"""录音设备（手机/平板/别的电脑）：上传录音、查看状态、连接信息、改名"""
from __future__ import annotations

import os
import socket

from fastapi import APIRouter, Request
from pydantic import BaseModel

from .. import config as config_mod
from .hub import engine, ingest

router = APIRouter(prefix="/api")


@router.post("/phone/chunk")
async def chunk(request: Request, stream: str, seq: int, start: str, dur: float = 0,
                silent: int = 0, enc: str = "pcm", device: str = "", name: str = ""):
    """上传一片录音（16kHz 单声道；enc=pcm 16bit，enc=adpcm 4:1 压缩；silent=1 是静音片，不带数据）。
    device = 设备编号（每台设备不同），name = 显示的名字"""
    data = await request.body()
    return ingest.accept(device, name, stream, seq, start, dur, bool(silent), data, enc=enc)


@router.post("/phone/stop")
def phone_stop(stream: str, seq: int, device: str = "", name: str = ""):
    """这台设备停止录音。所有设备都停了，这一场就收尾"""
    return ingest.accept(device, name, stream, seq, "", 0, False, b"", kind="stop")


def _voice_placeholder(p: dict) -> str:
    sec = sum(x.get("sec", 0) for x in p.get("segments", []))
    return f"🎙 {int(round(sec))} 秒语音（AI 复盘时会听写出来）" if sec else ""


@router.get("/phone/view")
def phone_view():
    """给手机看的精简状态：不带大段原文，只带最近 40 段"""
    st = engine.state()
    s = st["session"]
    if s:
        s = dict(s)
        s["reviews"] = [{k: v for k, v in r.items() if k != "text"} for r in s["reviews"]]
        s["paragraph_count"] = len(s["paragraphs"])
        s["paragraphs"] = [{"id": p["id"], "start_clock": p["start_clock"],
                            "device_name": p.get("device_name", ""),
                            "text": p["text"] or _voice_placeholder(p),
                            "status": p["status"]} for p in s["paragraphs"][-40:]]
    return {"session": s, "recording": st["recording"], "source": st["source"],
            "devices": st["devices"], "next_review": st["next_review"], **ingest.status()}


def _local_ips() -> set[str]:
    ips = set()
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        ips.add(s.getsockname()[0])
        s.close()
    except Exception:
        pass
    try:
        ips.update(socket.gethostbyname_ex(socket.gethostname())[2])
    except Exception:
        pass
    return {ip for ip in ips if not ip.startswith("127.")}


@router.get("/phone/info")
def phone_info():
    """电脑界面上显示：设备该填什么地址和口令；100.x 是 Tailscale 地址，在外面时用"""
    port = int(os.environ.get("AIMIND_PORT") or os.environ.get("AI_MIND_PORT") or 8765)
    ips = sorted(_local_ips())
    lan = [f"http://{ip}:{port}" for ip in ips if not ip.startswith("100.")]
    away = [f"http://{ip}:{port}" for ip in ips if ip.startswith("100.")]
    tok = config_mod.load().get("server_token")
    return {"urls": lan, "away_urls": away, "view_urls": [f"{u}/?token={tok}" for u in lan + away],
            "token": tok, **ingest.status()}


class Rename(BaseModel):
    name: str


@router.post("/phones/{dev}/rename")
def rename(dev: str, body: Rename):
    ingest.rename(dev, body.name.strip()[:30] or dev)
    return {"ok": True}


@router.post("/phones/{dev}/forget")
def forget(dev: str):
    ingest.forget(dev)
    return {"ok": True}
