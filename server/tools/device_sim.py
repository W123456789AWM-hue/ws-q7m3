"""模拟一台录音设备（手机 App 的上传协议）：合成“说话 / 停顿”的音频，切片上传。

    python -m tools.device_sim --server http://127.0.0.1:8765 --device kitchen --name 厨房手机

测试里直接用 DeviceSim(post=...)，post 可以是 httpx.post 或 TestClient.post。
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta

import numpy as np

SR = 16000


def synth(pattern: list[tuple[float, bool]], seed: int = 0) -> np.ndarray:
    """pattern = [(秒数, 是否说话)]。说话 = 一段起伏的响声，停顿 = 很小的底噪"""
    rng = np.random.default_rng(seed)
    out = []
    for sec, voiced in pattern:
        n = int(sec * SR)
        if voiced:
            t = np.arange(n) / SR
            env = 0.6 + 0.4 * np.sin(2 * np.pi * 3 * t)          # 像音节一样起伏
            x = rng.normal(0, 3000, n) * env + 2000 * np.sin(2 * np.pi * 220 * t)
        else:
            x = rng.normal(0, 20, n)
        out.append(x)
    return np.clip(np.concatenate(out), -32768, 32767).astype(np.int16)


def adpcm_encode(pcm: np.ndarray) -> bytes:
    """和 App 一样的 IMA ADPCM 编码（服务器 aimind.audio.adpcm.decode 的逆过程）"""
    from aimind.audio.adpcm import IDX, STEP
    pred, idx = int(pcm[0]) if len(pcm) else 0, 0
    out = bytearray(int(pred).to_bytes(2, "little", signed=True) + bytes([idx, 0]))
    nib = []
    for s in pcm:
        step = STEP[idx]
        diff = int(s) - pred
        code = 8 if diff < 0 else 0
        diff = abs(diff)
        d = step >> 3
        if diff >= step:
            code |= 4; diff -= step; d += step
        if diff >= step >> 1:
            code |= 2; diff -= step >> 1; d += step >> 1
        if diff >= step >> 2:
            code |= 1; d += step >> 2
        pred = max(-32768, min(32767, pred - d if code & 8 else pred + d))
        idx = max(0, min(88, idx + IDX[code & 7]))
        nib.append(code)
    if len(nib) % 2:
        nib.append(0)
    out += bytes(nib[i] | (nib[i + 1] << 4) for i in range(0, len(nib), 2))
    return bytes(out)


class DeviceSim:
    def __init__(self, post, device: str, name: str, stream: str = "s1", chunk_sec: float = 10,
                 adpcm: bool = False, headers: dict | None = None, base: str = ""):
        self.post, self.base, self.headers = post, base, headers or {}
        self.device, self.name, self.stream = device, name, stream
        self.chunk, self.adpcm, self.seq = int(chunk_sec * SR), adpcm, 0

    def _send(self, path: str, params: dict, body: bytes = b""):
        r = self.post(self.base + path, params={**params, "device": self.device, "name": self.name},
                      content=body, headers=self.headers)
        assert r.status_code == 200, r.text
        return r.json()

    def upload(self, pcm: np.ndarray, start: datetime):
        """切成 10 秒一片上传；几乎没声音的片只传“静音”标记"""
        for i in range(0, len(pcm), self.chunk):
            a = pcm[i:i + self.chunk]
            p = {"stream": self.stream, "seq": self.seq, "dur": len(a) / SR,
                 "start": (start + timedelta(seconds=i / SR)).isoformat(timespec="milliseconds")}
            if float(np.sqrt(np.mean(a.astype(np.float32) ** 2))) < 100:
                self._send("/api/phone/chunk", {**p, "silent": 1})
            elif self.adpcm:
                self._send("/api/phone/chunk", {**p, "enc": "adpcm"}, adpcm_encode(a))
            else:
                self._send("/api/phone/chunk", p, a.tobytes())
            self.seq += 1

    def stop(self):
        out = self._send("/api/phone/stop", {"stream": self.stream, "seq": self.seq})
        self.seq += 1
        return out


if __name__ == "__main__":
    import httpx
    ap = argparse.ArgumentParser()
    ap.add_argument("--server", default="http://127.0.0.1:8765")
    ap.add_argument("--token", default="")
    ap.add_argument("--device", default="sim")
    ap.add_argument("--name", default="模拟设备")
    ap.add_argument("--adpcm", action="store_true")
    a = ap.parse_args()
    sim = DeviceSim(httpx.post, a.device, a.name, adpcm=a.adpcm, base=a.server,
                    headers={"X-Token": a.token} if a.token else {})
    pcm = synth([(1, False), (4, True), (2, False), (5, True), (20, False)] * 2)
    sim.upload(pcm, datetime.now() - timedelta(seconds=len(pcm) / SR))
    print(sim.stop())
