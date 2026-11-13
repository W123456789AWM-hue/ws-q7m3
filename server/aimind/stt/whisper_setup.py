"""Whisper（显卡）安装后的准备：下载模型 → 在显卡上试跑 → 成功就把识别模型切换成 Whisper。
由 install_whisper_gpu.bat 调用：  python -m aimind.stt.whisper_setup
"""
from __future__ import annotations

import subprocess
import sys
import time

import numpy as np

from .. import config as config_mod
from . import local as stt_local


def main() -> int:
    cfg = config_mod.load()
    size = cfg.get("local_whisper_model") or "large-v3"
    print("\n==== 1/3 检查显卡 ====")
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total,driver_version",
                              "--format=csv,noheader"], capture_output=True, text=True, timeout=20)
        print("显卡：" + (out.stdout.strip() or "（nvidia-smi 没有输出）"))
    except Exception:
        print("没找到 nvidia-smi：请确认装了 NVIDIA 显卡驱动")

    print(f"\n==== 2/3 下载 Whisper {size} 模型（约 3GB，可断点续传）====")
    last = [""]

    def progress(msg: str):
        if msg != last[0]:
            last[0] = msg
            print("\r" + msg.ljust(70), end="", flush=True)

    try:
        stt_local.download_whisper(size, progress)
        print()
    except Exception as e:
        print(f"\n[失败] {e}\n网络恢复后重新运行本程序，会从断点继续。")
        return 1

    print("\n==== 3/3 在显卡上试跑 ====")
    try:
        t0 = time.time()
        w = stt_local.LocalWhisper({**cfg, "whisper_device": "cuda"}, lambda m: print("  " + m))
        t1 = time.time()
        w.transcribe((np.random.randn(16000 * 5) * 50).astype(np.int16))
        print(f"  加载用时 {t1 - t0:.1f} 秒；识别 5 秒音频用时 {time.time() - t1:.2f} 秒（{w.device}）")
    except Exception as e:
        print(f"\n[失败] 显卡上跑不起来：{e}")
        print("识别模型没有切换，程序会继续用原来的模型。把这个窗口截图发给 Claude。")
        return 1

    config_mod.save({"stt_provider": "whisper", "local_whisper_model": size})
    print("\n全部完成：识别模型已切换为 Whisper。现在可以双击 start.bat 启动程序了。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
