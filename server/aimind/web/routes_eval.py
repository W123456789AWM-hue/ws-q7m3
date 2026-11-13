"""识别测试集：从录音里挑句子标注，比较几种本地识别引擎的准确率"""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel

from .. import evalset
from ..audio import SR
from ..session import SESSIONS_DIR, load_session
from .hub import emit, engine

router = APIRouter(prefix="/api/eval")


def _session(sid: str) -> dict:
    s = load_session(sid)
    if not s:
        raise HTTPException(404, "找不到")
    return s


def _segs(s: dict) -> list[dict]:
    return [seg for p in s.get("paragraphs", []) for seg in p["segments"]]


@router.get("/utts/{sid}")
def utts(sid: str):
    s = _session(sid)
    in_set = {x["i"]: x["ref"] for x in evalset.load_items() if x["sid"] == s["id"]}
    return [{"i": i, "clock": seg.get("clock"), "text": seg.get("text", ""),
             "sec": round(seg.get("n", 0) / SR, 1), "has_audio": seg.get("off", -1) >= 0,
             "in_set": i in in_set, "ref": in_set.get(i)}
            for i, seg in enumerate(_segs(s))]


@router.get("/audio")
def audio(sid: str, i: int):
    segs = _segs(_session(sid))
    if i < 0 or i >= len(segs) or segs[i].get("off", -1) < 0:
        raise HTTPException(404, "这一句没有保存录音")
    try:
        pcm = evalset.read_clip(SESSIONS_DIR / Path(sid).name, segs[i])
    except Exception:
        raise HTTPException(404, "录音文件不在了")
    return Response(evalset.wav_bytes(pcm), media_type="audio/wav")


@router.get("/item_audio/{item_id}")
def item_audio(item_id: int):
    for x in evalset.load_items():
        if x["id"] == item_id:
            return FileResponse(evalset.DIR / x["audio"], media_type="audio/wav")
    raise HTTPException(404, "找不到")


class EvalAdd(BaseModel):
    sid: str
    picks: list[dict]


@router.post("/add")
def add(body: EvalAdd):
    n = evalset.add_items(_session(body.sid), SESSIONS_DIR / Path(body.sid).name, body.picks)
    return {"ok": True, "added": n, **{k: v for k, v in evalset.summary().items() if k != "items"}}


@router.post("/remove/{item_id}")
def remove(item_id: int):
    evalset.remove_item(item_id)
    return {"ok": True}


@router.get("/set")
def get_set():
    return {**evalset.summary(), "engines": evalset.available_engines()}


@router.post("/run")
def run():
    if engine.recording:
        raise HTTPException(400, "正在录音，等这一场结束后再评测（评测会占用识别模型）")
    try:
        evalset.run_eval(emit)
    except Exception as e:
        raise HTTPException(400, str(e))
    return {"ok": True}


@router.get("/export")
def export():
    if not evalset.load_items():
        raise HTTPException(400, "测试集是空的")
    return FileResponse(evalset.export_zip(), filename="testset_export.zip")
