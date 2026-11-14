# 安装程序 AIMind-Setup-<版本>.exe（单个文件）。主程序要先打好：
#   AIMIND_PAYLOAD=<主程序文件夹压成的 zip> pyinstaller --noconfirm packaging/setup.spec
# 一般不用直接调用，用 packaging/build_windows.bat
import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

HERE = Path(SPECPATH)
ROOT = HERE.parent.parent
ICON_PNG = ROOT / "mobile/ios/Runner/Assets.xcassets/AppIcon.appiconset/Icon-App-1024x1024@1x.png"
SERVER = HERE.parent
# 安装程序里固定找 payload.zip：不管传进来的 zip 叫什么名字，都先复制成这个名字再打包
# （以前云端直接传 AIMind-Windows.zip，打出来的安装程序报“缺少 payload.zip”）
import shutil  # noqa: E402

_src = Path(os.environ["AIMIND_PAYLOAD"]).resolve()
PAYLOAD = str(_src)
if _src.name != "payload.zip":
    _dst = SERVER / "build" / "setup_payload" / "payload.zip"
    _dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(_src, _dst)
    PAYLOAD = str(_dst)
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
