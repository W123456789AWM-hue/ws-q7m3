#!/bin/bash
# Mac 启动：在访达里双击本文件（第一次如果提示“无法打开”，请右键 → 打开）
cd "$(dirname "$0")" || exit 1

PY=""
for c in python3.13 python3.12 python3.11 python3.10 python3; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
    PY="$c"; break
  fi
done
if [ -z "$PY" ]; then
  echo "没有找到 Python 3.10 以上版本。"
  echo "请到 https://www.python.org/downloads/macos/ 下载安装，然后再双击本文件。"
  read -r -p "按回车键关闭…" _
  exit 1
fi

if [ ! -x .venv/bin/python ]; then
  echo "第一次运行：创建运行环境…"
  "$PY" -m venv .venv || { read -r -p "创建失败，按回车键关闭…" _; exit 1; }
fi

if [ ! -f .venv/installed_v4.flag ]; then
  echo "第一次运行：安装依赖（约 1 分钟）…"
  .venv/bin/python -m pip install -r requirements.txt \
    || .venv/bin/python -m pip install -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple \
    || { echo; echo "安装失败，请把这个窗口截图发给 Claude。"; read -r -p "按回车键关闭…" _; exit 1; }
  touch .venv/installed_v4.flag
fi

echo
echo "第一次运行时 Mac 会询问："
echo "  · 是否允许“终端”使用麦克风（要用这台 Mac 录音就点允许）"
echo "  · 是否允许 Python 接受传入的网络连接（手机等设备要连进来就点允许）"
echo
.venv/bin/python run.py
