"""用户反馈：设置里填写 → 发到开发者的飞书群（自定义机器人）。

- 机器人地址和签名密钥不写在代码里：云端打包时从 GitHub 密钥（FEEDBACK_WEBHOOK / FEEDBACK_SECRET）写进
  aimind/feedback_target.json 一起打包；本机开发 / 测试用环境变量 AIMIND_FEEDBACK_WEBHOOK / AIMIND_FEEDBACK_SECRET。
- 手机 App 的反馈先发给电脑（/api/feedback），由电脑转发：机器人地址只在电脑端程序里。
- 发不出去（没网、飞书暂时不可用）就存在 data/feedback/，后台每 5 分钟重试，不会丢。
- 附图（选填，最多 3 张）：自定义机器人不能传图，要另配一个飞书「企业自建应用」（FEEDBACK_APP_ID / FEEDBACK_APP_SECRET，
  权限 im:resource）先上传拿到 image_key 再放进卡片。
  没配或上传失败时卡片里注明“有 N 张附图没能显示”，图片留在用户电脑上。
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
MAX_IMAGES = 3
MAX_IMAGE_BYTES = 8 << 20           # 飞书上传上限 10MB；界面会先压缩到 1~2MB
_IMG_MAGIC = {b"\xff\xd8\xff": "jpg", b"\x89PNG": "png", b"GIF8": "gif"}
FEISHU = "https://open.feishu.cn/open-apis"

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


def image_app() -> tuple[str, str]:
    """上传图片用的飞书自建应用 (app_id, app_secret)；没配置时返回 ("", "")"""
    aid = os.environ.get("AIMIND_FEEDBACK_APP_ID", "")
    sec = os.environ.get("AIMIND_FEEDBACK_APP_SECRET", "")
    if not aid and TARGET_FILE.exists():
        try:
            j = json.loads(TARGET_FILE.read_text(encoding="utf-8"))
            aid, sec = j.get("app_id", ""), j.get("app_secret", "")
        except Exception:
            pass
    return aid.strip(), sec.strip()


def images_configured() -> bool:
    return all(image_app())


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


def _img_dir(fid: str) -> Path:
    return FEEDBACK_DIR / fid


def _image_ext(data: bytes) -> str:
    for magic, ext in _IMG_MAGIC.items():
        if data.startswith(magic):
            return ext
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    raise RuntimeError("附图只支持 JPG / PNG / WEBP / GIF 图片")


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
    return [_public(x) for x in items[:limit]]


def _public(item: dict) -> dict:
    """给界面看的：不带诊断信息和图片标识"""
    return {k: v for k, v in item.items() if k not in ("diag", "image_keys")}


def _card(item: dict, no_images: bool = False, image_note: str = "") -> dict:
    """飞书消息卡片：标题带类型和来源，正文是用户写的内容，诊断信息放在后面"""
    kind = KINDS.get(item["kind"], "其他")
    src = item.get("source") or "电脑"
    head = f"【{kind}】AI 录音思考助手 {item.get('version', '')} · {src}"
    body = [f"**内容**\n{item['text']}"]
    if item.get("contact"):
        body.append(f"**联系方式**：{item['contact']}")
    body.append(f"**时间**：{time.strftime('%Y-%m-%d %H:%M', time.localtime(item['time']))}　**编号**：{item['id']}")
    elements = [{"tag": "div", "text": {"tag": "lark_md", "content": "\n".join(body)}}]
    keys = [] if no_images else [k for k in (item.get("image_keys") or {}).values() if k]
    for i, k in enumerate(keys):
        elements.append({"tag": "img", "img_key": k, "alt": {"tag": "plain_text", "content": f"附图 {i + 1}"},
                         "mode": "fit_horizontal", "preview": True})
    missing = len(item.get("images") or []) - len(keys)
    if missing > 0:
        why = f"（{image_note}）" if image_note else ""
        msg = f"还有 {missing} 张附图没能显示{why}，图片存在用户电脑的 feedback/{item['id']} 里"
        elements.append({"tag": "note", "elements": [{"tag": "plain_text", "content": msg}]})
    if item.get("diag"):
        elements += [{"tag": "hr"}, {"tag": "div", "text": {"tag": "plain_text", "content": item["diag"][-3500:]}}]
    color = {"bug": "red", "idea": "blue"}.get(item["kind"], "grey")
    return {"msg_type": "interactive", "card": {
        "header": {"title": {"tag": "plain_text", "content": head}, "template": color}, "elements": elements}}


def _sign(secret: str, ts: int) -> str:
    """飞书签名：HmacSHA256(key = "时间戳\\n密钥", 消息为空) 再 base64"""
    return base64.b64encode(hmac.new(f"{ts}\n{secret}".encode(), b"", hashlib.sha256).digest()).decode()


def _http(url: str, data: bytes, ctype: str, headers: dict | None = None, timeout: int = 15) -> dict:
    """POST，返回飞书的 JSON；code 不为 0 时抛错"""
    import urllib.error
    import urllib.request

    from . import updater  # 同一套 HTTPS 证书（Mac 打包程序需要）
    req = urllib.request.Request(url, data=data, headers={"Content-Type": ctype, **(headers or {})})
    opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=updater.ssl_context()))
    try:
        with opener.open(req, timeout=timeout) as r:
            resp = json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:         # 飞书出错时也会带 JSON 说明
        try:
            resp = json.loads(e.read() or b"{}")
        except Exception:
            resp = {}
        if resp.get("code", resp.get("StatusCode", 0)) in (0, None):
            raise RuntimeError(f"飞书返回 HTTP {e.code}") from None
    code = resp.get("code", resp.get("StatusCode", 0))
    if code not in (0, None):
        raise RuntimeError(f"飞书返回错误 {code}：{resp.get('msg') or resp.get('StatusMessage')}")
    return resp


_token = {"value": "", "until": 0.0}


def _app_token() -> str:
    """自建应用的 tenant_access_token（两小时有效，提前 5 分钟换新）"""
    if _token["value"] and time.time() < _token["until"]:
        return _token["value"]
    aid, sec = image_app()
    r = _http(f"{FEISHU}/auth/v3/tenant_access_token/internal",
              json.dumps({"app_id": aid, "app_secret": sec}).encode(), "application/json")
    _token.update(value=r["tenant_access_token"], until=time.time() + int(r.get("expire", 7200)) - 300)
    return _token["value"]


def _upload_image(path: Path) -> str:
    boundary = "----aimind" + uuid.uuid4().hex
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"image_type\"\r\n\r\nmessage\r\n"
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"image\"; filename=\"{path.name}\"\r\n"
            f"Content-Type: application/octet-stream\r\n\r\n").encode()
    body += path.read_bytes() + f"\r\n--{boundary}--\r\n".encode()
    r = _http(f"{FEISHU}/im/v1/images", body, f"multipart/form-data; boundary={boundary}",
              {"Authorization": f"Bearer {_app_token()}"}, timeout=60)
    return r["data"]["image_key"]


def _upload_images(item: dict) -> str:
    """把还没上传的附图传到飞书，image_key 记在 item 里（重试时不重复传）。返回没传成功的原因"""
    names = item.get("images") or []
    if not names:
        return ""
    if not images_configured():
        return "这个版本还没接通图片通道"
    keys = item.setdefault("image_keys", {})
    err = ""
    for n in names:
        if keys.get(n):
            continue
        try:
            keys[n] = _upload_image(_img_dir(item["id"]) / n)
        except Exception as e:
            err = f"图片上传失败：{str(e)[:120]}"
    return err


def _post_card(payload: dict) -> None:
    url, secret = target()
    if secret:
        ts = int(time.time())
        payload.update(timestamp=str(ts), sign=_sign(secret, ts))
    _http(url, json.dumps(payload, ensure_ascii=False).encode(), "application/json")


def _send(item: dict) -> None:
    if not target()[0]:
        raise RuntimeError("这个版本还没配置反馈通道")
    note = _upload_images(item)
    try:
        _post_card(_card(item, image_note=note))
    except RuntimeError as e:
        if not item.get("image_keys"):
            raise
        # 卡片里的图片不被接受（比如图片和机器人不在同一个飞书组织）：文字先送到，注明原因
        _post_card(_card(item, no_images=True, image_note=f"卡片放不进图片：{str(e)[:120]}"))


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
           client: str = "", images: list[bytes] | None = None) -> dict:
    """client：手机 App 发来时附带的手机版本和系统（放在诊断信息最前面）；images：附图原始字节（选填）"""
    text = (text or "").strip()
    if not text:
        raise RuntimeError("请先写一下反馈内容")
    images = [b for b in (images or []) if b]
    if len(images) > MAX_IMAGES:
        raise RuntimeError(f"附图最多 {MAX_IMAGES} 张")
    if any(len(b) > MAX_IMAGE_BYTES for b in images):
        raise RuntimeError("附图太大了（每张不超过 8MB）")
    exts = [_image_ext(b) for b in images]
    item = {"id": time.strftime("%m%d") + "-" + uuid.uuid4().hex[:6], "time": time.time(),
            "kind": kind if kind in KINDS else "other", "text": text[:MAX_TEXT],
            "contact": (contact or "").strip()[:100],
            "source": (source or "").strip()[:60], "version": VERSION, "status": "pending", "error": ""}
    if include_diag:
        client = redact((client or "").strip()[:300])
        item["diag"] = (f"发送设备：{client}\n电脑端：" if client else "") + diagnostics()
    if images:
        d = _img_dir(item["id"])
        d.mkdir(parents=True, exist_ok=True)
        item["images"] = []
        for i, (b, ext) in enumerate(zip(images, exts), 1):
            (d / f"{i}.{ext}").write_bytes(b)
            item["images"].append(f"{i}.{ext}")
    with _lock:
        _save(item)
        item = _try_send(item)
    return _public(item)


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
