#!/bin/bash
# 打包给用户：dist/aimind.zip（整个仓库：电脑端 + 手机 App + CLAUDE.md，解压后可直接用 Claude Code 打开）
set -e
cd "$(dirname "$0")/.."
rm -rf dist && mkdir -p dist
EXCL=(-x '*/__pycache__/*' -x '*/.pytest_cache/*' -x '*/.ruff_cache/*' -x '*/data/*' -x '*/.venv/*'
      -x '*/build/*' -x '*/.dart_tool/*' -x '*/output/*' -x '*.pyc' -x '*/安装包/*')
cd .. && zip -qr "$OLDPWD/dist/aimind.zip" "$(basename "$OLDPWD")" -x "*/dist/*" -x "*/.git/*" "${EXCL[@]}" && cd "$OLDPWD"
ls -lh dist
