# Windows：生成 Android 工程 + 安装依赖（iOS 只能在 Mac 上编译）
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

flutter create --org com.example --project-name ai_mind --platforms=android,ios .
flutter pub get

Write-Host ""
Write-Host "Done. Connect an Android phone (USB debugging on), then run: flutter run"
