#!/usr/bin/env bash
# 一键打包并安装 iPhone 版（只能在 Mac 上运行）：  bash build_ios.sh
set -e
cd "$(dirname "$0")"

if [[ "$(uname)" != "Darwin" ]]; then
  echo "iPhone 版只能在 Mac 上编译（苹果的限制）。安卓版请在 Windows 上双击 build_android.bat。"
  exit 1
fi
command -v xcodebuild >/dev/null || { echo "请先从 App Store 安装 Xcode，并打开一次完成初始化。"; exit 1; }
command -v flutter >/dev/null || { echo "请先安装 Flutter： https://docs.flutter.dev/get-started/install/macos"; exit 1; }
command -v pod >/dev/null || { echo "请先安装 CocoaPods：  brew install cocoapods"; exit 1; }

bash scripts/setup.sh

if ! grep -q "DEVELOPMENT_TEAM" ios/Runner.xcodeproj/project.pbxproj; then
  echo
  echo "还没有设置签名。现在会打开 Xcode："
  echo "  左侧点 Runner → Signing & Capabilities → Team 选你的 Apple ID（没有就点 Add an Account 登录）"
  echo "设置好后关掉 Xcode，再运行一次本脚本。"
  open ios/Runner.xcworkspace
  exit 0
fi

echo
echo "用数据线连接 iPhone 并解锁（首次需要在手机上点“信任”，并在 设置 → 隐私与安全性 里打开开发者模式）。"
flutter run --release
