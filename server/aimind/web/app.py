"""FastAPI 应用：口令校验、静态页面、WebSocket，挂上各个路由模块"""
from __future__ import annotations

import asyncio
import json
import secrets
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from .. import config as config_mod
from . import hub, routes_core, routes_devices, routes_eval

STATIC = Path(__file__).resolve().parent / "static"
LOCAL = ("127.0.0.1", "::1", "localhost", "testclient")


@asynccontextmanager
async def lifespan(_app):
    hub.loop = asyncio.get_running_loop()
    yield


app = FastAPI(title="AI 录音思考助手", lifespan=lifespan)
for r in (routes_core, routes_devices, routes_eval):
    app.include_router(r.router)
class _Static(StaticFiles):
    """界面文件每次都和服务端核对一下（有 ETag，没改就是 304，很快）：升级后不会用到旧的缓存脚本"""

    async def get_response(self, path, scope):
        resp = await super().get_response(path, scope)
        resp.headers["Cache-Control"] = "no-cache"
        return resp


app.mount("/static", _Static(directory=STATIC), name="static")


def token_ok(tok: str) -> bool:
    return secrets.compare_digest(tok or "", config_mod.load().get("server_token") or "-")


@app.middleware("http")
async def auth(request: Request, call_next):
    """本机访问不需要口令；其他设备（手机、别的电脑）必须带口令"""
    host = request.client.host if request.client else ""
    via_query = False
    tok = ""
    if host not in LOCAL:
        tok = request.headers.get("x-token") or request.cookies.get("aim_token") or ""
        if not token_ok(tok) and token_ok(request.query_params.get("token") or ""):
            tok, via_query = request.query_params["token"], True
        if not token_ok(tok):
            if request.url.path == "/":
                return Response("<meta charset=utf-8><p style='font:16px sans-serif;margin:40px'>"
                                "请用带口令的地址打开：在运行本程序的电脑上点「设备连接」，复制「在其他电脑上查看」的地址。</p>",
                                media_type="text/html", status_code=401)
            return JSONResponse({"detail": "口令不对，请检查 App 里填的连接口令"}, status_code=401)
    resp = await call_next(request)
    if via_query:   # 浏览器打开 /?token=xxx：记住口令，之后不用再带
        resp.set_cookie("aim_token", tok, max_age=3600 * 24 * 365, httponly=True, samesite="lax")
    return resp


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    host = ws.client.host if ws.client else ""
    if host not in LOCAL and not token_ok(ws.query_params.get("token") or "") \
            and not token_ok(ws.cookies.get("aim_token") or ""):
        await ws.close(code=4401)
        return
    await ws.accept()
    hub.clients.add(ws)
    await ws.send_text(json.dumps({"type": "state", **hub.engine.state()}, ensure_ascii=False))
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        hub.clients.discard(ws)
