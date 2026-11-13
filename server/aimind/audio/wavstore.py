"""完整录音：每台设备、每 30 分钟一个 WAV 文件（audio_<设备>_001.wav …）"""
from __future__ import annotations

import wave
from pathlib import Path
from typing import Optional

import numpy as np

from .vad import SR

PART_SEC = 30 * 60


class WavStore:
    def __init__(self, folder: Path, device: str, part_sec: int = PART_SEC):
        self.folder = folder
        self.device = device
        self.part_sec = part_sec
        self._w: Optional[wave.Wave_write] = None
        self._name = ""
        self._part = 0
        self._samples = 0

    @property
    def current(self) -> str:
        """正在写的文件名（还不能同步到 NAS）"""
        return self._name if self._w else ""

    def position(self, back: int = 0) -> tuple[str, int]:
        """当前写到的位置（往回退 back 个采样），用来记下一句话在哪个文件的哪里"""
        if self._w is None:
            self._open()
        return self._name, max(0, self._samples - back)

    def write(self, f: np.ndarray):
        if self._w is None or self._samples >= self.part_sec * SR:
            self._open()
        self._w.writeframes(f.astype(np.int16).tobytes())
        self._samples += len(f)

    def _open(self):
        self.close()
        self._part += 1
        self._samples = 0
        self._name = f"audio_{self.device}_{self._part:03d}.wav"
        self._w = wave.open(str(self.folder / self._name), "wb")
        self._w.setnchannels(1)
        self._w.setsampwidth(2)
        self._w.setframerate(SR)

    def close(self):
        if self._w is not None:
            try:
                self._w.close()
            except Exception:
                pass
            self._w = None
