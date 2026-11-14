# 打包电脑端 Windows 版 —— 由 packaging\build_windows.bat 调用
# 输出到 server\dist：
#   AIMind-Windows.zip           解压即用的绿色版（里面双击 AIMind.exe）
#   AIMind-Setup-<版本>.exe       安装程序（推荐给用户：双击安装，有桌面 / 开始菜单快捷方式，能在设置里卸载）
# 编译用的环境放在 %LOCALAPPDATA%\ai_mind_build（路径短，避免 Windows 路径过长出错），不改系统设置。
$ErrorActionPreference = 'Stop'
$server = Split-Path -Parent $PSScriptRoot
$tc  = Join-Path $env:LOCALAPPDATA 'ai_mind_build'
$venv = Join-Path $tc 'deskvenv'
$work = Join-Path $tc 'desk_out'
$dist = Join-Path $server 'dist'
New-Item -ItemType Directory -Force $tc, $dist | Out-Null

$py = $null
foreach ($c in @('py -3', 'python')) {
  try { & cmd /c "$c -c ""import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)""" 2>$null; if ($LASTEXITCODE -eq 0) { $py = $c; break } } catch { }
}
if (-not $py) { throw '没有找到 Python 3.10 以上版本：https://www.python.org/downloads/' }

if (-not (Test-Path "$venv\Scripts\python.exe")) {
  Write-Host '创建编译环境…'
  & cmd /c "$py -m venv ""$venv"""
  if ($LASTEXITCODE -ne 0) { throw '创建编译环境失败' }
}
Write-Host '安装依赖…'
& "$venv\Scripts\python.exe" -m pip install -q -r "$server\requirements.txt" pyinstaller pywebview pillow
if ($LASTEXITCODE -ne 0) {
  & "$venv\Scripts\python.exe" -m pip install -q -r "$server\requirements.txt" pyinstaller pywebview pillow -i https://pypi.tuna.tsinghua.edu.cn/simple
  if ($LASTEXITCODE -ne 0) { throw '安装依赖失败' }
}

Write-Host '打包…'
Push-Location $server
try {
  & "$venv\Scripts\pyinstaller.exe" --noconfirm --log-level WARN --distpath "$work\dist" --workpath "$work\work" packaging\aimind.spec
  if ($LASTEXITCODE -ne 0) { throw 'PyInstaller 打包失败' }
} finally { Pop-Location }

$app = Join-Path $work 'dist\AIMind'
$zip = Join-Path $dist 'AIMind-Windows.zip'
Remove-Item -Force $zip -ErrorAction SilentlyContinue
Compress-Archive -Path $app -DestinationPath $zip
Write-Host "绿色版：$zip" -ForegroundColor Green

# 安装程序：主程序文件夹压成 payload.zip，和安装界面一起打成单个 exe
Write-Host '生成安装程序…'
$payload = Join-Path $work 'payload.zip'
Copy-Item -Force $zip $payload
$env:AIMIND_PAYLOAD = $payload
Push-Location $server
try {
  & "$venv\Scripts\pyinstaller.exe" --noconfirm --log-level WARN --distpath $dist --workpath "$work\setup_work" packaging\setup.spec
  if ($LASTEXITCODE -ne 0) { throw '生成安装程序失败' }
} finally { Pop-Location }
Write-Host "安装程序：$((Get-ChildItem $dist -Filter 'AIMind-Setup-*.exe' | Sort-Object LastWriteTime | Select-Object -Last 1).FullName)" -ForegroundColor Green
if (-not $env:AIMIND_NO_EXPLORER) { Start-Process explorer.exe $dist }
