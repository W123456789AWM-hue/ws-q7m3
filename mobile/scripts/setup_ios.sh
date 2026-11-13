#!/usr/bin/env bash
# 给 ios/Runner/Info.plist 加上麦克风权限、后台录音、局域网访问（仅 macOS）
set -e
cd "$(dirname "$0")/.."
PLIST=ios/Runner/Info.plist
PB=/usr/libexec/PlistBuddy

set_key () { # key type value
  $PB -c "Delete :$1" "$PLIST" 2>/dev/null || true
  $PB -c "Add :$1 $2 $3" "$PLIST"
}

set_key NSMicrophoneUsageDescription string "需要使用麦克风进行全天录音。语音在手机本地转成文字，文字用于 AI 复盘，录音保存到你的 NAS。"
set_key NSLocalNetworkUsageDescription string "需要访问局域网内的 NAS 以保存录音和复盘结果。"
set_key CFBundleDisplayName string "AI录音思考"

# 后台录音
$PB -c "Delete :UIBackgroundModes" "$PLIST" 2>/dev/null || true
$PB -c "Add :UIBackgroundModes array" "$PLIST"
$PB -c "Add :UIBackgroundModes:0 string audio" "$PLIST"

# 允许 http:// 访问 NAS
$PB -c "Delete :NSAppTransportSecurity" "$PLIST" 2>/dev/null || true
$PB -c "Add :NSAppTransportSecurity dict" "$PLIST"
$PB -c "Add :NSAppTransportSecurity:NSAllowsArbitraryLoads bool true" "$PLIST"
$PB -c "Add :NSAppTransportSecurity:NSAllowsLocalNetworking bool true" "$PLIST"

echo "iOS Info.plist 已配置。首次真机运行前，用 Xcode 打开 ios/Runner.xcworkspace，"
echo "在 Signing & Capabilities 里选择你的 Apple ID 团队。"
