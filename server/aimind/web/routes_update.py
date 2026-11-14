"""在线更新的接口：电脑端界面用 /api/update*，手机 App 通过电脑检查和下载（/api/update/mobile、/api/update/file/…）"""
from __future__ import annotations

import os
import threading
import time

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from .. import updater
from .hub import desktop_hooks, emit, engine

router = APIRouter(prefix="/api/update")


@router.get("")
def status():
    return updater.public_state()


@router.post("/check")
def check_now():
    out = updater.check(emit)
    out.pop("_manifest", None)
    return out


@router.post("/install")
def install():
    """后台下载并安装；进度和结果通过实时消息（type=update）推给界面"""
    def quit_app():
        hook = desktop_hooks.get("quit")
        if hook:
            hook()
        else:
            threading.Timer(1.0, os._exit, (0,)).start()

    def run():
        try:
            updater.install(emit, engine.recording, quit_app)
        except Exception as e:
            updater._st.update(error=str(e), installing=False)
            emit({"type": "update", **updater.public_state()})
            emit({"type": "error", "msg": f"更新失败：{e}"})

    if engine.recording:
        raise HTTPException(400, "正在录音，等这一场结束后再更新（录音不会丢）")
    problem = updater.install_problem()
    if problem:
        raise HTTPException(400, problem)
    threading.Thread(target=run, daemon=True).start()
    return {"ok": True}


# ---------- 手机 App：通过电脑检查和下载 ----------
ANDROID_KEYS = {"arm64-v8a": "android-arm64", "armeabi-v7a": "android-armv7"}


@router.get("/mobile")
def mobile(platform: str = "android", abi: str = "arm64-v8a"):
    st = updater.public_state()
    if not updater._st["manifest"] or time.time() - st["checked_at"] > 3600:
        updater.check(emit)
    m = updater._st["manifest"] or {}
    assets = m.get("assets") or {}
    if platform == "android":
        key = ANDROID_KEYS.get(abi, "android-arm64")
    else:   # iPhone：有签好名的就给签好名的
        key = "ios-signed" if "ios-signed" in assets else "ios"
    a = assets.get(key)
    return {"desktop_version": updater.VERSION, "latest": m.get("version", ""), "notes": m.get("notes", ""),
            "date": m.get("date", ""), "error": updater._st["error"],
            "asset": {"key": key, "name": a["name"], "size": a["size"], "sha256": a["sha256"]} if a else None}


@router.get("/file/{key}")
def mobile_file(key: str):
    """电脑替手机下载 APK（校验通过才给），手机从局域网拿，外出时走备用地址"""
    if key not in ANDROID_KEYS.values():
        raise HTTPException(404, "没有这个安装包")
    try:
        path = updater.download_asset(key, emit)
    except Exception as e:
        raise HTTPException(400, str(e))
    return FileResponse(path, media_type="application/vnd.android.package-archive", filename=path.name)
