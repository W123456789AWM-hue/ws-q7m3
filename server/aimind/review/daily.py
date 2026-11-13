"""大复盘：日复盘 → 月复盘 → 年复盘（逐级汇总，越往上看得越远）

- 日复盘：这一天所有会话的阶段复盘（多台设备的都在里面）
- 月复盘：这个月每天的日复盘；没有日复盘的日子用当天阶段复盘的摘要
- 年复盘：这一年每个月的月复盘；缺的月份先自动补一份月复盘
逐级汇总只把上一级的结论交给 AI，不会把一整年的原始内容都发过去，省 token。

文件：data/daily/2026-11-13.md、data/monthly/2026-11.md、data/yearly/2026.md（同步到 NAS 同名文件夹）
"""
from __future__ import annotations

import calendar
import threading
import time
from datetime import date, datetime, timedelta
from pathlib import Path

from .. import config as config_mod
from .. import nas
from ..config import DATA_DIR
from ..session import DAILY_DIR, SESSIONS_DIR, load_session
from . import prompts
from .llm import chat

DIRS = {"day": DAILY_DIR, "month": DATA_DIR / "monthly", "year": DATA_DIR / "yearly"}
NAS_SUB = {"day": "daily", "month": "monthly", "year": "yearly"}
NAMES = {"day": "日复盘", "month": "月复盘", "year": "年复盘"}
DAY_CHARS = 2500        # 月复盘里每天最多带多少字（日复盘一般 1000–2000 字）

_busy = threading.Lock()


def _file(period: str, key: str) -> Path:
    return DIRS[period] / f"{Path(key).name}.md"


def read_report(period: str, key: str) -> str:
    f = _file(period, key)
    return f.read_text(encoding="utf-8") if f.exists() else ""


def list_reports(period: str) -> list[str]:
    d = DIRS[period]
    return sorted((f.stem for f in d.glob("*.md")), reverse=True) if d.exists() else []


def _session_reviews(prefix: str) -> list[dict]:
    """prefix：20261113（某天）/ 202611（某月）"""
    reviews = []
    for d in sorted(SESSIONS_DIR.glob(prefix + "*")):
        j = load_session(d.name)
        if j:
            reviews += j.get("reviews", [])
    return reviews


def has_data(period: str, key: str) -> bool:
    prefix = key.replace("-", "")
    return any(SESSIONS_DIR.glob(prefix + "*")) or (period == "year" and bool(
        [k for k in list_reports("month") if k.startswith(key)]))


def _days_of(month: str) -> list[str]:
    y, m = map(int, month.split("-"))
    return [f"{month}-{d:02d}" for d in range(1, calendar.monthrange(y, m)[1] + 1)]


def _strip_title(md: str) -> str:
    """去掉报告第一行的“# xxx 日复盘”标题（上一级会自己标日期）"""
    lines = md.strip().splitlines()
    return "\n".join(lines[1:] if lines and lines[0].startswith("# ") else lines).strip()


def _build(period: str, key: str, cfg: dict, emit) -> tuple[str, str] | None:
    """返回 (系统提示, 用户内容)；没有内容时返回 None"""
    about = cfg.get("about_me", "")
    if period == "day":
        reviews = _session_reviews(key.replace("-", ""))
        if not prompts.has_content(reviews):
            return None
        return prompts.DAILY_SYSTEM, prompts.digest_user(reviews, about)

    if period == "month":
        parts = []
        for d in _days_of(key):
            md = read_report("day", d)
            if md:
                parts.append(f"### {d}\n{_strip_title(md)[:DAY_CHARS]}")
                continue
            reviews = _session_reviews(d.replace("-", ""))
            if prompts.has_content(reviews):   # 那天没做日复盘：用阶段复盘的摘要代替
                parts.append(f"### {d}（阶段复盘摘要）\n{prompts.brief_digest(reviews)}")
        if not parts:
            return None
        return prompts.MONTHLY_SYSTEM, prompts.period_user(about, f"{key} 每天的复盘", parts)

    # 年复盘：每个月的月复盘，缺的先补
    parts = []
    for m in range(1, 13):
        mk = f"{key}-{m:02d}"
        md = read_report("month", mk)
        if not md and any(SESSIONS_DIR.glob(mk.replace("-", "") + "*")):
            emit({"type": "status", "msg": f"年复盘需要 {mk} 的月复盘，先补一份…"})
            md = _make_locked("month", mk, cfg, emit) or ""
        if md:
            parts.append(f"### {mk}\n{_strip_title(md)}")
    if not parts:
        return None
    return prompts.YEARLY_SYSTEM, prompts.period_user(about, f"{key} 年每个月的月复盘", parts)


def _make_locked(period: str, key: str, cfg: dict, emit) -> str:
    built = _build(period, key, cfg, emit)
    if built is None:
        return ""
    emit({"type": "status", "msg": f"正在生成 {key} {NAMES[period]}…"})
    system, user = built
    md = f"# {key} {NAMES[period]}\n\n" + chat(cfg, system, user, max_tokens=6000) + "\n"
    f = _file(period, key)
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(md, encoding="utf-8")
    err = nas.copy_file(f, cfg, NAS_SUB[period])
    if err:
        emit({"type": "nas", "msg": NAMES[period] + err})
    emit({"type": "report", "period": period, "key": key, "md": md})
    if period == "day":
        emit({"type": "daily", "date": key, "md": md})   # 旧版界面 / 手机 App 认这个
    return md


def make_report(period: str, key: str, emit=lambda m: None, auto: bool = False) -> str:
    if period not in DIRS:
        raise RuntimeError("未知的复盘周期")
    if not _busy.acquire(blocking=False):
        raise RuntimeError("正在生成另一份复盘，请稍等")
    try:
        md = _make_locked(period, key, config_mod.load(), emit)
        if not md and not auto:
            raise RuntimeError(f"这段时间还没有可用的复盘内容，做不了{NAMES[period]}")
        return md
    finally:
        _busy.release()


# ---- 旧接口（手机 App 和 /api/daily 在用）----
def read(day: str) -> str:
    return read_report("day", day)


def make(day: str, emit=lambda m: None, auto: bool = False) -> str:
    return make_report("day", day, emit, auto)


# ======================= 自动生成 =======================
def _at(d: date, hhmm: str) -> datetime:
    h, m = (int(x) for x in hhmm.split(":"))
    return datetime(d.year, d.month, d.day, h, m)


def due_reports(cfg: dict, now: datetime) -> list[tuple[str, str]]:
    """现在应该已经做好、但还没做的大复盘（包括电脑没开时错过的上一天 / 上个月 / 去年）"""
    out = []
    day_t = (cfg.get("daily_review_time") or "").strip()
    big_t = (cfg.get("period_review_time") or day_t or "23:30").strip()
    today = now.date()
    try:
        if day_t:
            for d in (today - timedelta(days=1), today):
                if now >= _at(d, day_t):
                    out.append(("day", d.isoformat()))
        mode = cfg.get("monthly_review") or "month_end"
        if mode != "off":
            first = today.replace(day=1)
            prev = (first - timedelta(days=1)).replace(day=1)
            for m in (prev, first):
                last = m.replace(day=calendar.monthrange(m.year, m.month)[1])
                when = _at(last, big_t) if mode == "month_end" else _at(last + timedelta(days=1), big_t)
                if now >= when:
                    out.append(("month", m.strftime("%Y-%m")))
        mode = cfg.get("yearly_review") or "year_end"
        if mode != "off":
            for y in (today.year - 1, today.year):
                when = _at(date(y, 12, 31), big_t) if mode == "year_end" else _at(date(y + 1, 1, 1), big_t)
                if now >= when:
                    out.append(("year", str(y)))
    except ValueError:      # 时间格式填错了
        pass
    return [(p, k) for p, k in out if not read_report(p, k) and has_data(p, k)]


def start_scheduler(emit):
    """后台线程：到了设置的时间自动做日 / 月 / 年复盘（按这个顺序，月复盘能用上当天的日复盘）"""
    tried: set[tuple[str, str]] = set()

    def loop():
        while True:
            time.sleep(30)
            try:
                for p, k in due_reports(config_mod.load(), datetime.now()):
                    if (p, k) in tried:
                        continue
                    tried.add((p, k))
                    make_report(p, k, emit, auto=True)
            except Exception as e:
                emit({"type": "error", "msg": f"自动复盘失败：{e}"})

    threading.Thread(target=loop, daemon=True).start()
