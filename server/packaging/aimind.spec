# PyInstaller 打包配置：Windows 出 AIMind.exe（文件夹形式），Mac 出 AIMind.app
# 用法（在 server/ 下）：pyinstaller --noconfirm packaging/aimind.spec
# 一般不用直接调用，用 packaging/build_windows.bat 或 packaging/build_mac.sh
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

SERVER = Path(SPECPATH).parent
ROOT = SERVER.parent
ICON_PNG = ROOT / "mobile/ios/Runner/Assets.xcassets/AppIcon.appiconset/Icon-App-1024x1024@1x.png"
VERSION = "0.9.0"

hidden = (collect_submodules("aimind") + collect_submodules("uvicorn") + collect_submodules("webview", filter=lambda n: ".android" not in n)
          + ["run", "splash_win", "PIL.WebPImagePlugin"])
datas = [(str(SERVER / "aimind/web/static"), "aimind/web/static")]
datas += collect_data_files("webview")

a = Analysis(
    [str(SERVER / "desktop_app.py")],
    pathex=[str(SERVER)],
    datas=datas,
    hiddenimports=hidden,
    # 本地识别（sherpa-onnx / whisper）体积太大，不打进安装包；测试工具也不需要
    excludes=["tests", "tools", "pytest", "sherpa_onnx", "faster_whisper", "torch", "tkinter"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="AIMind",
    console=False,            # 不要黑色命令行窗口
    icon=str(ICON_PNG),
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="AIMind", upx=False)

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="AI录音思考助手.app",
        icon=str(ICON_PNG),
        bundle_identifier="com.example.aimind.desktop",
        version=VERSION,
        info_plist={
            "CFBundleDisplayName": "AI 录音思考助手",
            "CFBundleShortVersionString": VERSION,
            "NSMicrophoneUsageDescription": "用这台 Mac 的麦克风录音，交给 AI 做复盘。",
            "NSLocalNetworkUsageDescription": "让局域网里的手机、平板把录音传到这台 Mac。",
            "NSHighResolutionCapable": True,
            "LSMinimumSystemVersion": "11.0",
        },
    )
