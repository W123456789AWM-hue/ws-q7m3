# 安装程序 AIMind-Setup-<版本>.exe（单个文件）。主程序要先打好：
#   AIMIND_PAYLOAD=<主程序文件夹压成的 zip> pyinstaller --noconfirm packaging/setup.spec
# 一般不用直接调用，用 packaging/build_windows.bat
import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

HERE = Path(SPECPATH)
ROOT = HERE.parent.parent
ICON_PNG = ROOT / "mobile/ios/Runner/Assets.xcassets/AppIcon.appiconset/Icon-App-1024x1024@1x.png"
PAYLOAD = os.environ["AIMIND_PAYLOAD"]
SERVER = HERE.parent
VERSION = {}  # 从 aimind/version.py 读（全工程只写一处）
exec((SERVER / "aimind" / "version.py").read_text(encoding="utf-8-sig"), VERSION)
VERSION = VERSION["VERSION"]

a = Analysis(
    [str(HERE / "setup_app.py")],
    pathex=[str(SERVER)],
    datas=[(PAYLOAD, "."), (str(HERE / "setup_ui.html"), "."), (str(HERE / "setup_logo.png"), ".")]
          + collect_data_files("webview"),
    hiddenimports=collect_submodules("webview", filter=lambda n: ".android" not in n),
    excludes=["numpy", "PIL", "tkinter", "fastapi", "uvicorn", "sounddevice"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, a.binaries, a.datas, [],
    name=f"AIMind-Setup-{VERSION}",
    console=False,
    icon=str(ICON_PNG),
    upx=False,
)
