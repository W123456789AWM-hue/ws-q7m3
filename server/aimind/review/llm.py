"""文字 AI：OpenAI 兼容接口 / Claude。用于整场总复盘、日复盘、文字模式的复盘。"""
from __future__ import annotations

import json
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


def _raise(r: httpx.Response, what: str):
    if r.status_code >= 300:
        raise RuntimeError(f"{what}失败 HTTP {r.status_code}: {r.text[:300]}")


def text_cfg(cfg: dict) -> dict:
    """文字 AI 没配置（没填模型名，或没填 Key 且不是本机模型）时，借用“AI 听录音”的 OpenAI 接口"""
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
    r = HTTP.post(url, headers=headers, json={
        "model": cfg["llm_model"], "messages": msgs, "temperature": 0.9, "max_tokens": max_tokens})
    if r.status_code == 400:  # 部分推理模型不收 temperature / max_tokens
        r = HTTP.post(url, headers=headers, json={"model": cfg["llm_model"], "messages": msgs})
    _raise(r, "AI 调用")
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
