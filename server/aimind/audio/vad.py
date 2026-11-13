"""切句：一台设备的 PCM 流（16kHz 单声道）→ 一句一句的 Utterance。

用 30ms 一帧算音量，自适应噪声门限判断“有人在说话”；说话开始到停顿 0.8 秒为一句（最长 25 秒）。
每台设备一个 Segmenter，自带“录音时钟”（clock）：知道每个采样是什么时候录的，
所以手机断网后补传、或几台设备同时录，时间都不会乱。
"""
from __future__ import annotations

import collections
import io
import math
import wave
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Optional

import numpy as np

SR = 16000
FRAME = 480                      # 30ms
FRAME_SEC = FRAME / SR
END_SILENCE_SEC = 0.8
MAX_UTT_SEC = 25


@dataclass
class Utterance:
    device: str
    t0: datetime
    t1: datetime
    pcm: np.ndarray    # int16
    file: str = ""     # 这句话在哪个录音文件里（做识别测试时回放用）；"" = 没保存录音
    off: int = -1      # 在那个文件里的起始采样位置


class Segmenter:
    def __init__(self, device: str, cfg: dict, on_utterance: Callable[[Utterance], None],
                 wav=None, on_level: Optional[Callable[[float], None]] = None):
        self.device = device
        self.cfg = cfg
        self.on_utterance = on_utterance
        self.wav = wav                     # WavStore 或 None
        self.on_level = on_level
        self.clock: Optional[datetime] = None   # 下一个采样的录音时间
        self.last_voice: Optional[datetime] = None
        self.noise_db = -60.0
        self.level_db = -100.0
        self._leftover = np.zeros(0, dtype=np.int16)
        self._preroll: collections.deque = collections.deque(maxlen=10)
        self._in_utt = False
        self._buf: list[np.ndarray] = []
        self._utt_t0: Optional[datetime] = None
        self._utt_pos = ("", -1)
        self._silence = self._voiced = self._run = self._tick = 0

    # ---------- 输入 ----------
    def feed(self, pcm: np.ndarray, start: Optional[datetime] = None):
        """喂一段音频。start = 这段音频第一个采样的录音时间；None = 紧接上一段"""
        if start is not None:
            if self.clock is None:
                self.clock = start
            else:
                gap = (start - self.clock).total_seconds()
                if gap > 0.25:
                    self.skip(gap)           # 中间有一段没有音频（静音没上传 / 断线）
                elif gap < -1.0:             # 时间倒退（设备时钟被改过）：从新时间重新开始
                    self.flush()
                    self.clock = start
        elif self.clock is None:
            self.clock = datetime.now() - timedelta(seconds=len(pcm) / SR)
        pcm = pcm.astype(np.int16, copy=False)
        data = np.concatenate([self._leftover, pcm]) if self._leftover.size else pcm
        n = len(data) // FRAME * FRAME
        self._leftover = data[n:]
        for i in range(0, n, FRAME):
            self._frame(data[i:i + FRAME])

    def skip(self, seconds: float):
        """时间往前跳（这段没有声音，也不写进录音文件）"""
        if seconds <= 0 or self.clock is None:
            return
        self.flush()
        self._leftover = np.zeros(0, dtype=np.int16)
        self._preroll.clear()
        self._run = 0
        self.clock += timedelta(seconds=seconds)

    def idle_seconds(self) -> float:
        """距离最后一次有声音过了多少秒（按录音时间）"""
        if self.clock is None:
            return 0.0
        return (self.clock - (self.last_voice or self.clock)).total_seconds()

    # ---------- 每一帧 ----------
    def _frame(self, f: np.ndarray):
        if self.wav is not None:
            self.wav.write(f)
        t = self.clock
        self.clock = t + timedelta(seconds=FRAME_SEC)

        rms = math.sqrt(float(np.mean(f.astype(np.float32) ** 2)) + 1e-9)
        db = 20 * math.log10(rms / 32768 + 1e-9)
        self.level_db = db
        if db < self.noise_db:                       # 自适应噪声底：快降慢升
            self.noise_db = 0.8 * self.noise_db + 0.2 * db
        else:
            self.noise_db += 0.002 * (db - self.noise_db)
        thr = max(float(self.cfg.get("vad_min_db", -50)),
                  self.noise_db + float(self.cfg.get("vad_margin_db", 10)))
        speech = db > thr
        if speech:
            self.last_voice = self.clock
        self._tick += 1
        if self.on_level and self._tick % 6 == 0:
            self.on_level(db)

        if not self._in_utt:
            self._run = self._run + 1 if speech else 0
            self._preroll.append(f)
            if self._run >= 3:                       # 连续 90ms 有声才算开口
                self._in_utt = True
                self._buf = list(self._preroll)
                self._utt_t0 = self.clock - timedelta(seconds=len(self._buf) * FRAME_SEC)
                self._utt_pos = self.wav.position(len(self._buf) * FRAME) if self.wav else ("", -1)
                self._silence, self._voiced = 0, self._run
                self._preroll.clear()
        else:
            self._buf.append(f)
            if speech:
                self._silence = 0
                self._voiced += 1
            else:
                self._silence += 1
            if (self._silence * FRAME_SEC >= END_SILENCE_SEC
                    or len(self._buf) * FRAME_SEC >= MAX_UTT_SEC):
                self.flush()

    def flush(self):
        """结束当前这一句（停止 / 跳过时间时也要调用）"""
        if not self._in_utt:
            return
        self._in_utt = False
        self._run = 0
        buf, self._buf = self._buf, []
        if self._voiced * FRAME_SEC < 0.4 or not buf:
            return
        pcm = np.concatenate(buf)
        t0 = self._utt_t0
        self.on_utterance(Utterance(self.device, t0, t0 + timedelta(seconds=len(pcm) / SR), pcm,
                                    *self._utt_pos))


# ---------------- WAV 工具 ----------------
def pcm_to_wav_bytes(pcm: np.ndarray) -> bytes:
    bio = io.BytesIO()
    with wave.open(bio, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.astype(np.int16).tobytes())
    return bio.getvalue()


def read_wav_16k(path: Path) -> np.ndarray:
    """读取任意采样率/声道的 16bit WAV，转成 16k 单声道"""
    with wave.open(str(path), "rb") as w:
        sr, ch, sw = w.getframerate(), w.getnchannels(), w.getsampwidth()
        raw = w.readframes(w.getnframes())
    if sw != 2:
        raise ValueError("只支持 16bit PCM WAV；MP3/M4A 请先用格式工厂等转成 WAV")
    a = np.frombuffer(raw, dtype=np.int16).astype(np.float32)
    if ch > 1:
        a = a.reshape(-1, ch).mean(axis=1)
    if sr != SR:
        n = int(len(a) * SR / sr)
        a = np.interp(np.linspace(0, len(a) - 1, n), np.arange(len(a)), a)
    return np.clip(a, -32768, 32767).astype(np.int16)
