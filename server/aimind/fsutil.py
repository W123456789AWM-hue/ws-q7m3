"""写文件的小工具：扛住 Windows 上“文件被占用”。

Windows 上刚写完的文件常被杀毒软件、系统索引短暂打开；同步到 NAS 的线程也可能正在读它。
这时追加写入或替换文件会报 PermissionError（拒绝访问），过几十到几百毫秒就好了。
这里统一等一等再试，不让一次复盘或一次保存因此失败。
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Callable, Iterable, TypeVar

T = TypeVar("T")
DELAYS = (0.02, 0.05, 0.1, 0.2, 0.3, 0.5, 0.8)      # 最多等约 2 秒


def retry(fn: Callable[[], T]) -> T:
    """fn 报“被占用”时等一会儿再试；试完还不行就把最后的错误抛出去"""
    for d in DELAYS:
        try:
            return fn()
        except PermissionError:
            time.sleep(d)
    return fn()


def write_atomic(path: Path, text: str) -> None:
    """先写临时文件再整体换上去：写到一半断电也不会留下半个文件"""
    tmp = path.with_name(path.name + ".tmp")
    retry(lambda: tmp.write_text(text, encoding="utf-8"))
    retry(lambda: tmp.replace(path))


def append_jsonl(path: Path, rows: Iterable[dict]) -> bool:
    """往 .jsonl 日志追加几行。这类文件只是附带的记录：实在写不进去就记一笔，不影响主流程。返回是否写成功"""
    data = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows)
    if not data:
        return True

    def write():
        with open(path, "a", encoding="utf-8") as f:
            f.write(data)
    try:
        retry(write)
        return True
    except OSError as e:
        print(f"写入 {path.name} 失败（不影响使用）：{e}", file=sys.stderr)
        return False
