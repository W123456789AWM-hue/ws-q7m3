"""识别测试集：用你自己的真实录音衡量“哪个识别模型更准”。

1. 标注：从某一场录音里挑句子，边听边把识别结果改成“实际说的话”，存进测试集
2. 评测：让每个识别模型把测试集里的音频重新识别一遍，和你改对的文字比，算错误率
"""
from __future__ import annotations

import json
import re
import threading
import time
import wave
import zipfile
from pathlib import Path

import numpy as np

from . import config as config_mod
from .audio import SR

DIR = config_mod.DATA_DIR / "testset"
ITEMS = DIR / "items.json"
RESULTS = DIR / "results.json"
_lock = threading.Lock()

ENGINES = {"sensevoice": "SenseVoice", "paraformer": "Paraformer", "whisper": "Whisper large-v3（显卡）"}


# ---------------- 文本归一化与错误率 ----------------
_CN = {"零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7,
       "八": 8, "九": 9}
_UNIT = {"十": 10, "百": 100, "千": 1000}
_EN = {w: i for i, w in enumerate(
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen "
    "fifteen sixteen seventeen eighteen nineteen".split())}
_EN.update({"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70,
            "eighty": 80, "ninety": 90})


def _cn_num(run: str) -> str:
    """中文数字 → 阿拉伯数字（“二十五”→25，“九”→9）。不同模型有的写“九点”有的写“9点”，统一后才公平"""
    if not any(c in _UNIT or c == "万" for c in run):
        return "".join(str(_CN[c]) for c in run)
    total, section, num = 0, 0, 0
    for c in run:
        if c in _CN:
            num = _CN[c]
        elif c in _UNIT:
            section += (num or 1) * _UNIT[c]
            num = 0
        elif c == "万":
            total += (section + num) * 10000
            section, num = 0, 0
    return str(total + section + num)


def _en_num(m: re.Match) -> str:
    words = re.split(r"[\s-]+", m.group(0).strip())
    total = 0
    for w in words:
        total += _EN[w]
    return str(total)


def normalize(text: str) -> list[str]:
    """归一化后切成“词”：一个汉字算一个，一个英文单词/一串数字算一个"""
    t = (text or "").lower()
    t = re.sub(r"\b(?:(?:twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety)[\s-]+"
               r"(?:one|two|three|four|five|six|seven|eight|nine)\b|"
               r"(?:" + "|".join(sorted(_EN, key=len, reverse=True)) + r")\b)", _en_num, t)
    t = re.sub(r"[零〇一二两三四五六七八九十百千万]+",
               lambda m: _cn_num(m.group(0)) if re.search(r"[零〇一二两三四五六七八九]", m.group(0))
               else m.group(0), t)
    return re.findall(r"[a-z']+|\d+|[一-鿿㐀-䶿]", t)


def edit_ops(ref: list[str], hyp: list[str]) -> tuple[int, list[tuple[str, str, str]]]:
    """编辑距离 + 对齐结果 [(操作, 参考词, 识别词)]，操作：= 对 / S 错 / D 漏 / I 多"""
    n, m = len(ref), len(hyp)
    d = np.zeros((n + 1, m + 1), dtype=np.int32)
    d[:, 0] = np.arange(n + 1)
    d[0, :] = np.arange(m + 1)
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            d[i, j] = min(d[i - 1, j] + 1, d[i, j - 1] + 1,
                          d[i - 1, j - 1] + (ref[i - 1] != hyp[j - 1]))
    ops, i, j = [], n, m
    while i > 0 or j > 0:
        if i > 0 and j > 0 and d[i, j] == d[i - 1, j - 1] + (ref[i - 1] != hyp[j - 1]):
            ops.append(("=" if ref[i - 1] == hyp[j - 1] else "S", ref[i - 1], hyp[j - 1]))
            i, j = i - 1, j - 1
        elif i > 0 and d[i, j] == d[i - 1, j] + 1:
            ops.append(("D", ref[i - 1], ""))
            i -= 1
        else:
            ops.append(("I", "", hyp[j - 1]))
            j -= 1
    return int(d[n, m]), ops[::-1]


# ---------------- 测试集 ----------------
def load_items() -> list[dict]:
    if not ITEMS.exists():
        return []
    try:
        return json.loads(ITEMS.read_text(encoding="utf-8"))
    except Exception:
        return []


def _save_items(items: list[dict]):
    DIR.mkdir(parents=True, exist_ok=True)
    tmp = ITEMS.with_suffix(".tmp")
    tmp.write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(ITEMS)


def read_clip(session_dir: Path, seg: dict) -> np.ndarray:
    """从整场录音文件里取出一句。新版记录 file，旧版只有 part"""
    f = session_dir / (seg.get("file") or f"audio_{int(seg.get('part', 0)):03d}.wav")
    off, n = seg["off"], seg["n"]
    with wave.open(str(f), "rb") as w:
        w.setpos(max(0, min(int(off), w.getnframes())))
        return np.frombuffer(w.readframes(int(n)), dtype=np.int16)


def wav_bytes(pcm: np.ndarray) -> bytes:
    import io
    bio = io.BytesIO()
    with wave.open(bio, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.astype(np.int16).tobytes())
    return bio.getvalue()


def add_items(session: dict, session_dir: Path, picks: list[dict]) -> int:
    """picks: [{"i": 第几句（按整场顺序）, "ref": 改对后的文字}]"""
    segs = [s for p in session.get("paragraphs", []) for s in p["segments"]]
    with _lock:
        items = load_items()
        have = {(x["sid"], x["i"]) for x in items}
        next_id = max([x["id"] for x in items], default=0) + 1
        (DIR / "audio").mkdir(parents=True, exist_ok=True)
        added = 0
        for pk in picks:
            i, ref = int(pk["i"]), (pk.get("ref") or "").strip()
            if not ref or i < 0 or i >= len(segs) or segs[i].get("off", -1) < 0:
                continue
            seg = segs[i]
            if (session["id"], i) in have:  # 已经在测试集里：只更新文字
                for x in items:
                    if x["sid"] == session["id"] and x["i"] == i:
                        x["ref"] = ref
                continue
            pcm = read_clip(session_dir, seg)
            if len(pcm) < SR // 4:
                continue
            name = f"audio/{next_id:05d}.wav"
            (DIR / name).write_bytes(wav_bytes(pcm))
            items.append({"id": next_id, "sid": session["id"], "i": i, "clock": seg.get("clock"),
                          "audio": name, "sec": round(len(pcm) / SR, 2), "ref": ref,
                          "orig": seg.get("text", "")})
            next_id += 1
            added += 1
        _save_items(items)
        return added


def remove_item(item_id: int):
    with _lock:
        items = load_items()
        for x in items:
            if x["id"] == item_id:
                (DIR / x["audio"]).unlink(missing_ok=True)
        _save_items([x for x in items if x["id"] != item_id])


def summary() -> dict:
    items = load_items()
    res = None
    if RESULTS.exists():
        try:
            res = json.loads(RESULTS.read_text(encoding="utf-8"))
        except Exception:
            res = None
    return {"items": items, "count": len(items),
            "seconds": round(sum(x["sec"] for x in items), 1), "results": res}


def export_zip() -> Path:
    out = DIR / "testset_export.zip"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for f in [ITEMS, RESULTS]:
            if f.exists():
                z.write(f, f.name)
        for x in load_items():
            z.write(DIR / x["audio"], x["audio"])
    return out


# ---------------- 评测 ----------------
_running = False


def available_engines() -> list[str]:
    out = ["sensevoice", "paraformer"]
    try:
        from .stt.local import import_faster_whisper
        import_faster_whisper()
        out.append("whisper")
    except Exception:
        pass
    return out


def run_eval(emit, engines: list[str] | None = None):
    """在后台线程里跑；进度通过 emit 推给界面"""
    global _running
    if _running:
        raise RuntimeError("评测正在进行中")
    items = load_items()
    if not items:
        raise RuntimeError("测试集还是空的，先去标注几句")
    _running = True

    def job():
        global _running
        try:
            from .stt.transcriber import Transcriber
            cfg = config_mod.load()
            report = {"time": time.strftime("%Y-%m-%d %H:%M:%S"), "count": len(items),
                      "seconds": round(sum(x["sec"] for x in items), 1), "engines": []}
            # 基准：标注时原本的识别结果（也就是你平时实际看到的）
            todo = [("orig", "标注时的原始结果", None)]
            todo += [(e, ENGINES[e], e) for e in (engines or available_engines())]
            for key, label, provider in todo:
                rows, err, tot, t_used = [], 0, 0, 0.0
                tr = None
                if provider:
                    try:
                        emit({"type": "eval", "msg": f"准备 {label}…"})
                        tr = Transcriber({**cfg, "stt_provider": provider})
                        tr.prepare(lambda m, label=label: emit({"type": "eval", "msg": f"{label}：{m}"}))
                    except Exception as e:
                        report["engines"].append({"key": key, "label": label, "error": str(e)})
                        continue
                for n, x in enumerate(items, 1):
                    if provider:
                        with wave.open(str(DIR / x["audio"]), "rb") as w:
                            pcm = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
                        t0 = time.time()
                        try:
                            hyp = tr.transcribe(pcm)
                        except Exception as e:
                            hyp = f"[出错：{e}]"
                        t_used += time.time() - t0
                        if n % 5 == 0 or n == len(items):
                            emit({"type": "eval", "msg": f"{label}：{n}/{len(items)}"})
                    else:
                        hyp = x.get("orig", "")
                    ref_t, hyp_t = normalize(x["ref"]), normalize(hyp)
                    e, ops = edit_ops(ref_t, hyp_t)
                    err += e
                    tot += len(ref_t)
                    rows.append({"id": x["id"], "hyp": hyp, "errors": e, "words": len(ref_t),
                                 "ops": [o for o in ops]})
                report["engines"].append({
                    "key": key, "label": label, "errors": err, "words": tot,
                    "rate": round(err / tot * 100, 2) if tot else 0.0,
                    "perfect": sum(1 for r in rows if r["errors"] == 0),
                    "speed": round(report["seconds"] / t_used, 1) if t_used > 0 else None,
                    "rows": rows})
            DIR.mkdir(parents=True, exist_ok=True)
            RESULTS.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
            emit({"type": "eval", "msg": "评测完成", "done": True})
        except Exception as e:
            emit({"type": "eval", "msg": f"评测出错：{e}", "done": True, "error": True})
        finally:
            _running = False

    threading.Thread(target=job, daemon=True).start()
