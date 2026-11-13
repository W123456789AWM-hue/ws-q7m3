"""全局单例：引擎、设备接收、WebSocket 推送。各个路由模块都从这里拿"""
from __future__ import annotations

import asyncio
import json

from fastapi import HTTPException, WebSocket

from ..devices import DeviceIngest
from ..engine import Engine

clients: set[WebSocket] = set()
desktop_hooks: dict = {}     # 桌面程序（desktop_app.py）注册的功能，比如预览启动动画；浏览器方式运行时为空
loop: asyncio.AbstractEventLoop | None = None


async def broadcast(msg: dict):
    data = json.dumps(msg, ensure_ascii=False)
    for ws in list(clients):
        try:
            await ws.send_text(data)
        except Exception:
            clients.discard(ws)


def emit(msg: dict):
    """可以从任何线程调用"""
    if loop is not None:
        asyncio.run_coroutine_threadsafe(broadcast(msg), loop)


engine = Engine(emit)
ingest = DeviceIngest(engine, emit)


def guard(fn):
    """调用 fn，出错就变成 HTTP 400（错误信息直接给界面显示）"""
    try:
        out = fn()
    except Exception as e:
        raise HTTPException(400, str(e))
    return out if isinstance(out, dict) else {"ok": True}
