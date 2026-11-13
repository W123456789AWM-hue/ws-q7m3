#!/usr/bin/env bash
# macOS / Linux：生成平台工程 + 安装依赖（macOS 上顺带配置 iOS）
set -e
cd "$(dirname "$0")/.."

# 已存在的文件（AndroidManifest、Kotlin、lib/）不会被覆盖
flutter create --org com.example --project-name ai_mind --platforms=android,ios .
flutter pub get

if [[ "$(uname)" == "Darwin" ]]; then
  bash scripts/setup_ios.sh
fi

echo
echo "完成。接上手机后运行： flutter run"
