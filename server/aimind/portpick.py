"""选端口：默认 8765；被别的程序占用了就自动换一个，并记在设置里（以后一直用它，手机地址不会变来变去）。

为什么需要：有的电脑上 8765 已经被别的服务占着（比如 Loon / Surge 的配置服务），
以前程序会以为“自己已经在运行”，直接打开那个地址——窗口里显示的是别人的页面。
现在会先问一下端口上的服务是不是 AI 录音思考助手（/api/state），是自己才复用。
"""
from __future__ import annotations

import http.client
import json
import socket

DEFAULT_PORT = 8765


def port_busy(port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def is_ours(port: int) -> bool:
    """这个端口上跑的是不是 AI 录音思考助手（直接连 127.0.0.1，不走系统代理）"""
    try:
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=1.5)
        c.request("GET", "/api/state")
        r = c.getresponse()
        if r.status != 200:
            return False
        j = json.loads(r.read(200_000) or b"{}")
        return isinstance(j, dict) and "recording" in j and "devices" in j
    except Exception:
        return False


def choose_port(env_port: str | None = None) -> tuple[int, bool, int]:
    """返回 (要用的端口, 这次是不是因为被占用而换了端口, 原来想用的端口)。
    环境变量指定了端口就照用，不自动换。"""
    if env_port:
        return int(env_port), False, int(env_port)
    from . import config
    try:
        want = int(config.load().get("server_port") or DEFAULT_PORT)
    except (TypeError, ValueError):
        want = DEFAULT_PORT
    if not port_busy(want) or is_ours(want):
        return want, False, want
    for p in range(want + 1, want + 50):
        if not port_busy(p) or is_ours(p):
            config.save({"server_port": p})
            return p, True, want
    return want, False, want     # 实在找不到空端口：照旧，启动时会报“端口打不开”
