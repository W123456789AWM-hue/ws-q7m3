"""启动入口：python run.py（start.bat / start.command 会自动调用）

环境变量：AIMIND_PORT 端口（默认 8765）、AIMIND_HOST 监听地址、AIMIND_NO_BROWSER=1 不自动开窗口、
AIMIND_DATA 数据目录（默认 server/data）。旧名字 AI_MIND_* 也认。
"""
import os
import shutil
import subprocess
import sys
import threading
import time
import webbrowser


def env(name: str, default: str = "") -> str:
    return os.environ.get("AIMIND_" + name) or os.environ.get("AI_MIND_" + name) or default


if env("DATA"):
    os.environ.setdefault("AIMIND_DATA", env("DATA"))
from aimind.portpick import choose_port  # noqa: E402  （要在设好数据目录之后导入）

# 8765 被别的程序占着时自动换一个端口（会记在设置里，以后一直用它）
PORT, PORT_MOVED, PORT_WANTED = choose_port(env("PORT"))
os.environ["AIMIND_PORT"] = str(PORT)
URL = f"http://127.0.0.1:{PORT}"


def open_window():
    time.sleep(1.5)
    if env("NO_BROWSER"):
        return
    # Windows 上优先用 Edge 的“应用模式”，看起来就像独立软件（没有地址栏）
    if sys.platform == "win32":
        for exe in (shutil.which("msedge"),
                    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"):
            if exe and os.path.exists(exe):
                subprocess.Popen([exe, f"--app={URL}", "--window-size=1280,860"])
                return
    if sys.platform == "darwin":
        for app in ("Google Chrome", "Microsoft Edge"):
            if os.path.exists(f"/Applications/{app}.app"):
                subprocess.Popen(["open", "-na", app, "--args", f"--app={URL}", "--window-size=1280,860"])
                return
    webbrowser.open(URL)


if __name__ == "__main__":
    import uvicorn
    print(f"AI 录音思考助手已启动：{URL}")
    if PORT_MOVED:
        print(f"注意：{PORT_WANTED} 端口被别的程序占用，已改用 {PORT}。手机 App 里的电脑地址端口要改成 :{PORT}")
    print("关闭这个黑色窗口即可退出程序。")
    threading.Thread(target=open_window, daemon=True).start()
    # 监听局域网，手机才能连进来；局域网里的访问都要带口令（见界面上的「设备连接」）
    uvicorn.run("aimind.web.app:app", host=env("HOST", "0.0.0.0"),
                port=PORT, log_level="warning")
