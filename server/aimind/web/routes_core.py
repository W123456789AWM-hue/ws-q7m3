"""设置、连接测试、录音控制、每日复盘、历史记录"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import threading
from datetime import datetime
from pathlib import Path

import numpy as np
from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from .. import config as config_mod
from .. import nas
from ..audio.mic import list_mics
from ..review import daily
from ..review.listen import test_audio
from ..review.llm import chat
from ..session import SESSIONS_DIR, list_sessions, load_session, render_markdown
from ..stt.transcriber import Transcriber
from .hub import emit, engine, guard

router = APIRouter(prefix="/api")


# ---------- 状态与设置 ----------
@router.get("/state")
def get_state():
    return engine.state()


@router.get("/config")
def get_config():
    return config_mod.load()


@router.post("/config")
def set_config(cfg: dict):
    return config_mod.save(cfg)


@router.get("/usage")
def get_usage(date: str = ""):
    """AI 用量（token）统计，默认今天"""
    from ..review import usage
    return usage.day_summary(date or None)


@router.get("/app_info")
def app_info():
    """界面用来判断：是不是在桌面程序里（能不能预览启动动画）"""
    from ..version import VERSION
    return {"app": "aimind", "version": VERSION, "desktop": bool(os.environ.get("AIMIND_DESKTOP")),
            "platform": sys.platform, "frozen": bool(getattr(sys, "frozen", False)),
            "port": int(os.environ.get("AIMIND_PORT") or 8765)}


@router.post("/splash_preview")
def splash_preview():
    """在桌面程序里按当前设置的速度播放一遍启动动画（Windows、Mac 都行）"""
    from .hub import desktop_hooks
    hook = desktop_hooks.get("splash_preview")
    if not hook:
        raise HTTPException(400, "只有在桌面程序里才能预览启动动画")
    hook(float(config_mod.load().get("splash_speed") or 1))
    return {"ok": True}


@router.get("/devices")
def mics():
    """这台电脑上的麦克风"""
    return list_mics()


@router.get("/model")
def model_status():
    from ..stt.local import sv_dir, sv_ready
    return {"sensevoice_ready": sv_ready(), "dir": str(sv_dir())}


# ---------- 连接测试 ----------
def _try(fn, ok_msg):
    try:
        return {"ok": True, "msg": ok_msg(fn())}
    except Exception as e:
        return {"ok": False, "msg": str(e)}


@router.post("/test/audio")
def t_audio():
    return _try(lambda: test_audio(config_mod.load()), lambda m: m)


@router.post("/test/llm")
def t_llm():
    return _try(lambda: chat(config_mod.load(), "你是测试助手。", "请只回复：连接成功", max_tokens=50),
                lambda out: f"AI 接口正常，回复：{out}")


@router.post("/test/nas")
def t_nas():
    return nas.test_write(config_mod.load())


@router.post("/test/stt")
def t_stt():
    cfg = config_mod.load()
    pcm = (np.random.randn(16000) * 30).astype("int16")
    if (cfg.get("stt_provider") or "sensevoice") == "api":
        return _try(lambda: Transcriber(cfg).transcribe(pcm),
                    lambda text: f"在线识别接口正常（返回：{text or '空，静音正常'}）")

    def job():
        try:
            t = Transcriber(cfg)
            t.prepare(lambda m: emit({"type": "model", "msg": m}))
            t.transcribe(pcm)
            engine.transcriber = t
            emit({"type": "model", "done": True,
                  "msg": "⚠ " + t.warning if t.warning else "✅ 本地识别正常，可以开始录音"})
        except Exception as e:
            emit({"type": "error", "msg": f"本地识别不可用：{e}"})

    threading.Thread(target=job, daemon=True).start()
    return {"ok": True, "msg": "正在检查本地识别模型（首次会自动下载），进度见页面顶部"}


# ---------- 录音控制 ----------
@router.post("/start")
def start():
    """用这台电脑的麦克风录音（和手机等设备可以同时录）"""
    return guard(engine.start_mic)


@router.post("/stop")
def stop():
    """停止这台电脑的麦克风；其他设备还在录的话这一场继续"""
    return guard(engine.stop_mic)


@router.post("/finish")
def finish():
    """结束这一场：所有设备的内容马上做整场总复盘"""
    return guard(engine.finish_now)


@router.post("/review_now")
def review_now():
    return guard(engine.review_now)


@router.post("/retry_review/{rid}")
def retry_review(rid: int):
    return guard(lambda: engine.retry_review(rid))


@router.post("/import")
async def import_wav(file: UploadFile = File(...)):
    dst = Path(tempfile.mkdtemp()) / Path(file.filename or "upload.wav").name
    with open(dst, "wb") as f:
        shutil.copyfileobj(file.file, f)
    return guard(lambda: engine.import_file(dst))


class TextIn(BaseModel):
    text: str


@router.post("/analyze_text")
def analyze_text(body: TextIn):
    if len(body.text.strip()) < 5:
        raise HTTPException(400, "文字太短")
    return guard(lambda: engine.analyze_text(body.text))


# ---------- 每日复盘 ----------
def _today(date: str) -> str:
    return Path(date).name if date else datetime.now().strftime("%Y-%m-%d")


@router.get("/report")
def get_report(period: str = "day", key: str = ""):
    """日 / 月 / 年复盘。period = day / month / year；key = 2026-11-13 / 2026-11 / 2026（默认当前）"""
    key = key or _default_key(period)
    return {"period": period, "key": key, "md": daily.read_report(period, key) if period in daily.DIRS else "",
            "has_data": daily.has_data(period, key) if period in daily.DIRS else False}


@router.post("/report")
def make_report(period: str = "day", key: str = ""):
    key = key or _default_key(period)
    return guard(lambda: {"period": period, "key": key, "md": daily.make_report(period, key, emit)})


@router.get("/reports")
def list_reports(period: str = "month"):
    """已经生成过的复盘（新的在前）"""
    return daily.list_reports(period) if period in daily.DIRS else []


def _default_key(period: str) -> str:
    now = datetime.now()
    return now.strftime({"month": "%Y-%m", "year": "%Y"}.get(period, "%Y-%m-%d"))


@router.get("/daily")
def get_daily(date: str = ""):
    d = _today(date)
    return {"date": d, "md": daily.read(d)}


@router.post("/daily")
def make_daily(date: str = ""):
    d = _today(date)
    return guard(lambda: {"date": d, "md": daily.make(d, emit)})


# ---------- 历史 ----------
@router.get("/sessions")
def sessions():
    return list_sessions()


def _load(sid: str) -> dict:
    s = load_session(sid)
    if not s:
        raise HTTPException(404, "找不到")
    return s


@router.get("/sessions/{sid}")
def session(sid: str):
    return _load(sid)


@router.get("/sessions/{sid}/report.md", response_class=PlainTextResponse)
def report(sid: str):
    return render_markdown(_load(sid))


@router.post("/open_folder/{sid}")
def open_folder(sid: str):
    d = SESSIONS_DIR / Path(sid).name
    if d.exists():
        if sys.platform == "win32":
            os.startfile(d)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            os.system(f'open "{d}"')
    return {"ok": True, "path": str(d)}
