"""一次录音（会话）的数据结构、保存、读取、生成 Markdown 报告。

session.json 的结构：
  paragraphs: [{id, device, device_name, start_t, start_clock, status, text,
                segments: [{t0, t1, clock, pid, device, text, rv?, file?, off?, n?, clip?, sec?}]}]
  reviews:    [{id, kind, date, from_clock, to_clock, chars, text, status, analysis, error,
                audio?: [{pid, device, device_name, clock, clips, secs}], sec?}]
segment 上的 rv = 它被第几次复盘用过（没有 rv 的就是还没复盘的内容）。
"""
from __future__ import annotations

import json
import unicodedata
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from .config import DATA_DIR

SESSIONS_DIR = DATA_DIR / "sessions"
DAILY_DIR = DATA_DIR / "daily"


def clock(t: datetime) -> str:
    return t.strftime("%H:%M:%S")


def with_pause(text: str) -> str:
    """有的识别模型不带标点：每句话之间有停顿，补一个逗号"""
    t = text.rstrip()
    if not t or unicodedata.category(t[-1])[0] in ("P", "S"):
        return t
    return t + (", " if t[-1].isascii() and t[-1].isalnum() else "，")


class Session:
    def __init__(self, started: Optional[datetime] = None, title: str = ""):
        self.started = started or datetime.now()
        self.id = self.started.strftime("%Y%m%d_%H%M%S")
        self.dir = SESSIONS_DIR / self.id
        self.dir.mkdir(parents=True, exist_ok=True)
        self.title = title
        self.paragraphs: list[dict] = []
        self.reviews: list[dict] = []
        self.summary = ""
        self.status = "recording"            # recording / finishing / done
        self.mode = "audio"                   # audio = AI 听录音；text = 本地识别成文字
        self.nas_status = ""
        self.last_review: datetime = self.started   # 上次复盘到的录音时间（周期复盘用）
        self.pending_utts = 0                 # 还没处理完的句子
        self.pending_reviews = 0              # 还没做完的复盘

    # ---------- 查询 ----------
    def segments(self) -> list[dict]:
        return [seg for p in self.paragraphs for seg in p["segments"]]

    def unreviewed(self) -> list[dict]:
        """还没复盘过的句子，按录音时间排序（几台设备的内容交错在一起）"""
        return sorted((x for x in self.segments() if "rv" not in x), key=lambda x: x["t0"])

    def rel(self, t: datetime) -> float:
        return round((t - self.started).total_seconds(), 2)

    def at(self, rel_sec: float) -> datetime:
        return self.started + timedelta(seconds=rel_sec)

    def devices(self) -> list[str]:
        out = []
        for p in self.paragraphs:
            name = p.get("device_name") or p.get("device") or ""
            if name and name not in out:
                out.append(name)
        return out

    # ---------- 存储 ----------
    def to_dict(self) -> dict:
        return {"id": self.id, "started": self.started.isoformat(timespec="seconds"),
                "title": self.title, "status": self.status, "summary": self.summary,
                "nas_status": self.nas_status, "mode": self.mode, "devices": self.devices(),
                "paragraphs": self.paragraphs, "reviews": self.reviews}

    def save(self):
        d = self.to_dict()
        tmp = self.dir / "session.json.tmp"
        tmp.write_text(json.dumps(d, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        tmp.replace(self.dir / "session.json")
        (self.dir / "report.md").write_text(render_markdown(d), encoding="utf-8")


def load_session(sid: str) -> Optional[dict]:
    f = SESSIONS_DIR / Path(sid).name / "session.json"
    if not f.exists():
        return None
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except Exception:
        return None


def list_sessions() -> list[dict]:
    if not SESSIONS_DIR.exists():
        return []
    out = []
    for d in sorted(SESSIONS_DIR.iterdir(), reverse=True):
        j = load_session(d.name)
        if j:
            out.append({"id": j["id"], "started": j["started"], "title": j.get("title") or "",
                        "count": len(j.get("reviews", [])), "status": j.get("status"),
                        "devices": j.get("devices", [])})
    return out


def render_markdown(s: dict) -> str:
    lines = [f"# {s.get('title') or '录音'}", "", f"开始时间：{s['started']}"]
    if s.get("devices"):
        lines.append(f"录音设备：{'、'.join(s['devices'])}")
    lines.append("")
    if s.get("summary"):
        lines += ["# 整场总复盘", "", s["summary"], ""]
    if s.get("reviews"):
        lines += ["# 阶段复盘", ""]

    def bullets(title, items, fmt=lambda x: x):
        if items:
            lines.append(f"**{title}**")
            lines.extend(f"- {fmt(x)}" for x in items)
            lines.append("")

    def pair(a, b, tpl):
        return lambda x: tpl.format(x.get(a), x.get(b)) if isinstance(x, dict) else x

    for r in s.get("reviews", []):
        a = r.get("analysis") or {}
        lines += [f"## {r['from_clock']}–{r['to_clock']} {a.get('title', '')}", ""]
        if r["status"] == "error":
            lines += [f"> 复盘失败：{r['error']}", ""]
        if a.get("trivial"):
            lines += ["> 闲聊/无实质内容", ""]
        if a.get("summary"):
            lines += [f"**概括**：{a['summary']}", ""]
        bullets("话题", a.get("topics"),
                lambda x: f"[{x.get('time')}] {x.get('topic')}：{x.get('gist')}" if isinstance(x, dict) else x)
        bullets("你可能没注意到", a.get("blind_spots"))
        bullets("潜在需求", a.get("latent_needs"), pair("need", "evidence", "{}（依据：{}）"))
        bullets("发散联想", a.get("divergent"), pair("angle", "idea", "【{}】{}"))
        bullets("建议", a.get("suggestions"), pair("priority", "text", "[{}] {}"))
        bullets("值得追问", a.get("questions"))
        bullets("和上次相比", a.get("changes"))
        bullets("从语气里听出来的", a.get("voice_cues"))
    lines += ["# 完整转写", ""]
    for p in s.get("paragraphs", []):
        dev = f"（{p['device_name']}）" if p.get("device_name") else ""
        lines += [f"**[{p['start_clock']}]{dev}** {p.get('text', '')}", ""]
    return "\n".join(lines)
