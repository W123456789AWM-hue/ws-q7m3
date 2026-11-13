"""识别引擎的统一入口：根据设置选 SenseVoice / Paraformer / Whisper（显卡）/ 在线接口"""
from __future__ import annotations

import re

import httpx
import numpy as np

from ..audio import pcm_to_wav_bytes
from ..review.llm import TIMEOUT

# Whisper 在噪音/静音上常见的“幻觉”字幕
HALLUCINATIONS = ["请不吝点赞", "订阅", "打赏支持", "字幕由", "字幕志愿者", "谢谢观看", "感谢观看",
                  "明镜与点点", "Amara.org", "优优独播剧场", "以下是普通话的", "请使用简体中文"]


def clean_transcript(text: str) -> str:
    t = (text or "").strip()
    stripped = t
    for h in HALLUCINATIONS:
        stripped = stripped.replace(h, "")
    return t if len(re.sub(r"[\s\W_]", "", stripped)) >= 2 else ""


def engine_key(cfg: dict) -> tuple:
    """这几项变了才需要重新加载模型"""
    return (cfg.get("stt_provider"), cfg.get("stt_language"),
            cfg.get("local_whisper_model"), cfg.get("whisper_device"))


class Transcriber:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.engine = None
        self.kind = ""       # 实际在用的引擎（Whisper 不可用时会退回 sensevoice）
        self.warning = ""

    @property
    def provider(self) -> str:
        return self.cfg.get("stt_provider") or "sensevoice"

    def prepare(self, progress=lambda m: None):
        """下载/加载模型（耗时）"""
        from . import local
        p = self.provider
        if p == "sensevoice":
            self.engine = local.SenseVoice(self.cfg, progress)
        elif p == "paraformer":
            self.engine = local.Paraformer(self.cfg, progress)
        elif p == "whisper":
            try:
                self.engine = local.LocalWhisper(self.cfg, progress)
                self.kind = "whisper"
            except Exception as e:  # Whisper 用不了时先顶上 SenseVoice，保证照样有文字
                self.warning = f"Whisper 不可用，暂时改用 SenseVoice：{e}"
                progress("⚠ " + self.warning)
                self.engine = local.SenseVoice(self.cfg, lambda m: None)

    def transcribe(self, pcm: np.ndarray, prev_text: str = "") -> str:
        if self.provider == "api":
            return self._api(pcm, prev_text)
        if self.engine is None:
            self.prepare()
        if self.kind == "whisper":
            self.engine.cfg = self.cfg  # 常用词表改了立即生效
            return clean_transcript(self.engine.transcribe(pcm, prev_text))
        return clean_transcript(self.engine.transcribe(pcm))

    def _api(self, pcm: np.ndarray, prev_text: str) -> str:
        c = self.cfg
        data = {"model": c["stt_model"], "response_format": "json"}
        lang = (c.get("stt_language") or "").strip()
        if lang:
            data["language"] = lang
        hint = ("以下是普通话，使用简体中文和标点。" if lang == "zh" else "") + (prev_text or "")[-120:]
        if hint.strip():
            data["prompt"] = hint.strip()
        headers = {"Authorization": f"Bearer {c['stt_api_key']}"} if c.get("stt_api_key") else {}
        r = httpx.post(c["stt_base_url"].rstrip("/") + "/audio/transcriptions", headers=headers,
                       data=data, files={"file": ("speech.wav", pcm_to_wav_bytes(pcm), "audio/wav")},
                       timeout=TIMEOUT)
        if r.status_code >= 300:
            raise RuntimeError(f"语音转写失败 HTTP {r.status_code}: {r.text[:300]}")
        try:
            return clean_transcript(r.json().get("text", ""))
        except ValueError:
            return clean_transcript(r.text)
