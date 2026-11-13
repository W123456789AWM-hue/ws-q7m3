"""同步到 NAS（任何电脑上能访问的目录：Windows 共享路径、映射盘、Mac 的 /Volumes/…）"""
from __future__ import annotations

import shutil
import time
from pathlib import Path


def nas_root(cfg: dict) -> Path | None:
    p = (cfg.get("nas_dir") or "").strip()
    return Path(p) if p else None


def sync_dir(src: Path, cfg: dict, skip: set[str] = frozenset()) -> str:
    """把 src 里的文件复制到 NAS/<src 的文件夹名>/（已经一样的跳过）。返回状态文字"""
    root = nas_root(cfg)
    if root is None:
        return ""
    try:
        dst = root / src.name
        dst.mkdir(parents=True, exist_ok=True)
        for f in src.iterdir():
            if f.is_dir() or f.suffix == ".tmp" or f.name in skip:
                continue
            t = dst / f.name
            st = f.stat()
            if t.exists() and t.stat().st_size == st.st_size and t.stat().st_mtime >= st.st_mtime:
                continue
            shutil.copy2(f, t)
        return f"已同步到 NAS {time.strftime('%H:%M:%S')}"
    except Exception as e:
        return f"NAS 同步失败（文件已存本地，下次会重试）：{e}"


def copy_file(f: Path, cfg: dict, sub: str) -> str:
    root = nas_root(cfg)
    if root is None:
        return ""
    try:
        (root / sub).mkdir(parents=True, exist_ok=True)
        shutil.copy2(f, root / sub / f.name)
        return ""
    except Exception as e:
        return f"同步 NAS 失败：{e}"


def test_write(cfg: dict) -> dict:
    root = nas_root(cfg)
    if root is None:
        return {"ok": False, "msg": "还没填写 NAS 目录"}
    try:
        root.mkdir(parents=True, exist_ok=True)
        t = root / ".write_test.txt"
        t.write_text("ok", encoding="utf-8")
        t.unlink()
        return {"ok": True, "msg": f"可以写入 {root}"}
    except Exception as e:
        return {"ok": False, "msg": f"无法写入：{e}"}
