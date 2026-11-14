"""在线更新：检查 → 下载 → 校验 → 安装。

发布方（云端打包，见 .github/workflows/build-all.yml）：每个版本在公开的发布仓库放安装包 + latest.json（版本、说明、
各平台安装包的地址 / 大小 / sha256）+ latest.json.sig（用私钥对 latest.json 原文做的 Ed25519 签名）。

这边：
  1. 下载 latest.json 和签名，用程序里内置的公钥验证（不对就拒绝：防止下载地址被劫持后推送恶意程序）
  2. 版本比现在新 → 告诉界面（顶栏小提示、设置里「软件更新」）
  3. 用户点更新：下载本平台的安装包，核对大小和 sha256
  4. Windows：启动安装程序（--silent --upgrade --wait-pid --relaunch）后自己退出；
     安装程序等旧版退出 → 换上新版 → 重新打开
     Mac：启动一个小脚本后自己退出；脚本等旧版退出 → 挂载 dmg → 换掉 .app → 重新打开
  5. 手机 App 通过电脑更新：电脑替手机下载 APK（同样校验），手机从电脑的局域网地址下载
录音、复盘、设置都在数据目录里，更新不会动它们。
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import platform
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

from . import config as config_mod
from . import ed25519
from .config import DATA_DIR
from .version import MANIFEST_URL, UPDATE_PUBLIC_KEY, VERSION, newer

UPDATES_DIR = DATA_DIR / "updates"
CHECK_EVERY = 6 * 3600
FROZEN = bool(getattr(sys, "frozen", False))

_lock = threading.Lock()
_st: dict = {"checking": False, "checked_at": 0.0, "manifest": None, "error": "",
             "downloading": "", "progress": 0, "installing": False}


# ======================= 平台 =======================
def platform_key() -> str | None:
    if sys.platform == "win32":
        return "windows"
    if sys.platform == "darwin":
        return "mac-arm64" if platform.machine().lower() in ("arm64", "aarch64") else "mac-intel"
    return None


def install_problem() -> str:
    """不能自动安装的原因（空 = 可以）"""
    if not FROZEN:
        return "现在是用源码方式运行的，请用 git pull 更新代码"
    key = platform_key()
    if key is None:
        return "这个系统不支持自动安装"
    if key == "windows":
        here = Path(sys.executable).resolve().parent
        extra = {p.name.lower() for p in here.iterdir()} - {"aimind.exe", "_internal", "uninstall.ps1"}
        if extra:   # 绿色版放在了有别的文件的文件夹里：自动替换可能误删东西
            return f"程序所在的文件夹（{here}）里还有别的文件，为安全起见不自动替换。请下载安装程序手动安装"
    return ""


# ======================= 下载与校验 =======================
def _url(url: str, cfg: dict) -> str:
    """设置里填了下载镜像（比如 https://ghproxy.net/）就加在前面"""
    mirror = (cfg.get("update_mirror") or "").strip()
    return mirror.rstrip("/") + "/" + url if mirror else url


def _open(url: str, timeout: float = 30):
    # urllib 会用系统代理（Windows 注册表 / Mac 系统设置），和浏览器一样能连上 GitHub
    req = urllib.request.Request(url, headers={"User-Agent": f"AIMind/{VERSION}"})
    return urllib.request.urlopen(req, timeout=timeout)


PUBLIC_KEY = UPDATE_PUBLIC_KEY      # 测试时可以换成临时密钥


def verify_manifest(raw: bytes, sig_b64: bytes, public_key: str | None = None) -> dict:
    public_key = public_key or PUBLIC_KEY
    try:
        ok = ed25519.verify(base64.b64decode(public_key), raw, base64.b64decode(sig_b64.strip()))
    except Exception:
        ok = False
    if not ok:
        raise RuntimeError("更新清单的签名验证不通过，已拒绝（可能被篡改，或者下载不完整）")
    m = json.loads(raw)
    if not isinstance(m, dict) or not isinstance(m.get("version"), str) or not isinstance(m.get("assets"), dict):
        raise RuntimeError("更新清单格式不对")
    return m


def fetch_manifest(cfg: dict) -> dict:
    url = (cfg.get("update_manifest_url") or "").strip() or MANIFEST_URL
    raw = _open(_url(url, cfg)).read()
    sig = _open(_url(url + ".sig", cfg)).read()
    return verify_manifest(raw, sig)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def download_asset(key: str, emit=lambda m: None) -> Path:
    """下载某个平台的安装包到 data/updates/，校验大小和 sha256；已经下好且校验通过的直接用"""
    m = _st["manifest"] or check(emit)["_manifest"]
    a = (m or {}).get("assets", {}).get(key)
    if not a:
        raise RuntimeError(f"新版本里没有这个平台（{key}）的安装包")
    UPDATES_DIR.mkdir(parents=True, exist_ok=True)
    dst = UPDATES_DIR / Path(a["name"]).name
    if dst.exists() and dst.stat().st_size == a["size"] and _sha256(dst) == a["sha256"]:
        return dst
    part = dst.with_suffix(dst.suffix + ".part")
    cfg = config_mod.load()
    _st.update(downloading=key, progress=0, error="")
    try:
        with _open(_url(a["url"], cfg), timeout=60) as r, open(part, "wb") as f:
            total, got, last = int(a["size"]), 0, 0.0
            while chunk := r.read(1 << 16):
                f.write(chunk)
                got += len(chunk)
                if time.time() - last > 0.3:
                    last = time.time()
                    _st["progress"] = min(99, int(got * 100 / max(total, 1)))
                    emit({"type": "update", **public_state()})
        if part.stat().st_size != a["size"] or _sha256(part) != a["sha256"]:
            part.unlink(missing_ok=True)
            raise RuntimeError("下载的文件校验不通过（可能下载不完整或被篡改），已删除，请重试")
        part.replace(dst)
        for old in UPDATES_DIR.iterdir():          # 只留这个版本的安装包
            if old.name != dst.name and not old.name.endswith(".part"):
                old.unlink(missing_ok=True)
        return dst
    finally:
        _st.update(downloading="", progress=0)
        emit({"type": "update", **public_state()})


# ======================= 检查 =======================
def public_state() -> dict:
    m = _st["manifest"] or {}
    key = platform_key()
    latest = m.get("version", "")
    return {"current": VERSION, "latest": latest, "notes": m.get("notes", ""), "date": m.get("date", ""),
            "available": bool(latest) and newer(latest, VERSION) and bool(key and key in m.get("assets", {})),
            "size": (m.get("assets", {}).get(key) or {}).get("size", 0) if key else 0,
            "install_problem": install_problem(), "checking": _st["checking"], "checked_at": _st["checked_at"],
            "downloading": _st["downloading"], "progress": _st["progress"], "installing": _st["installing"],
            "error": _st["error"], "platform": key or sys.platform}


def check(emit=lambda m: None) -> dict:
    with _lock:
        _st.update(checking=True, error="")
        emit({"type": "update", **public_state()})
        try:
            _st["manifest"] = fetch_manifest(config_mod.load())
        except Exception as e:
            _st["error"] = f"检查更新失败：{e}"
        finally:
            _st.update(checking=False, checked_at=time.time())
    out = public_state()
    emit({"type": "update", **out})
    return {**out, "_manifest": _st["manifest"]}


def start_auto_check(emit) -> None:
    """后台：启动 20 秒后检查一次，之后每 6 小时一次（设置里可以关）。只在打包好的程序里自动检查"""
    if not (FROZEN or os.environ.get("AIMIND_UPDATE_CHECK")):
        return

    def loop():
        time.sleep(20)
        while True:
            if config_mod.load().get("update_auto_check", True):
                check(emit)
            time.sleep(CHECK_EVERY)

    threading.Thread(target=loop, daemon=True, name="update-check").start()


# ======================= 安装 =======================
_MAC_SCRIPT = r"""#!/bin/bash
# AI 录音思考助手 在线更新：等旧版退出 → 挂载新版 dmg → 换掉 .app → 重新打开
pid="$1"; dmg="$2"; app="$3"
for i in $(seq 1 200); do kill -0 "$pid" 2>/dev/null || break; sleep 0.3; done
mnt="$(mktemp -d)"
if hdiutil attach -nobrowse -quiet -mountpoint "$mnt" "$dmg"; then
  src="$(ls -d "$mnt"/*.app | head -1)"
  rm -rf "$app.new" "$app.old"
  if ditto "$src" "$app.new" && mv "$app" "$app.old" && mv "$app.new" "$app"; then rm -rf "$app.old"
  else [ -d "$app.old" ] && [ ! -d "$app" ] && mv "$app.old" "$app"; fi
  hdiutil detach -quiet "$mnt"
  xattr -cr "$app" 2>/dev/null
fi
open "$app"
"""


def install(emit, recording: bool, quit_app) -> None:
    """下载并安装新版本。quit_app()：让程序退出（桌面程序注册的钩子）"""
    if recording:
        raise RuntimeError("正在录音，等这一场结束后再更新（录音不会丢）")
    problem = install_problem()
    if problem:
        raise RuntimeError(problem)
    if not public_state()["available"]:
        raise RuntimeError("已经是最新版本")
    key = platform_key()
    path = download_asset(key, emit)
    _st["installing"] = True
    emit({"type": "update", **public_state()})
    if key == "windows":
        flags = 0x00000008 | 0x00000200      # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP：程序退出后安装程序继续跑
        subprocess.Popen([str(path), "--silent", "--upgrade", "--wait-pid", str(os.getpid()), "--relaunch"],
                         creationflags=flags, close_fds=True)
    else:
        app = Path(sys.executable).resolve().parents[2]          # …/AI录音思考助手.app/Contents/MacOS/AIMind
        script = Path(tempfile.gettempdir()) / "aimind_update.sh"
        script.write_text(_MAC_SCRIPT, encoding="utf-8")
        subprocess.Popen(["/bin/bash", str(script), str(os.getpid()), str(path), str(app)],
                         start_new_session=True, close_fds=True)
    emit({"type": "status", "msg": "正在安装新版本，程序会自动重新打开…"})
    quit_app()
