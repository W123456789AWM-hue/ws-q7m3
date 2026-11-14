"""生成界面音效文件（改了 aimind/sounds.py 之后运行一次，把生成的文件一起提交）：

    python packaging/make_sounds.py

- aimind/web/static/sounds/click.wav           网页里的按钮音效
- ../mobile/assets/sounds/click.wav、splash.wav 手机 App 用（手机的启动动画是 1.5 倍速，音效按同样的速度生成）
电脑端的启动动画音效不用文件：桌面程序启动时按设置的速度现场生成。
"""
from __future__ import annotations

import sys
from pathlib import Path

SERVER = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SERVER))
from aimind import sounds  # noqa: E402

MOBILE_SPLASH_SPEED = 1.5      # 和 mobile/lib/ui/splash.dart 的 speed 一致


def main() -> None:
    out = {
        SERVER / "aimind/web/static/sounds/click.wav": sounds.click_wav(),
        SERVER.parent / "mobile/assets/sounds/click.wav": sounds.click_wav(),
        SERVER.parent / "mobile/assets/sounds/splash.wav": sounds.splash_wav(MOBILE_SPLASH_SPEED),
    }
    for path, data in out.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        print(f"{path.relative_to(SERVER.parent)}  {len(data) // 1024} KB")


if __name__ == "__main__":
    main()
