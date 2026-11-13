@echo off
chcp 65001 >nul
cd /d "%~dp0"

set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY where python >nul 2>nul && set "PY=python"
if not defined PY goto nopython
%PY% -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul
if errorlevel 1 goto nopython

if exist ".venv\Scripts\python.exe" goto deps
echo Creating virtual environment...
%PY% -m venv .venv
if errorlevel 1 goto fail

:deps
if exist ".venv\installed_v4.flag" goto run
echo Installing dependencies, first run only...
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 ".venv\Scripts\python.exe" -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
if errorlevel 1 goto fail
echo ok> ".venv\installed_v4.flag"

:run
".venv\Scripts\python.exe" run.py
pause
exit /b 0

:nopython
echo.
echo [!] Python 3.10+ not found.
echo     Download from https://www.python.org/downloads/
echo     During install, tick "Add python.exe to PATH", then run this file again.
pause
exit /b 1

:fail
echo.
echo [!] Setup failed. Please send a screenshot of this window to Claude.
pause
exit /b 1
