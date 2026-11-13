"""AI 直接听录音做复盘（OpenAI gpt-audio 系列，Chat Completions 接口的 input_audio）

- 每个段落作为一段音频发过去，前面附一行【段落 #编号 · 时间 · 时长】，AI 返回听写 + 复盘
- 录音太长、一次发不完时：先分几次让 AI 听写并记下语气线索，再基于这些用文字做一次复盘
"""
from __future__ import annotations

import base64
import io
import wave
from pathlib import Path

import httpx
import numpy as np

from ..audio import SR
from . import prompts, usage
from .llm import HTTP, TIMEOUT, chat, parse_json, repair_json

LONG_TIMEOUT = httpx.Timeout(300.0, connect=15.0)


def audio_endpoint(cfg: dict) -> tuple[str, str, str]:
    """(接口地址, Key, 模型)。Key 没填时，如果文字 AI 也是 OpenAI，就借用它的 Key"""
    base = (cfg.get("audio_base_url") or "https://api.openai.com/v1").strip().rstrip("/")
    key = (cfg.get("audio_api_key") or "").strip()
    if not key and "api.openai.com" in (cfg.get("llm_base_url") or ""):
        key = (cfg.get("llm_api_key") or "").strip()
    return base, key, (cfg.get("audio_model") or "gpt-audio-1.5").strip()


def wav_b64(pcm: np.ndarray) -> str:
    bio = io.BytesIO()
    with wave.open(bio, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.astype(np.int16).tobytes())
    return base64.b64encode(bio.getvalue()).decode("ascii")


KEEP_EDGE_SEC = 0.25     # 每句话前后最多保留多少秒静音
GAP_SEC = 0.4            # 句与句之间留多少秒（保留“停顿”的感觉，AI 能听出犹豫）


def trim_silence(pcm: np.ndarray, keep: float = KEEP_EDGE_SEC) -> np.ndarray:
    """去掉一句话开头、结尾多余的静音（切句时会带上约 0.8 秒尾巴）。
    按这句话自己的音量判断：比最响的 20ms 低 35dB 以上算静音。句子中间的停顿不动。"""
    win = SR // 50
    n = len(pcm) // win
    if n < 5:
        return pcm
    frames = pcm[:n * win].astype(np.float32).reshape(n, win)
    db = 10 * np.log10((frames ** 2).mean(axis=1) + 1e-6)
    loud = np.where(db > db.max() - 35)[0]
    if not len(loud):
        return pcm
    k = int(keep * SR / win)
    a, b = max(0, loud[0] - k), min(n, loud[-1] + 1 + k)
    return pcm[a * win:(b * win if b < n else len(pcm))]


def load_group_pcm(session_dir: Path, clips: list[str], compress: bool = True) -> tuple[np.ndarray, float]:
    """一个段落的几句话拼起来。返回 (音频, 省掉的秒数)。
    compress=True：去掉每句前后多余的静音（AI 听录音按时长计费，静音也算钱），句间统一留 0.4 秒"""
    gap = np.zeros(int(SR * (GAP_SEC if compress else 0.3)), dtype=np.int16)
    out, raw = [], 0
    for c in clips:
        f = session_dir / "clips" / c
        if f.exists():
            pcm = np.frombuffer(f.read_bytes(), dtype=np.int16)
            raw += len(pcm)
            if compress:
                pcm = trim_silence(pcm)
            if out:
                out.append(gap)
            out.append(pcm)
    if not out:
        return np.zeros(0, dtype=np.int16), 0.0
    pcm = np.concatenate(out)
    raw += int(SR * 0.3) * (len(out) // 2)   # 和不压缩时（句间 0.3 秒）比
    return pcm, max(0.0, (raw - len(pcm)) / SR)


def _fmt_sec(sec: float) -> str:
    sec = int(round(sec))
    return f"{sec // 60}分{sec % 60:02d}秒" if sec >= 60 else f"{sec}秒"


def call_audio(cfg: dict, system: str, header: str, groups: list[dict],
               session_dir: Path, max_tokens: int = 12000) -> str:
    """groups: [{"pid", "clock", "clips": [...]}]，每组作为一段音频"""
    base, key, model = audio_endpoint(cfg)
    if not key:
        raise RuntimeError("还没填写 OpenAI 的 API Key（设置 → AI 听录音）")
    content: list[dict] = [{"type": "text", "text": header}]
    compress = bool(cfg.get("audio_trim_silence", True))
    sent = saved = 0.0
    for g in groups:
        pcm, cut = load_group_pcm(session_dir, g["clips"], compress)
        if len(pcm) < SR // 10:
            continue
        dev = f" · {g['device_name']}" if g.get("device_name") else ""
        content.append({"type": "text",
                        "text": f"【段落 #{g['pid']}{dev} · {g['clock']} · {_fmt_sec(len(pcm) / SR)}】"})
        content.append({"type": "input_audio", "input_audio": {"data": wav_b64(pcm), "format": "wav"}})
        sent += len(pcm) / SR
        saved += cut
    if len(content) == 1:
        raise RuntimeError("这段时间的录音片段找不到了（可能已被删除）")
    msgs = [{"role": "system", "content": system}, {"role": "user", "content": content}]
    headers = {"Authorization": f"Bearer {key}", "content-type": "application/json"}
    url = f"{base}/chat/completions"
    body = {"model": model, "modalities": ["text"], "messages": msgs,
            "temperature": 0.8, "max_tokens": max_tokens}
    r = HTTP.post(url, headers=headers, json=body, timeout=LONG_TIMEOUT)
    if r.status_code == 400 and "audio" not in r.text.lower():
        # 有的模型不收 temperature / max_tokens，去掉再试
        body = {"model": model, "modalities": ["text"], "messages": msgs}
        r = HTTP.post(url, headers=headers, json=body, timeout=LONG_TIMEOUT)
    if r.status_code == 413:
        raise RuntimeError("一次发送的录音太大，请在设置里把「每次最多发送多少分钟录音」调小")
    if r.status_code == 401:
        raise RuntimeError("OpenAI 的 API Key 不对或已失效")
    if r.status_code == 429:
        raise RuntimeError(f"OpenAI 额度不足或请求太频繁（HTTP 429）：{r.text[:200]}")
    if r.status_code >= 300:
        raise RuntimeError(f"HTTP {r.status_code}: {r.text[:300]}")
    j = r.json()
    usage.record(model, j.get("usage"), "audio", audio_sec=sent, saved_sec=saved)
    msg = j["choices"][0]["message"]
    content_out = msg.get("content")
    if isinstance(content_out, list):  # 少数兼容接口返回分段内容
        content_out = "".join(p.get("text", "") for p in content_out if isinstance(p, dict))
    return (content_out or "").strip()


def split_groups(groups: list[dict], max_sec: float) -> list[list[dict]]:
    """把段落分成几批，每批录音总长不超过 max_sec；单个段落太长也会被拆开（编号不变）"""
    batches, cur, cur_sec = [], [], 0.0
    for g in groups:
        pieces, piece, piece_sec = [], [], 0.0
        for c, sec in zip(g["clips"], g["secs"]):
            if piece and piece_sec + sec > max_sec:
                pieces.append((piece, piece_sec))
                piece, piece_sec = [], 0.0
            piece.append(c)
            piece_sec += sec
        if piece:
            pieces.append((piece, piece_sec))
        for clips, sec in pieces:
            if cur and cur_sec + sec > max_sec:
                batches.append(cur)
                cur, cur_sec = [], 0.0
            cur.append({**g, "clips": clips, "sec": sec})
            cur_sec += sec
    if cur:
        batches.append(cur)
    return batches


def _transcripts(data: dict | None) -> dict[int, str]:
    out: dict[int, str] = {}
    for t in (data or {}).get("transcripts") or []:
        try:
            pid = int(t.get("id"))
        except (TypeError, ValueError, AttributeError):
            continue
        txt = str(t.get("text") or "").strip()
        if txt:
            out[pid] = (out.get(pid, "") + txt)
    return out


def audio_review(cfg: dict, groups: list[dict], session_dir: Path, span: str,
                 prev: list[dict], progress=lambda m: None) -> tuple[dict, dict[int, str]]:
    """返回 (复盘结果, {段落编号: 听写文字})"""
    max_sec = max(60.0, float(cfg.get("audio_max_min") or 8) * 60)
    header = prompts.audio_header(span, prev, cfg.get("about_me", ""),
                                  cfg.get("extra_instructions", ""), cfg.get("glossary", ""))
    batches = split_groups(groups, max_sec)

    if len(batches) == 1:
        out = call_audio(cfg, prompts.AUDIO_REVIEW_SYSTEM, header, batches[0], session_dir)
        # JSON 坏了不重新发录音（那样整段录音要再付一次钱），交给文字 AI 修
        data = parse_json(out) or repair_json(cfg, out) or {"title": "复盘", "summary": out}
        return data, _transcripts(data)

    # 录音太长：分批听写，再用文字复盘
    texts: dict[int, str] = {}
    cues: list[str] = []
    for i, b in enumerate(batches, 1):
        progress(f"录音较长，分 {len(batches)} 次听：第 {i} 次")
        out = call_audio(cfg, prompts.AUDIO_LISTEN_SYSTEM, header, b, session_dir)
        d = parse_json(out) or repair_json(cfg, out) or {}
        for pid, t in _transcripts(d).items():
            texts[pid] = texts.get(pid, "") + t
        cues += [str(c) for c in (d.get("voice_cues") or [])]
    clock = {g["pid"]: g["clock"] for g in groups}
    body = "\n\n".join(f"[{clock.get(pid, '')}] {t}" for pid, t in sorted(texts.items()))
    if cues:
        body += "\n\n【从语气、情绪、环境里听出来的信息】\n" + "\n".join(f"- {c}" for c in cues)
    user = prompts.review_user(body, span, prev, cfg.get("about_me", ""),
                               cfg.get("extra_instructions", ""), cfg.get("glossary", ""))
    out = chat(cfg, prompts.REVIEW_SYSTEM, user)
    data = parse_json(out) or {"title": "复盘", "summary": out}
    if cues and not data.get("voice_cues"):
        data["voice_cues"] = cues[:3]
    return data, texts


def test_audio(cfg: dict) -> str:
    """设置页的测试按钮：发 1.5 秒提示音，确认 Key、模型都能用"""
    base, key, model = audio_endpoint(cfg)
    if not key:
        raise RuntimeError("还没填写 OpenAI 的 API Key")
    t = np.arange(int(SR * 1.5)) / SR
    pcm = (np.sin(2 * np.pi * 440 * t) * 8000).astype(np.int16)
    r = HTTP.post(f"{base}/chat/completions", timeout=TIMEOUT,
                   headers={"Authorization": f"Bearer {key}", "content-type": "application/json"},
                   json={"model": model, "modalities": ["text"], "messages": [{"role": "user", "content": [
                       {"type": "text", "text": "这是一段测试音频。请用一句中文描述你听到了什么。"},
                       {"type": "input_audio", "input_audio": {"data": wav_b64(pcm), "format": "wav"}}]}]})
    if r.status_code >= 300:
        raise RuntimeError(f"HTTP {r.status_code}: {r.text[:300]}")
    return f"AI 能听到录音（{model}）：{(r.json()['choices'][0]['message'].get('content') or '').strip()[:80]}"
