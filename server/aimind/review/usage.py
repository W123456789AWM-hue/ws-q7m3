"""AI 用量统计：每次调用 AI 后记下 token 数，按天、按模型累计，存在 data/usage.json。

界面上显示“今天用了多少”，方便判断哪些设置最费 token。只记数字，不记内容。
"""
from __future__ import annotations

import json
import threading
from datetime import datetime

from ..config import DATA_DIR

FILE = DATA_DIR / "usage.json"
_lock = threading.Lock()
KEEP_DAYS = 120


def _load() -> dict:
    try:
        return json.loads(FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _num(x) -> int:
    try:
        return int(x or 0)
    except (TypeError, ValueError):
        return 0


def record(model: str, usage: dict | None, kind: str, audio_sec: float = 0.0, saved_sec: float = 0.0) -> None:
    """usage：接口返回的 usage 字段（OpenAI 或 Claude 格式都认）。kind：audio（听录音）/ text（文字）"""
    u = usage or {}
    details = u.get("prompt_tokens_details") or {}
    inp = _num(u.get("prompt_tokens")) or (_num(u.get("input_tokens")) + _num(u.get("cache_read_input_tokens"))
                                           + _num(u.get("cache_creation_input_tokens")))
    out = _num(u.get("completion_tokens")) or _num(u.get("output_tokens"))
    cached = _num(details.get("cached_tokens")) or _num(u.get("cache_read_input_tokens"))
    audio_tok = _num(details.get("audio_tokens"))
    day = datetime.now().strftime("%Y-%m-%d")
    with _lock:
        data = _load()
        m = data.setdefault(day, {}).setdefault(model or "?", {
            "kind": kind, "calls": 0, "input": 0, "output": 0, "cached": 0, "audio_tokens": 0,
            "audio_sec": 0.0, "saved_sec": 0.0})
        m["calls"] += 1
        m["input"] += inp
        m["output"] += out
        m["cached"] += cached
        m["audio_tokens"] += audio_tok
        m["audio_sec"] = round(m.get("audio_sec", 0) + audio_sec, 1)
        m["saved_sec"] = round(m.get("saved_sec", 0) + saved_sec, 1)
        for old in sorted(data)[:-KEEP_DAYS]:
            data.pop(old, None)
        try:
            FILE.parent.mkdir(parents=True, exist_ok=True)
            tmp = FILE.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            tmp.replace(FILE)
        except OSError:
            pass


def day_summary(day: str | None = None) -> dict:
    day = day or datetime.now().strftime("%Y-%m-%d")
    with _lock:
        models = _load().get(day, {})
    tot = {k: 0 for k in ("calls", "input", "output", "cached", "audio_tokens")}
    tot.update(audio_sec=0.0, saved_sec=0.0)
    for m in models.values():
        for k in tot:
            tot[k] += m.get(k, 0)
    tot["audio_sec"] = round(tot["audio_sec"], 1)
    tot["saved_sec"] = round(tot["saved_sec"], 1)
    return {"date": day, "total": tot, "models": models}
