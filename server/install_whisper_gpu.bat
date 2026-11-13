@echo off
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONUTF8=1
set "PY=.venv\Scripts\python.exe"
if not exist "%PY%" (
  echo Please run start.bat once first, then close it and run this again.
  pause
  exit /b 1
)

rem Only the packages that are really needed are installed, each WITHOUT its dependency list:
rem some dependencies (av, PyYAML, onnxruntime) have no prebuilt package for very new Python
rem versions. The app does not use them and works without them.
set "CORE=nvidia-cublas-cu12 nvidia-cudnn-cu12 ctranslate2 tokenizers faster-whisper"
set "OPT=--retries 5 --timeout 120"

"%PY%" -m pip show %CORE% tqdm >nul 2>nul
if not errorlevel 1 goto setup

echo Installing Whisper + NVIDIA CUDA 12 runtime libraries (about 1.5GB)...
call :try https://mirrors.aliyun.com/pypi/simple
if not errorlevel 1 goto setup
call :try https://pypi.org/simple
if not errorlevel 1 goto setup
call :try https://mirrors.cloud.tencent.com/pypi/simple
if not errorlevel 1 goto setup
echo.
echo [!] Install FAILED on all 3 sources.
echo     The reason of each attempt is saved in whisper_install_log.txt in this folder.
echo     Please send that file to Claude.
pause
exit /b 1

:try
echo.
echo ---- trying %1
echo ==== %1 ==== >> whisper_install_log.txt
"%PY%" -m pip install %OPT% --no-deps --only-binary=:all: %CORE% -i %1 --log whisper_install_log.txt
if errorlevel 1 exit /b 1
"%PY%" -m pip install %OPT% tqdm -i %1 --log whisper_install_log.txt
if errorlevel 1 exit /b 1
rem optional extras: fine if these fail
"%PY%" -m pip install %OPT% pyyaml -i %1 >nul 2>nul
exit /b 0

:setup
"%PY%" -m aimind.stt.whisper_setup
echo.
pause
