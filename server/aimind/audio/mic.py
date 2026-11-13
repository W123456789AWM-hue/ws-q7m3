"""电脑自己的麦克风：把声卡的音频送进引擎（和手机传来的录音走同一条路）"""
from __future__ import annotations

import queue
import threading
from datetime import datetime, timedelta
from typing import Optional

import numpy as np

from .vad import FRAME, SR

MIC_DEVICE = "pc"


def list_mics() -> list[dict]:
    try:
        import sounddevice as sd
        return [{"index": i, "name": d["name"]} for i, d in enumerate(sd.query_devices())
                if d.get("max_input_channels", 0) > 0]
    except Exception as e:  # 没装声卡驱动 / 没有 PortAudio
        return [{"index": None, "name": f"无法读取设备：{e}"}]


class MicSource:
    def __init__(self, engine, device_index: Optional[int] = None):
        self.engine = engine
        self.device_index = device_index
        self.q: "queue.Queue[Optional[np.ndarray]]" = queue.Queue()
        self.stream = None
        self._thread: Optional[threading.Thread] = None

    @property
    def running(self) -> bool:
        return self.stream is not None

    def start(self):
        import sounddevice as sd  # 延迟导入：不用电脑麦克风时不需要声卡
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        self.stream = sd.InputStream(samplerate=SR, channels=1, dtype="int16", blocksize=FRAME * 4,
                                     device=self.device_index,
                                     callback=lambda d, *_: self.q.put(d[:, 0].copy()))
        self.stream.start()

    def _loop(self):
        first = True
        while True:
            pcm = self.q.get()
            if pcm is None:
                break
            start = datetime.now() - timedelta(seconds=len(pcm) / SR) if first else None
            first = False
            self.engine.feed(MIC_DEVICE, pcm, start)

    def stop(self):
        if self.stream is not None:
            try:
                self.stream.stop()
                self.stream.close()
            except Exception:
                pass
            self.stream = None
        self.q.put(None)
        if self._thread:
            self._thread.join(timeout=10)
