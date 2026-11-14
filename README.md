# AI 录音思考助手

- `安装包/`：已经打好的安装包。电脑端双击 `AIMind-Setup-<版本>.exe` 安装；安卓手机装 `AIMind-Android-arm64.apk`。
- `server/`：电脑端（Windows / Mac）。可以打包成独立程序（不用装 Python）：Windows 双击 `server/packaging/build_windows.bat`，
  Mac 运行 `bash server/packaging/build_mac.sh`。也可以继续双击 `start.bat` / `start.command` 用源码启动。说明见 `server/README.md`。
- `mobile/`：手机 App（安卓 / iPhone）。打包方法见 `mobile/README.md`。
- **云端一次打出全部四个平台**（Windows、Mac、安卓、iPhone，不需要 Mac）：把整个文件夹传到 GitHub，
  在 Actions 里运行「Build all」（`.github/workflows/build-all.yml`），跑完在 Artifacts 里下载。
- `CLAUDE.md`：代码结构与开发约定（在 Claude Code 里打开本文件夹会自动读取）。
