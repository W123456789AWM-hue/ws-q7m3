"""会话引擎：把所有设备的录音变成复盘。

    设备音频 ──feed()──► 每台设备一个 Segmenter（切句，带录音时钟）──► 句子队列
    句子队列 ──_utt_worker──► AI 听录音模式：存成语音片段 / 文字模式：本地识别 ──► 按设备分段
    监控线程（每秒）：停顿结束段落、到点做周期复盘、所有设备都不录了就收尾
    复盘队列 ──_llm_worker──► AI 复盘 ──► 保存 + 同步 NAS + 推送给界面

几台设备同时录音时，它们的内容放在同一场会话里，按录音时间排好，一起交给 AI 复盘。
过了零点自动换成新的一场。
"""
from __future__ import annotations

import queue
import threading
import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

import numpy as np

from . import config as config_mod
from . import nas
from .audio import SR, Segmenter, Utterance, read_wav_16k
from .audio.mic import MIC_DEVICE, MicSource
from .audio.vad import looks_like_speech
from .audio.wavstore import WavStore
from .fsutil import append_jsonl
from .review import daily, prompts
from .review.listen import audio_review
from .review.llm import chat, parse_json, repair_json
from .session import Session, clock, with_pause
from .stt.transcriber import Transcriber, engine_key

IMPORT_DEVICE = "import"
LIVE_KEYS = ("review_input", "audio_vendor", "google_api_key", "audio_base_url", "audio_api_key", "audio_model",
             "audio_max_min",
             "realtime_min_sec", "review_min_sec", "realtime_min_chars", "review_min_chars",
             "review_mode", "review_interval_min", "pause_close_sec", "max_paragraph_sec",
             "about_me", "extra_instructions", "glossary", "llm_provider", "llm_base_url",
             "llm_api_key", "llm_model", "audio_trim_silence", "noise_filter", "session_review", "nas_dir",
             "phone_idle_stop_min", "vad_margin_db")


class Track:
    """一台设备在一场会话里的状态"""

    def __init__(self, dev: str, name: str, s: Session, engine: "Engine"):
        self.dev, self.name = dev, name
        self.wav = WavStore(s.dir, dev) if (engine.cfg.get("save_audio", True) or s.mode == "audio") else None
        self.seg = Segmenter(dev, engine.cfg, lambda u: engine._on_utt(s, self, u), self.wav,
                             on_level=engine._level if dev == MIC_DEVICE else None)
        self.last_data = time.time()      # 最后一次收到这台设备的数据（真实时间）
        self.stopped = False              # 设备说了“停止录音”
        self.current: Optional[dict] = None   # 正在进行的段落
        self.prev_text = ""


class Engine:
    def __init__(self, emit: Callable[[dict], None]):
        self.emit = emit
        self.lock = threading.RLock()        # 保护会话数据
        self.feed_lock = threading.RLock()   # 保护切句器；顺序永远是 feed_lock → lock
        self.cfg: dict = config_mod.load()
        self.s: Optional[Session] = None
        self.tracks: dict[str, Track] = {}
        self.names: dict[str, str] = {MIC_DEVICE: "这台电脑", IMPORT_DEVICE: "导入的文件"}
        self.mic: Optional[MicSource] = None
        self.utt_q: "queue.Queue[tuple]" = queue.Queue()
        self.llm_q: "queue.Queue[tuple]" = queue.Queue()
        self.transcriber: Optional[Transcriber] = None
        for f in (self._utt_worker, self._llm_worker, self._monitor):
            threading.Thread(target=f, daemon=True).start()
        daily.start_scheduler(emit)

    # ======================= 查询 =======================
    @property
    def audio_mode(self) -> bool:
        """True = AI 直接听录音；False = 先本地识别成文字"""
        return (self.cfg.get("review_input") or "audio") == "audio"

    @property
    def recording(self) -> bool:
        return self.s is not None and self.s.status == "recording"

    @property
    def mic_on(self) -> bool:
        return self.mic is not None and self.mic.running

    def pending(self) -> int:
        s = self.s
        return s.pending_utts if s else 0

    def state(self) -> dict:
        with self.lock:
            now = time.time()
            devs = [{"id": t.dev, "name": t.name, "stopped": t.stopped,
                     "idle_sec": int(now - t.last_data)} for t in self.tracks.values()]
            used = {t.dev for t in self.tracks.values()}
            used |= {p.get("device") for p in (self.s.paragraphs if self.s else [])}
            source = "phone" if used - {MIC_DEVICE} else "mic"    # 旧版手机 App 用这个字段
            return {"session": self.s.to_dict() if self.s else None, "recording": self.recording,
                    "mic_on": self.mic_on, "source": source, "devices": devs,
                    "next_review": self._next_review_info()}

    def set_name(self, dev: str, name: str):
        if name:
            self.names[dev] = name

    # ======================= 音频输入（任何线程都可以调用）=======================
    def feed(self, dev: str, pcm: np.ndarray, start: Optional[datetime] = None):
        """一台设备送来一段音频。start = 第一个采样的录音时间；None = 紧接上一段"""
        with self.feed_lock:
            tr = self.tracks.get(dev)
            t = start or (tr.seg.clock if tr and tr.seg.clock else None) or datetime.now()
            tr = self._track_for(dev, t, create=True)
            tr.last_data, tr.stopped = time.time(), False
            tr.seg.feed(pcm, start)

    def skip(self, dev: str, start: datetime, dur: float):
        """一台设备送来一段静音（只有时间，没有音频）。没在录的时候不会因此开新的一场"""
        with self.feed_lock:
            tr = self._track_for(dev, start, create=False)
            if tr is None:
                return
            tr.last_data, tr.stopped = time.time(), False
            tr.seg.feed(np.zeros(0, dtype=np.int16), start)
            tr.seg.skip(dur)

    def device_stop(self, dev: str):
        """一台设备停止录音。所有设备都停了，这一场就会收尾"""
        with self.feed_lock:
            tr = self.tracks.get(dev)
            if tr:
                tr.seg.flush()
                tr.stopped = True

    def _track_for(self, dev: str, t: datetime, create: bool) -> Optional[Track]:
        with self.lock:
            s = self.s
            if s is not None and s.status == "recording" and t.date() != s.started.date() and t > s.started:
                if not create:
                    return None
                self._detach_and_finish(s)        # 过了零点：这一场收尾，开新的一场
            if s is None or s.status != "recording":
                if not create:
                    return None
                self.cfg = config_mod.load()
                s = self.s = Session(started=t)
                s.mode = "audio" if self.audio_mode else "text"
                self.tracks = {}
                self.emit({"type": "state", **self.state()})
            tr = self.tracks.get(dev)
            if tr is None:
                tr = self.tracks[dev] = Track(dev, self.names.get(dev, dev), s, self)
            return tr

    def _level(self, db: float):
        self.emit({"type": "level", "db": round(db, 1)})

    # ======================= 控制 =======================
    def start_mic(self):
        if self.mic_on:
            raise RuntimeError("已经在用这台电脑录音了")
        self.cfg = config_mod.load()
        self.mic = MicSource(self, self.cfg.get("mic_device"))
        self.mic.start()
        self.emit({"type": "state", **self.state()})

    def stop_mic(self):
        if self.mic:
            self.mic.stop()
            self.mic = None
        self.device_stop(MIC_DEVICE)
        self.emit({"type": "state", **self.state()})

    def finish_now(self):
        """结束这一场（不管还有没有设备在录），马上做整场总复盘"""
        if self.mic_on:
            self.mic.stop()
            self.mic = None
        with self.lock:
            if not self.recording:
                raise RuntimeError("当前没有在录音")
            self._detach_and_finish(self.s)

    def import_file(self, path: Path):
        """导入一个 WAV 文件：当作一台设备，按录音时间快速喂进来"""
        def run():
            try:
                pcm, base = read_wav_16k(path), datetime.now()
                for i in range(0, len(pcm), SR):
                    from datetime import timedelta
                    self.feed(IMPORT_DEVICE, pcm[i:i + SR], base + timedelta(seconds=i / SR))
                    while self.pending() > 0:            # 等识别/存片段跟上，周期复盘的时间才准
                        time.sleep(0.02)
                self.device_stop(IMPORT_DEVICE)
            except Exception as e:
                self.emit({"type": "error", "msg": f"导入失败：{e}"})
        threading.Thread(target=run, daemon=True).start()

    def review_now(self):
        with self.lock:
            if not self.recording:
                raise RuntimeError("当前没有在录音")
            if not self._queue_review(self.s, "manual"):
                raise RuntimeError("上次复盘之后还没有新的内容")

    def retry_review(self, rid: int):
        with self.lock:
            self.cfg.update({k: v for k, v in config_mod.load().items()
                             if k not in ("save_audio", "mic_device")})   # 用最新设置（比如刚改的 Key）
            s = self.s
            for r in s.reviews if s else []:
                if r["id"] == rid and r["status"] == "error":
                    r["status"], r["error"] = "analyzing", ""
                    s.pending_reviews += 1
                    self.emit({"type": "review", "data": r})
                    self.llm_q.put((s, r))

    def analyze_text(self, text: str):
        """文字测试：把一段文字当作一次复盘的内容，直接交给 AI"""
        with self.lock:
            if self.recording:
                raise RuntimeError("录音中，请先结束这一场")
            self.cfg = config_mod.load()
            s = self.s = Session(title="文字测试")
            s.mode = "text"
            tr = Track("text", "文字", s, self)
            now = datetime.now()
            self._add_segment(s, tr, Utterance("text", now, now, np.zeros(0, np.int16)), text.strip())
            self._close_paragraph(s, tr, auto_review=False)
            r = self._make_review(s, "manual")
            s.status = "done"
            s.save()
        self.emit({"type": "state", **self.state()})
        threading.Thread(target=lambda: (self._analyze(s, r), self._sync(s, final=True)),
                         daemon=True).start()

    # ======================= 句子 → 段落 =======================
    def _on_utt(self, s: Session, tr: Track, u: Utterance):
        with self.lock:
            s.pending_utts += 1
        self.utt_q.put((s, tr, u))

    def _utt_worker(self):
        while True:
            s, tr, u = self.utt_q.get()
            try:
                if self.cfg.get("noise_filter", True) and not looks_like_speech(u.pcm):
                    with self.lock:
                        s.noise_skipped += 1
                    continue
                if s.mode == "audio":   # AI 听录音：只把这句话存成小片段，复盘时交给 AI
                    clips = s.dir / "clips"
                    clips.mkdir(exist_ok=True)
                    with self.lock:
                        name = f"{len(s.segments()):06d}.pcm"
                    (clips / name).write_bytes(u.pcm.astype(np.int16).tobytes())
                    with self.lock:
                        self._add_segment(s, tr, u, "", clip=name)
                else:
                    text = self._transcribe(u.pcm, tr.prev_text)
                    if text:
                        tr.prev_text = text
                        with self.lock:
                            self._add_segment(s, tr, u, text)
            except Exception as e:
                self.emit({"type": "error", "msg": f"处理一句话时出错（录音仍保留）：{e}"})
            finally:
                with self.lock:
                    s.pending_utts -= 1

    def _transcribe(self, pcm: np.ndarray, prev: str) -> str:
        t = self.transcriber
        if t is None or engine_key(t.cfg) != engine_key(self.cfg):
            t = self.transcriber = Transcriber(self.cfg)
            try:
                t.prepare(lambda m: self.emit({"type": "model", "msg": m}))
                if t.warning:
                    self.emit({"type": "error", "msg": t.warning})
            except Exception as e:
                self.transcriber = None
                raise RuntimeError(f"本地识别模型加载失败：{e}")
        t.cfg = self.cfg
        return t.transcribe(pcm, prev)

    def _add_segment(self, s: Session, tr: Track, u: Utterance, text: str, clip: str = ""):
        cur = tr.current
        if cur and cur["segments"] and \
                s.rel(u.t0) - cur["segments"][-1]["t1"] >= float(self.cfg.get("pause_close_sec") or 15):
            self._close_paragraph(s, tr)
            cur = None
        if cur is None:
            cur = tr.current = {"id": len(s.paragraphs) + 1, "device": tr.dev, "device_name": tr.name,
                                "start_t": s.rel(u.t0), "start_clock": clock(u.t0),
                                "segments": [], "text": "", "status": "live"}
            s.paragraphs.append(cur)
        text = with_pause(text) if text else ""
        seg = {"t0": s.rel(u.t0), "t1": s.rel(u.t1), "clock": clock(u.t0), "pid": cur["id"],
               "device": tr.dev, "text": text}
        if u.file:
            seg.update(file=u.file, off=u.off, n=len(u.pcm))
        if clip:
            seg.update(clip=clip, sec=round(len(u.pcm) / SR, 2))
        cur["segments"].append(seg)
        cur["text"] += text
        if text:
            append_jsonl(s.dir / "transcript.jsonl", [seg])
        self.emit({"type": "caption", "pid": cur["id"], "clock": seg["clock"], "text": text,
                   "sec": seg.get("sec"), "device_name": tr.name})
        if seg["t1"] - cur["start_t"] >= float(self.cfg.get("max_paragraph_sec") or 180):
            self._close_paragraph(s, tr)

    def _close_paragraph(self, s: Session, tr: Track, auto_review: bool = True):
        p, tr.current = tr.current, None
        if not p:
            return
        if not p["segments"]:
            s.paragraphs.remove(p)
            return
        p["status"] = "closed"
        self.emit({"type": "paragraph", "data": p})
        s.save()
        # 实时复盘：每说完一段就交给 AI（太短的先攒着）
        if auto_review and self.cfg.get("review_mode") == "realtime" and s.status != "done" \
                and self._amount(s) >= self._min_amount(s, "realtime"):
            self._queue_review(s, "realtime")

    # ======================= 复盘调度 =======================
    def _amount(self, s: Session) -> float:
        """还没复盘的内容量：听录音模式按语音秒数，文字模式按字数"""
        new = s.unreviewed()
        if s.mode == "audio":
            return round(sum(x.get("sec", 0) for x in new), 1)
        return sum(len(x["text"]) for x in new)

    def _min_amount(self, s: Session, kind: str) -> float:
        audio = s.mode == "audio"
        key, d = {("realtime", True): ("realtime_min_sec", 5), ("interval", True): ("review_min_sec", 30),
                  ("realtime", False): ("realtime_min_chars", 30),
                  ("interval", False): ("review_min_chars", 200)}[(kind, audio)]
        v = self.cfg.get(key)
        return float(d if v is None else v)

    def _frontier(self) -> Optional[datetime]:
        """所有设备里最新的录音时间"""
        clocks = [t.seg.clock for t in self.tracks.values() if t.seg.clock]
        return max(clocks) if clocks else None

    def _next_review_info(self) -> Optional[dict]:
        s = self.s
        if not s or s.status != "recording":
            return None
        unit = "秒语音" if s.mode == "audio" else "字"
        info = {"unit": unit, "new_chars": self._amount(s)}
        if self.cfg.get("review_mode") == "realtime":
            return {**info, "mode": "realtime", "seconds_left": None,
                    "min_chars": self._min_amount(s, "realtime")}
        frontier = self._frontier() or s.started
        interval = float(self.cfg.get("review_interval_min") or 30) * 60
        left = max(0, int(interval - (frontier - s.last_review).total_seconds()))
        return {**info, "mode": "interval", "seconds_left": left,
                "min_chars": self._min_amount(s, "interval")}

    def _render_span(self, s: Session, segs: list[dict]) -> str:
        multi = len({x.get("device") for x in segs}) > 1
        names = {p["id"]: p.get("device_name", "") for p in s.paragraphs}
        blocks: dict[int, list[str]] = {}
        for x in segs:
            if x["pid"] not in blocks:
                dev = f" {names.get(x['pid'], '')}" if multi else ""
                blocks[x["pid"]] = [f"[{x['clock']}{dev}] "]
            blocks[x["pid"]].append(x["text"])
        return "\n\n".join("".join(b) for b in blocks.values())

    def _make_review(self, s: Session, kind: str) -> Optional[dict]:
        new = s.unreviewed()
        if not new:
            return None
        rid = len(s.reviews) + 1
        r = {"id": rid, "kind": kind, "date": s.started.strftime("%Y-%m-%d"),
             "from_clock": new[0]["clock"], "to_clock": max(new, key=lambda x: x["t1"])["clock"],
             "chars": sum(len(x["text"]) for x in new), "text": self._render_span(s, new),
             "status": "analyzing", "analysis": None, "error": ""}
        if s.mode == "audio":
            # 每个段落一组录音片段，按开始时间排
            names = {p["id"]: p.get("device_name", "") for p in s.paragraphs}
            groups: dict[int, dict] = {}
            for x in new:
                if x.get("clip"):
                    g = groups.setdefault(x["pid"], {"pid": x["pid"], "device": x.get("device"),
                                                     "device_name": names.get(x["pid"], ""),
                                                     "clock": x["clock"], "clips": [], "secs": []})
                    g["clips"].append(x["clip"])
                    g["secs"].append(x.get("sec", 0))
            if groups:
                r.update(audio=list(groups.values()), text="",
                         sec=round(sum(sum(g["secs"]) for g in groups.values()), 1))
        for x in new:
            x["rv"] = rid
        s.last_review = self._frontier() or s.started
        s.reviews.append(r)
        return r

    def _queue_review(self, s: Session, kind: str) -> bool:
        r = self._make_review(s, kind)
        if not r:
            return False
        s.pending_reviews += 1
        s.save()
        self.emit({"type": "review", "data": r})
        self.llm_q.put((s, r))
        return True

    # ======================= AI 复盘 =======================
    def _llm_worker(self):
        while True:
            s, r = self.llm_q.get()
            try:
                self._analyze(s, r)
            except Exception:
                self.emit({"type": "error", "msg": traceback.format_exc()[-400:]})
            finally:
                with self.lock:
                    s.pending_reviews = max(0, s.pending_reviews - 1)

    def _analyze(self, s: Session, r: dict):
        with self.lock:
            prev = [x for x in s.reviews if x["id"] < r["id"] and x["status"] == "done"
                    and not (x["analysis"] or {}).get("trivial")][-2:]
        span = f"{r['date']} {r['from_clock']}–{r['to_clock']}"
        try:
            if r.get("audio"):
                data, texts = audio_review(self.cfg, r["audio"], s.dir, span, prev,
                                           progress=lambda m: self.emit({"type": "status", "msg": m}))
                data.pop("transcripts", None)
                with self.lock:
                    self._apply_transcripts(s, r, texts)
            else:
                user = prompts.review_user(r["text"], span, prev, self.cfg.get("about_me", ""),
                                           self.cfg.get("extra_instructions", ""), self.cfg.get("glossary", ""))
                out = chat(self.cfg, prompts.REVIEW_SYSTEM, user)
                data = parse_json(out) or repair_json(self.cfg, out) or {"title": "复盘", "summary": out}
            with self.lock:
                r["analysis"], r["status"] = data, "done"
        except Exception as e:
            with self.lock:
                r["status"] = "error"
                where = "「AI 听录音」" if r.get("audio") else "「AI 接口」"
                r["error"] = f"AI 复盘失败：{e}（检查设置里的{where}后点重试）"
        with self.lock:
            s.save()
            self.emit({"type": "review", "data": r})
        if r["status"] == "done":
            if r.get("audio") and s is self.s:
                self.emit({"type": "state", **self.state()})   # 段落里填上了听写文字
            threading.Thread(target=self._sync, args=(s,), daemon=True).start()

    def _apply_transcripts(self, s: Session, r: dict, texts: dict[int, str]):
        """把 AI 听写的文字填回段落；听完的语音片段删掉（完整录音在 audio_*.wav 里）"""
        paras = {p["id"]: p for p in s.paragraphs}
        blocks, lines = [], []
        for g in r["audio"]:
            t = texts.pop(g["pid"], "")
            if t:
                p = paras.get(g["pid"])
                if p is not None:
                    p["text"] = p["text"] + t
                dev = f" {g['device_name']}" if g.get("device_name") else ""
                blocks.append(f"[{g['clock']}{dev}] {t}")
                lines.append({"pid": g["pid"], "clock": g["clock"], "device": g.get("device"), "text": t})
            for c in g["clips"]:
                (s.dir / "clips" / c).unlink(missing_ok=True)
        r["text"] = "\n\n".join(blocks)
        r["chars"] = len(r["text"])
        # 听写记录只是附带的日志：Windows 上文件偶尔被杀毒软件 / 同步线程占着，等一等再写，实在不行也不让这次复盘失败
        append_jsonl(s.dir / "transcript.jsonl", lines)

    # ======================= 监控（每秒）=======================
    def _monitor(self):
        tick = 0
        while True:
            time.sleep(1)
            tick += 1
            try:
                self._check(tick)
            except Exception:
                self.emit({"type": "error", "msg": "监控出错：" + traceback.format_exc()[-300:]})

    def _check(self, tick: int):
        to_flush = []
        with self.lock:
            s = self.s
            if not s or s.status != "recording":
                return
            if tick % 5 == 0:   # 设置在录音中修改也生效
                new = config_mod.load()
                self.cfg.update({k: new.get(k) for k in LIVE_KEYS})
            now = time.time()
            pause = float(self.cfg.get("pause_close_sec") or 15)
            idle_q = s.pending_utts == 0
            for tr in self.tracks.values():
                wire_idle = now - tr.last_data
                if wire_idle > pause + 20:
                    to_flush.append(tr)   # 设备没再传数据（没电/断网）：把说到一半的那句结束掉
                if tr.current and tr.current["segments"] and idle_q and \
                        (tr.seg.idle_seconds() >= pause or wire_idle > pause + 20 or tr.stopped):
                    self._close_paragraph(s, tr)
            # 周期复盘（按录音时间算，补传的录音也准）
            frontier = self._frontier()
            if self.cfg.get("review_mode") != "realtime" and idle_q and frontier and \
                    (frontier - s.last_review).total_seconds() >= float(self.cfg.get("review_interval_min") or 30) * 60:
                if self._amount(s) >= self._min_amount(s, "interval"):
                    self._queue_review(s, "periodic")
                else:
                    s.last_review = frontier      # 内容太少：这一轮跳过
            # 所有设备都停了 / 很久没数据：这一场收尾
            idle_stop = float(self.cfg.get("phone_idle_stop_min") or 30) * 60
            active = [t for t in self.tracks.values() if not t.stopped and now - t.last_data < idle_stop]
            if self.tracks and not active and not self.mic_on and idle_q:
                self._detach_and_finish(s)
                return
            if tick % 5 == 0:
                self.emit({"type": "next_review", "data": self._next_review_info()})
        for tr in to_flush:
            with self.feed_lock:
                tr.seg.flush()

    # ======================= 收尾 =======================
    def _detach_and_finish(self, s: Session):
        """（持有 lock 时调用）把这一场和它的设备拿出来，在后台收尾；新的录音会开新的一场"""
        s.status = "finishing"
        tracks, self.tracks = self.tracks, {}
        self.emit({"type": "state", **self.state()})
        threading.Thread(target=self._finish, args=(s, tracks), daemon=True).start()

    def _wait(self, cond: Callable[[], bool], timeout: float = 1800):
        end = time.time() + timeout
        while not cond() and time.time() < end:
            time.sleep(0.1)

    def _finish(self, s: Session, tracks: dict[str, Track]):
        try:
            with self.feed_lock:
                for tr in tracks.values():
                    tr.seg.flush()
                    if tr.wav:
                        tr.wav.close()
            self._wait(lambda: s.pending_utts == 0)
            with self.lock:
                for tr in tracks.values():
                    self._close_paragraph(s, tr)
                if self._amount(s) >= (3 if s.mode == "audio" else 20):   # 最后一小段也复盘
                    self._queue_review(s, "final_part")
            self._wait(lambda: s.pending_reviews == 0)
            done = [r for r in s.reviews if r["status"] == "done"]
            want = (self.cfg.get("session_review") or "end") != "off"
            if want and prompts.has_content(s.reviews) and len(done) > 1:
                self.emit({"type": "status", "msg": "正在生成整场总复盘…"})
                try:
                    s.summary = chat(self.cfg, prompts.FINAL_SYSTEM,
                                     prompts.digest_user(s.reviews, self.cfg.get("about_me", "")))
                except Exception as e:
                    s.summary = f"> 总复盘生成失败：{e}"
            if not s.title:
                titles = [(r["analysis"] or {}).get("title") for r in done
                          if not (r["analysis"] or {}).get("trivial")]
                s.title = "、".join(list(dict.fromkeys(t for t in titles if t))[:3]) or "录音"   # 去重
        except Exception:
            self.emit({"type": "error", "msg": traceback.format_exc()[-500:]})
        with self.lock:
            s.status = "done"
            s.save()
        self._sync(s, final=True)
        self.emit({"type": "state", **self.state()})

    def _sync(self, s: Session, final: bool = False):
        """同步到 NAS。录音中途不传 WAV（还在写）"""
        skip = set() if final else {f.name for f in s.dir.glob("*.wav")}
        st = nas.sync_dir(s.dir, self.cfg, skip)
        if st:
            s.nas_status = st
            self.emit({"type": "nas", "msg": st})
