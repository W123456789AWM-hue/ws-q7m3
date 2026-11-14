"""用户反馈：设置里填写 → 发到开发者的飞书群（自定义机器人）。

- 机器人地址和签名密钥不写在代码里：云端打包时从 GitHub 密钥（FEEDBACK_WEBHOOK / FEEDBACK_SECRET）写进
  aimind/feedback_target.json 一起打包；本机开发 / 测试用环境变量 AIMIND_FEEDBACK_WEBHOOK / AIMIND_FEEDBACK_SECRET。
- 手机 App 的反馈先发给电脑（/api/feedback），由电脑转发：机器人地址只在电脑端程序里。
- 发不出去（没网、飞书暂时不可用）就存在 data/feedback/，后台每 5 分钟重试，不会丢。
- 诊断信息：版本、系统、最近的错误日志、最近一次检查更新的结果。不带录音、听写、复盘内容；
  日志里像密钥 / 口令的字符串会被抹掉。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import platform
import re
import sys
import threading
import time
import uuid
from pathlib import Path

from .config import DATA_DIR
from .version import VERSION

FEEDBACK_DIR = DATA_DIR / "feedback"
TARGET_FILE = Path(__file__).resolve().parent / "feedback_target.json"
RETRY_EVERY = 300
KINDS = {"bug": "问题", "idea": "建议", "other": "其他"}
MAX_TEXT = 4000

_lock = threading.Lock()


# ======================= 发到哪里 =======================
def target() -> tuple[str, str]:
    """(机器人地址, 签名密钥)；没配置时返回 ("", "")"""
    url = os.environ.get("AIMIND_FEEDBACK_WEBHOOK", "")
    secret = os.environ.get("AIMIND_FEEDBACK_SECRET", "")
    if not url and TARGET_FILE.exists():
        try:
            j = json.loads(TARGET_FILE.read_text(encoding="utf-8"))
            url, secret = j.get("webhook", ""), j.get("secret", "")
        except Exception:
            pass
    return url.strip(), secret.strip()


def configured() -> bool:
    return bool(target()[0])


# ======================= 诊断信息（脱敏） =======================
_SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_\-]{8,}"),                       # OpenAI 等的 API Key
    re.compile(r"github_pat_[A-Za-z0-9_]{10,}"),
    re.compile(r"(?i)(bearer|token|key|secret|password|口令|密钥)([\"'\s:=：]+)[^\s\"',}]{4,}"),
    re.compile(r"\b[A-Za-z0-9+/_\-]{32,}={0,2}"),                # 长串（可能是密钥 / 口令）
]


def redact(text: str) -> str:
    for p in _SECRET_PATTERNS:
        text = p.sub(lambda m: (m.group(1) + m.group(2) + "***") if m.lastindex and m.lastindex >= 2 else "***", text)
    return text


def diagnostics() -> str:
    from . import updater
    lines = [f"版本 {VERSION} · {sys.platform} {platform.release()} {platform.machine()}",
             f"打包程序：{'是' if getattr(sys, 'frozen', False) else '否（源码运行）'}"
             f" · Python {platform.python_version()}"]
    st = updater.public_state()
    if st.get("checked_at"):
        err = f"；错误：{st['error']}" if st.get("error") else ""
        lines.append(f"检查更新：最新 {st.get('latest') or '?'}{err}")
    log = DATA_DIR / "app_log.txt"
    if log.exists():
        with open(log, "rb") as f:          # 日志可能很大：只读最后 32KB
            f.seek(max(0, log.stat().st_size - 32768))
            tail = f.read().decode("utf-8", errors="replace").splitlines()[-60:]
        lines += ["--- 最近的程序日志 ---", *tail]
    return redact("\n".join(lines))[-6000:]


# ======================= 保存与发送 =======================
def _path(fid: str) -> Path:
    return FEEDBACK_DIR / f"{fid}.json"


def _save(item: dict) -> None:
    FEEDBACK_DIR.mkdir(parents=True, exist_ok=True)
    tmp = _path(item["id"]).with_suffix(".tmp")
    tmp.write_text(json.dumps(item, ensure_ascii=False), encoding="utf-8")
    tmp.replace(_path(item["id"]))


def history(limit: int = 30) -> list[dict]:
    if not FEEDBACK_DIR.exists():
        return []
    items = []
    for f in FEEDBACK_DIR.glob("*.json"):
        try:
            items.append(json.loads(f.read_text(encoding="utf-8")))
        except Exception:
            continue
    items.sort(key=lambda x: x.get("time", 0), reverse=True)
    return [{k: v for k, v in x.items() if k != "diag"} for x in items[:limit]]


def _card(item: dict) -> dict:
    """飞书消息卡片：标题带类型和来源，正文是用户写的内容，诊断信息放在后面"""
    kind = KINDS.get(item["kind"], "其他")
    src = item.get("source") or "电脑"
    head = f"【{kind}】AI 录音思考助手 {item.get('version', '')} · {src}"
    body = [f"**内容**\n{item['text']}"]
    if item.get("contact"):
        body.append(f"**联系方式**：{item['contact']}")
    body.append(f"**时间**：{time.strftime('%Y-%m-%d %H:%M', time.localtime(item['time']))}　**编号**：{item['id']}")
    elements = [{"tag": "div", "text": {"tag": "lark_md", "content": "\n".join(body)}}]
    if item.get("diag"):
        elements += [{"tag": "hr"}, {"tag": "div", "text": {"tag": "plain_text", "content": item["diag"][-3500:]}}]
    color = {"bug": "red", "idea": "blue"}.get(item["kind"], "grey")
    return {"msg_type": "interactive", "card": {
        "header": {"title": {"tag": "plain_text", "content": head}, "template": color}, "elements": elements}}


def _sign(secret: str, ts: int) -> str:
    """飞书签名：HmacSHA256(key = "时间戳\\n密钥", 消息为空) 再 base64"""
    return base64.b64encode(hmac.new(f"{ts}\n{secret}".encode(), b"", hashlib.sha256).digest()).decode()


def _send(item: dict) -> None:
    url, secret = target()
    if not url:
        raise RuntimeError("这个版本还没配置反馈通道")
    payload = _card(item)
    if secret:
        ts = int(time.time())
        payload.update(timestamp=str(ts), sign=_sign(secret, ts))
    import urllib.request

    from . import updater  # 同一套 HTTPS 证书（Mac 打包程序需要）
    req = urllib.request.Request(url, data=json.dumps(payload, ensure_ascii=False).encode(),
                                 headers={"Content-Type": "application/json"})
    opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=updater.ssl_context()))
    with opener.open(req, timeout=15) as r:
        resp = json.loads(r.read() or b"{}")
    code = resp.get("code", resp.get("StatusCode", 0))
    if code not in (0, None):
        raise RuntimeError(f"飞书返回错误 {code}：{resp.get('msg') or resp.get('StatusMessage')}")


def _try_send(item: dict) -> dict:
    try:
        _send(item)
        item.update(status="sent", error="", sent_at=time.time())
    except Exception as e:
        item.update(status="pending", error=str(e)[:200])
    item["tries"] = item.get("tries", 0) + 1
    _save(item)
    return item


def submit(kind: str, text: str, contact: str = "", include_diag: bool = True, source: str = "",
           client: str = "") -> dict:
    """client：手机 App 发来时附带的手机版本和系统（放在诊断信息最前面）"""
    text = (text or "").strip()
    if not text:
        raise RuntimeError("请先写一下反馈内容")
    item = {"id": time.strftime("%m%d") + "-" + uuid.uuid4().hex[:6], "time": time.time(),
            "kind": kind if kind in KINDS else "other", "text": text[:MAX_TEXT],
            "contact": (contact or "").strip()[:100],
            "source": (source or "").strip()[:60], "version": VERSION, "status": "pending", "error": ""}
    if include_diag:
        client = redact((client or "").strip()[:300])
        item["diag"] = (f"发送设备：{client}\n电脑端：" if client else "") + diagnostics()
    with _lock:
        _save(item)
        item = _try_send(item)
    return {k: v for k, v in item.items() if k != "diag"}


def retry_pending() -> int:
    """把没发出去的再发一次，返回这次发成功的条数"""
    ok = 0
    with _lock:
        for f in sorted(FEEDBACK_DIR.glob("*.json")) if FEEDBACK_DIR.exists() else []:
            try:
                item = json.loads(f.read_text(encoding="utf-8"))
            except Exception:
                continue
            if item.get("status") == "pending" and _try_send(item)["status"] == "sent":
                ok += 1
    return ok


def start_retry_loop() -> None:
    def loop():
        while True:
            time.sleep(RETRY_EVERY)
            try:
                retry_pending()
            except Exception:
                pass
    threading.Thread(target=loop, daemon=True, name="feedback-retry").start()
