#!/usr/bin/env bash
# 打包电脑端 Mac 版（只能在 Mac 上运行）：  bash packaging/build_mac.sh
# 输出 server/dist/AIMind-Mac.dmg（里面是「AI录音思考助手.app」，拖进“应用程序”即可）
# 苹果芯片的 Mac 打出来的只能在苹果芯片上用，Intel Mac 打出来的只能在 Intel 上用。
set -e
cd "$(dirname "$0")/.."
[[ "$(uname)" == "Darwin" ]] || { echo "Mac 版只能在 Mac 上打包。"; exit 1; }

PY=""
for c in python3.13 python3.12 python3.11 python3.10 python3; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
    PY="$c"; break
  fi
done
[ -n "$PY" ] || { echo "请先安装 Python 3.10 以上：https://www.python.org/downloads/macos/"; exit 1; }

VENV="${TMPDIR:-/tmp}/aimind_build_venv"
[ -x "$VENV/bin/python" ] || "$PY" -m venv "$VENV"
"$VENV/bin/python" -m pip install -q -r requirements.txt pyinstaller pywebview pillow \
  || "$VENV/bin/python" -m pip install -q -r requirements.txt pyinstaller pywebview pillow -i https://mirrors.aliyun.com/pypi/simple

"$VENV/bin/pyinstaller" --noconfirm --log-level WARN --distpath build/mac/dist --workpath build/mac/work packaging/aimind.spec

APP="build/mac/dist/AI录音思考助手.app"
# 没有苹果开发者证书：做一个本机临时签名，避免“已损坏”提示（第一次打开仍需右键 → 打开）
codesign --force --deep --sign - "$APP" || true

mkdir -p dist
STAGE=build/mac/dmg; rm -rf "$STAGE"; mkdir -p "$STAGE"
cp -R "$APP" "$STAGE/"
ln -s /Applications "$STAGE/应用程序"
rm -f dist/AIMind-Mac.dmg
hdiutil create -volname "AI录音思考助手" -srcfolder "$STAGE" -ov -format UDZO dist/AIMind-Mac.dmg
echo
echo "完成：server/dist/AIMind-Mac.dmg"
