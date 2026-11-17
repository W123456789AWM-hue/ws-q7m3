"""文字 AI：OpenAI 兼容接口 / Claude / Google Gemini。用于整场总复盘、日复盘、文字模式的复盘。"""
from __future__ import annotations

import json
import os
import re
from typing import Optional

import httpx

from . import usage

TIMEOUT = httpx.Timeout(120.0, connect=15.0)
class _Client(httpx.Client):
    """连接池里的旧连接可能刚好被服务器关掉（空闲几秒就关，各家不同）：
    这时请求还没被处理就断了，自动换新连接重发一次（不会重复计费）"""

    def post(self, *a, **k):
        try:
            return super().post(*a, **k)
        except (httpx.RemoteProtocolError, httpx.ConnectError, httpx.WriteError):
            return super().post(*a, **k)


# 共用一个连接池：连续调用时不用每次重新握手（HTTPS 握手要几百毫秒）。
# 空闲 3 秒就不再复用：比常见服务器的空闲超时（5 秒起）短，避免拿到快被关掉的连接
HTTP = _Client(timeout=TIMEOUT, limits=httpx.Limits(max_keepalive_connections=4, keepalive_expiry=3))


# ---- Google Gemini：走它的 OpenAI 兼容接口（听录音和文字都支持），所以和 OpenAI 共用一套代码 ----
GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta/openai"
GEMINI_MODEL = "gemini-3.8-flash"        # 稳定版，能直接听音频（2026-11 官方文档）
GEMINI_MAX_AUDIO_MIN = 6                 # 一次请求最大 20MB：16kHz WAV 转 base64 后约 7 分钟，留点余量


def is_gemini(base: str) -> bool:
    return "generativelanguage.googleapis.com" in (base or "")


def vendor_name(base: str) -> str:
    return "Google" if is_gemini(base) else "OpenAI" if "api.openai.com" in (base or "") else "AI 接口"


def gemini_model(model: str) -> str:
    """换成 Google 时，原来填的 gpt-audio 之类的模型名不能用：不是 gemini 开头的就用默认模型"""
    model = (model or "").strip()
    return model if model.lower().startswith(("gemini", "models/gemini")) else GEMINI_MODEL


_proxied: dict[str, httpx.Client] = {}


def client_for(base: str) -> httpx.Client:
    """Google 的接口在国内直连不通。httpx 只认代理环境变量，不认系统代理设置（Clash 等软件设的就是这个），
    所以连 Google 时如果没设环境变量，就用系统代理（Windows 注册表 / Mac 系统设置）。其他接口照旧"""
    if not is_gemini(base) or any(os.environ.get(k) for k in
                                  ("HTTPS_PROXY", "https_proxy", "ALL_PROXY", "all_proxy")):
        return HTTP
    import urllib.request
    sys_proxies = urllib.request.getproxies()
    p = sys_proxies.get("https") or sys_proxies.get("http") or ""
    if not p.startswith(("http://", "https://")):      # 没有系统代理，或是 SOCKS（httpx 默认不支持）
        return HTTP
    if p not in _proxied:
        _proxied[p] = _Client(timeout=TIMEOUT, proxy=p,
                              limits=httpx.Limits(max_keepalive_connections=4, keepalive_expiry=3))
    return _proxied[p]


def _raise(r: httpx.Response, what: str):
    if r.status_code >= 300:
        raise RuntimeError(f"{what}失败 HTTP {r.status_code}: {r.text[:300]}")


def text_cfg(cfg: dict) -> dict:
    """文字 AI 的实际配置。选了 Google：换成它的兼容接口（Key 没单独填就用听录音那里的 Google Key）。
    没配置（没填模型名，或没填 Key 且不是本机模型）时，借用“AI 听录音”的接口"""
    if cfg.get("llm_provider") == "google":
        key = (cfg.get("llm_api_key") or cfg.get("google_api_key") or "").strip()
        if key:
            return {**cfg, "llm_provider": "openai", "llm_base_url": GEMINI_BASE, "llm_api_key": key,
                    "llm_model": gemini_model(cfg.get("llm_model"))}
        cfg = {**cfg, "llm_model": ""}            # 没有 Google Key：借用听录音的接口
    base = cfg.get("llm_base_url") or ""
    local = "127.0.0.1" in base or "localhost" in base
    if cfg.get("llm_model") and (cfg.get("llm_api_key") or local):
        return cfg
    from .listen import audio_endpoint
    a_base, a_key, a_model = audio_endpoint(cfg)
    if not a_key:
        return cfg
    return {**cfg, "llm_provider": "openai", "llm_base_url": a_base, "llm_api_key": a_key,
            "llm_model": a_model}


def chat(cfg: dict, system: str, user: str, max_tokens: int = 4000) -> str:
    cfg = text_cfg(cfg)
    base = (cfg.get("llm_base_url") or "").rstrip("/")
    if cfg.get("llm_provider") == "anthropic":
        r = HTTP.post(f"{base}/v1/messages",
                       headers={"x-api-key": cfg["llm_api_key"], "anthropic-version": "2023-06-01",
                                "content-type": "application/json"},
                       json={"model": cfg["llm_model"], "max_tokens": max_tokens, "system": system,
                             "messages": [{"role": "user", "content": user}]})
        _raise(r, "Claude 调用")
        usage.record(cfg["llm_model"], r.json().get("usage"), "text")
        return "".join(b.get("text", "") for b in r.json().get("content", [])
                       if b.get("type") == "text").strip()

    headers = {"content-type": "application/json"}
    if cfg.get("llm_api_key"):
        headers["Authorization"] = f"Bearer {cfg['llm_api_key']}"
    msgs = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    url = f"{base}/chat/completions"
    body = {"model": cfg["llm_model"], "messages": msgs, "temperature": 0.9, "max_tokens": max_tokens}
    if is_gemini(base):
        # Gemini 3 关不掉“思考”，思考也占输出额度：调到最省，额度放宽，免得复盘被截断
        body.update(reasoning_effort="low", max_tokens=max(max_tokens, 16000))
    client = client_for(base)
    r = client.post(url, headers=headers, json=body)
    if r.status_code == 400:  # 部分推理模型不收 temperature / max_tokens
        r = client.post(url, headers=headers, json={"model": cfg["llm_model"], "messages": msgs})
    _raise(r, f"{vendor_name(base)} 调用" if is_gemini(base) else "AI 调用")
    usage.record(cfg["llm_model"], r.json().get("usage"), "text")
    return (r.json()["choices"][0]["message"]["content"] or "").strip()


REPAIR_SYSTEM = "把下面这段内容整理成一个合法的 JSON 对象并原样输出，不要改写内容、不要加任何解释。"


def repair_json(cfg: dict, text: str) -> Optional[dict]:
    """模型输出的 JSON 坏了（被截断、多了文字）：交给文字 AI 修一下。
    比把整段录音重新发一遍便宜得多（只花几百个文字 token）。"""
    if not (text or "").strip():
        return None
    try:
        return parse_json(chat(cfg, REPAIR_SYSTEM, text[:20000], max_tokens=8000))
    except Exception:
        return None


def parse_json(text: str) -> Optional[dict]:
    """从模型输出里抠出 JSON（兼容 ```json 包裹、前后有废话、推理模型的 <think>）"""
    t = re.sub(r"<think>.*?</think>", "", text or "", flags=re.S)
    a, b = t.find("{"), t.rfind("}")
    if a < 0 or b <= a:
        return None
    try:
        return json.loads(t[a:b + 1])
    except json.JSONDecodeError:
        return None
