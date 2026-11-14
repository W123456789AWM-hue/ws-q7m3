# PyInstaller 打包配置：Windows 出 AIMind.exe（文件夹形式），Mac 出 AIMind.app
# 用法（在 server/ 下）：pyinstaller --noconfirm packaging/aimind.spec
# 一般不用直接调用，用 packaging/build_windows.bat 或 packaging/build_mac.sh
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

SERVER = Path(SPECPATH).parent
ROOT = SERVER.parent
ICON_PNG = ROOT / "mobile/ios/Runner/Assets.xcassets/AppIcon.appiconset/Icon-App-1024x1024@1x.png"
VERSION = {}  # 从 aimind/version.py 读（全工程只写一处）
exec((SERVER / "aimind" / "version.py").read_text(encoding="utf-8-sig"), VERSION)
VERSION = VERSION["VERSION"]

hidden = (collect_submodules("aimind") + collect_submodules("uvicorn") + collect_submodules("webview", filter=lambda n: ".android" not in n)
          + ["run", "splash_win", "PIL.WebPImagePlugin"])
datas = [(str(SERVER / "aimind/web/static"), "aimind/web/static")]
datas += collect_data_files("webview")

# 用户反馈的飞书机器人地址：云端打包时来自 GitHub 密钥（环境变量 FEEDBACK_WEBHOOK / FEEDBACK_SECRET），
# 本机打包时用 %LOCALAPPDATA%\ai_mind_build\feedback_target.json（如果有）。不写进源码目录，也不提交
import json as _json  # noqa: E402
import os as _os  # noqa: E402

_fb = SERVER / "build" / "feedback_target.json"
if _os.environ.get("FEEDBACK_WEBHOOK"):
    _fb.parent.mkdir(parents=True, exist_ok=True)
    _fb.write_text(_json.dumps({"webhook": _os.environ["FEEDBACK_WEBHOOK"].strip(),
                                "secret": _os.environ.get("FEEDBACK_SECRET", "").strip(),
                                # 附图上传用的飞书自建应用（选填）
                                "app_id": _os.environ.get("FEEDBACK_APP_ID", "").strip(),
                                "app_secret": _os.environ.get("FEEDBACK_APP_SECRET", "").strip()}),
                    encoding="utf-8")
else:
    _local = Path(_os.environ.get("LOCALAPPDATA", "~")).expanduser() / "ai_mind_build" / "feedback_target.json"
    _fb = _local if _local.exists() else None
if _fb:
    datas.append((str(_fb), "aimind"))
    print("feedback: webhook configured")   # 只用英文：云端 Windows 控制台是 cp1252，打印中文会直接报错
else:
    print("feedback: no webhook, feedback will be queued locally")

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
