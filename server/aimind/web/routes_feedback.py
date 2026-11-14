"""用户反馈：电脑界面和手机 App 都发到这里，由电脑转发到开发者的飞书群（见 aimind/feedback.py）"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .. import feedback

router = APIRouter(prefix="/api/feedback")


class Feedback(BaseModel):
    kind: str = "other"
    text: str = ""
    contact: str = ""
    include_diag: bool = True
    source: str = ""
    client: str = ""


@router.get("")
def list_feedback():
    return {"configured": feedback.configured(), "items": feedback.history()}


@router.get("/diag")
def preview_diag():
    """发送前给用户看：会附带哪些诊断信息"""
    return {"text": feedback.diagnostics()}


@router.post("")
def send(fb: Feedback):
    try:
        return feedback.submit(fb.kind, fb.text, fb.contact, fb.include_diag, fb.source, fb.client)
    except RuntimeError as e:
        raise HTTPException(400, str(e))


@router.post("/retry")
def retry():
    return {"sent": feedback.retry_pending(), "items": feedback.history()}
