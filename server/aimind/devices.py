"""录音设备（手机、平板、别的电脑）上传的录音：先落盘，再按录音时间喂给引擎。

    POST /api/phone/chunk ──accept()──► data/inbox/<设备>/<stream>/<seq>.json(+.pcm) ──► 回复“收到”
    后台线程：几台设备的待处理片段里，挑录音时间最早的一片 ──► engine.feed / skip / device_stop

落盘后才回复设备，所以电脑重启也不会丢。设备注册表 data/devices.json 记着每台设备的名字和最近在线时间。
旧版 App 不带 device 参数，统一当作设备 "phone"（名字“手机”）。
"""
from __future__ import annotations

import json
import threading
import time
from datetime import datetime
from pathlib import Path

import numpy as np

from . import config as config_mod
from .audio import SR
from .audio.adpcm import decode
from .fsutil import write_atomic

INBOX = config_mod.DATA_DIR / "inbox"
REGISTRY = config_mod.DATA_DIR / "devices.json"
DEFAULT_DEVICE, DEFAULT_NAME = "phone", "手机"
MAX_PENDING_UTTS = 20     # 引擎积压太多句子时先别喂，免得内存涨


def safe_id(name: str) -> str:
    return "".join(c for c in (name or "") if c.isalnum() or c in "_-")[:40] or DEFAULT_DEVICE


class DeviceIngest:
    def __init__(self, engine, emit):
        self.engine, self.emit = engine, emit
        self.lock = threading.Lock()
        self.dir_lock = threading.Lock()     # inbox 文件夹：接收时建、处理完删，两边要互斥
        self.reg: dict[str, dict] = {}
        try:
            self.reg = json.loads(REGISTRY.read_text(encoding="utf-8"))
        except Exception:
            pass
        for dev, d in self.reg.items():
            engine.set_name(dev, d.get("name") or dev)
        INBOX.mkdir(parents=True, exist_ok=True)
        threading.Thread(target=self._loop, daemon=True).start()

    # ---------------- 接收（HTTP 线程调用）----------------
    def accept(self, device: str, name: str, stream: str, seq: int, start: str, dur: float,
               silent: bool, data: bytes, kind: str = "chunk", enc: str = "pcm") -> dict:
        dev = self._seen(device, name)
        if kind == "chunk" and not silent and enc == "adpcm":   # 移动网络下压缩上传的，先还原
            data = decode(data, int(round(dur * SR))).tobytes()
        if kind == "stop":       # 停止标记没有录音时间，按收到的时间排
            start = datetime.now().isoformat(timespec="milliseconds")
        d = INBOX / dev / safe_id(stream)
        meta = d / f"{seq:08d}.json"
        # 和后台“删掉空文件夹”互斥：否则可能刚建好文件夹就被删了，写文件时报 FileNotFoundError
        with self.dir_lock:
            d.mkdir(parents=True, exist_ok=True)
            if not meta.exists():   # 重复上传（设备没收到回复又传了一次）直接确认
                if kind == "chunk" and not silent:
                    (d / f"{seq:08d}.pcm").write_bytes(data)
                write_atomic(meta, json.dumps({"kind": kind, "start": start, "dur": dur, "silent": silent}))
        return {"ok": True, "seq": seq, "device": dev}

    def _seen(self, device: str, name: str) -> str:
        dev = safe_id(device or DEFAULT_DEVICE)
        name = (name or "").strip()[:30]
        with self.lock:
            d = self.reg.setdefault(dev, {"name": name or (DEFAULT_NAME if dev == DEFAULT_DEVICE else dev)})
            changed = bool(name and name != d.get("name"))
            if changed:
                d["name"] = name
            first = "last_seen" not in d
            d["last_seen"] = time.time()
            if changed or first or int(d["last_seen"]) % 60 == 0:
                self._save_reg()
        self.engine.set_name(dev, d["name"])
        return dev

    def _save_reg(self):
        write_atomic(REGISTRY, json.dumps(self.reg, ensure_ascii=False, indent=1))

    def rename(self, dev: str, name: str):
        with self.lock:
            self.reg.setdefault(dev, {})["name"] = name
            self._save_reg()
        self.engine.set_name(dev, name)

    def forget(self, dev: str):
        with self.lock:
            self.reg.pop(dev, None)
            self._save_reg()

    # ---------------- 状态 ----------------
    def status(self) -> dict:
        now = time.time()
        backlog: dict[str, int] = {}
        for p in INBOX.glob("*/*/*.json"):
            dev = p.parent.parent.name
            backlog[dev] = backlog.get(dev, 0) + 1
        with self.lock:
            devs = [{"id": k, "name": v.get("name", k), "online": now - v.get("last_seen", 0) < 60,
                     "last_seen": int(v.get("last_seen", 0)), "backlog": backlog.get(k, 0)}
                    for k, v in self.reg.items()]
        devs.sort(key=lambda x: -x["last_seen"])
        return {"backlog": sum(backlog.values()), "phone_online": any(d["online"] for d in devs),
                "phones": devs}

    # ---------------- 处理（后台线程）----------------
    def _next(self) -> Path | None:
        """每台设备最早的一片里，挑录音时间最早的"""
        best, best_t = None, None
        for dev_dir in INBOX.iterdir() if INBOX.exists() else []:
            metas = sorted(dev_dir.glob("*/*.json"), key=lambda p: (p.parent.name, p.name))
            if not metas:
                continue
            try:
                t = json.loads(metas[0].read_text(encoding="utf-8")).get("start") or ""
            except Exception:
                t = ""
            if best is None or t < best_t:
                best, best_t = metas[0], t
        return best

    def _loop(self):
        while True:
            try:
                if self.engine.pending() > MAX_PENDING_UTTS:
                    time.sleep(0.2)
                    continue
                meta = self._next()
                if meta is None:
                    time.sleep(0.5)
                    continue
                self._process(meta)
            except Exception as e:   # 不让线程死掉
                self.emit({"type": "error", "msg": f"处理设备录音出错：{e}"})
                time.sleep(2)

    def _process(self, meta: Path):
        dev = meta.parent.parent.name
        pcm_file = meta.with_suffix(".pcm")
        try:
            m = json.loads(meta.read_text(encoding="utf-8"))
            if m.get("kind") == "stop":
                self.engine.device_stop(dev)
                return
            start = datetime.fromisoformat(m["start"]).replace(tzinfo=None)
            if m.get("silent"):
                self.engine.skip(dev, start, float(m.get("dur") or 0))
            elif pcm_file.exists():
                self.engine.feed(dev, np.frombuffer(pcm_file.read_bytes(), dtype=np.int16), start)
        finally:
            pcm_file.unlink(missing_ok=True)
            meta.unlink(missing_ok=True)
            with self.dir_lock:                       # 和接收互斥（见 accept）
                for d in (meta.parent, meta.parent.parent):   # 目录空了就删
                    try:
                        d.rmdir()
                    except OSError:
                        pass
