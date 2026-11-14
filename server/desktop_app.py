"""桌面程序入口（打包成 Windows 的 .exe / Mac 的 .app 时用这个，不用 run.py）

和 run.py 的区别：
- 界面在程序自己的窗口里（Windows 用系统自带的 Edge WebView2，Mac 用系统自带的 WebKit），没有黑色命令行窗口；
  关掉窗口就退出程序。
- 打包后的程序里不能写文件，数据存到用户目录：
    Windows：%APPDATA%\\AIMind\\data      Mac：~/Library/Application Support/AIMind/data
  （仍然可以用环境变量 AIMIND_DATA 指定）
- 程序已经在运行时，再双击只会打开一个新窗口连到正在运行的那个，不会重复启动。

开发时也可以直接运行：python desktop_app.py
"""
from __future__ import annotations

import os
import socket
import sys
import threading
import time
from pathlib import Path

APP_NAME = "AI 录音思考助手"
FROZEN = getattr(sys, "frozen", False)


def user_data_dir() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return base / "AIMind" / "data"


# 必须在 import aimind 之前设好数据目录（config.py 在导入时就确定目录）
if FROZEN and not (os.environ.get("AIMIND_DATA") or os.environ.get("AI_MIND_DATA")):
    os.environ["AIMIND_DATA"] = str(user_data_dir())
if os.environ.get("AI_MIND_DATA") and not os.environ.get("AIMIND_DATA"):
    os.environ["AIMIND_DATA"] = os.environ["AI_MIND_DATA"]

from aimind.portpick import choose_port, is_ours  # noqa: E402  （要在设好数据目录之后导入）

# 8765 被别的程序（比如 Loon 的配置服务）占着时，自动换一个端口并记住
PORT, PORT_MOVED, PORT_WANTED = choose_port(os.environ.get("AIMIND_PORT") or os.environ.get("AI_MIND_PORT"))
os.environ["AIMIND_PORT"] = str(PORT)
HOST = os.environ.get("AIMIND_HOST") or os.environ.get("AI_MIND_HOST") or "0.0.0.0"
URL = f"http://127.0.0.1:{PORT}"
os.environ["AIMIND_DESKTOP"] = "1"     # 告诉界面：在桌面程序里（设置里可以预览启动动画）


def port_busy() -> bool:
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", PORT)) == 0


SERVER_ERROR: list[BaseException] = []    # 后台启动服务失败时，记在这里


def wait_ready(timeout: float = 30) -> bool:
    end = time.time() + timeout
    while time.time() < end and not SERVER_ERROR:
        if port_busy():
            return True
        time.sleep(0.2)
    return False


def friendly_error(e: BaseException | None = None) -> str:
    """把启动失败的原因翻译成用户能照着做的话"""
    text = str(e or "")
    if "太长" in text or "too long" in text.lower() or getattr(e, "winerror", 0) == 206:
        return (f"启动失败：程序所在的文件夹路径太深（{Path(sys.executable).parent}）。\n\n"
                "请用安装程序 AIMind-Setup.exe 安装后再打开；\n"
                "或者把整个 AIMind 文件夹先解压到一个短路径（比如 D:\\AIMind）再运行。")
    if e is not None:
        return f"启动失败：{text}\n\n详细信息在 {log_file()}，可以发给 Claude。"
    return f"启动失败：端口 {PORT} 打不开（可能被别的程序占用了）。\n\n详细信息在 {log_file()}"


def notify_port_moved() -> None:
    """端口换了：告诉用户手机 App 里的地址要跟着改（只在换端口的那一次提示）"""
    if not wait_ready():
        return
    msg = (f"这台电脑的 {PORT_WANTED} 端口已经被别的程序占用了（比如 Loon / Surge 的配置服务），"
           f"AI 录音思考助手已自动改用 {PORT} 端口，以后会一直用它。\n\n"
           f"手机 App 里的「电脑地址」要把端口改成 :{PORT}。"
           "完整地址在程序右上角「设备连接」里能看到。")
    try:
        if sys.platform == "win32":
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, msg, APP_NAME, 0x40 | 0x40000)
        elif sys.platform == "darwin":
            import subprocess
            subprocess.run(["osascript", "-e", f'display dialog "{msg}" with title "{APP_NAME}" buttons {{"好"}}'],
                           check=False)
    except Exception:
        pass
    print(msg, file=sys.stderr)


def running_from_archive() -> bool:
    """在 WinRAR / 7-Zip / 资源管理器里直接双击压缩包里的程序：会被临时解压到很深的临时目录，经常跑不起来"""
    if not (FROZEN and sys.platform == "win32"):
        return False
    exe = str(Path(sys.executable).resolve()).lower()
    temp = os.path.normcase(os.environ.get("TEMP") or "").lower()
    marks = ("\\rar$", "\\7z", ".zip\\", "\\temp1_", "\\wz")
    return bool(temp) and exe.startswith(temp) and any(m in exe for m in marks)


def log_file() -> Path:
    d = Path(os.environ.get("AIMIND_DATA") or user_data_dir())
    d.mkdir(parents=True, exist_ok=True)
    return d / "app_log.txt"


def start_server() -> threading.Thread:
    """在后台线程里加载并启动服务：加载要 1–2 秒，这段时间启动动画已经在播了"""

    def serve():
        try:
            import uvicorn

            from aimind.web.app import app

            # 局域网监听，手机才能连进来（局域网访问都要带口令）
            server = uvicorn.Server(uvicorn.Config(app, host=HOST, port=PORT, log_level="warning",
                                                   log_config=None))
            server.run()
        except BaseException as e:   # noqa: BLE001  任何原因都要告诉用户，而不是一直卡着
            import traceback
            traceback.print_exc()
            SERVER_ERROR.append(e)

    t = threading.Thread(target=serve, daemon=True, name="aimind-server")
    t.start()
    return t


def show_error(msg: str) -> None:
    try:
        if sys.platform == "win32":
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, msg, APP_NAME, 0x10)
        elif sys.platform == "darwin":
            import subprocess
            subprocess.run(["osascript", "-e", f'display alert "{APP_NAME}" message "{msg}"'], check=False)
    except Exception:
        pass
    print(msg, file=sys.stderr)


STATIC = Path(__file__).resolve().parent / "aimind" / "web" / "static"
SPLASH_SIZE = (760, 290)          # 启动动画窗口大小（splash.webp 是 1000x381，按比例缩小）


def splash_settings() -> tuple[bool, float]:
    """(要不要播启动动画, 速度)。设置里可以改；环境变量 AIMIND_NO_SPLASH=1 也能关掉"""
    try:
        from aimind import config
        cfg = config.load()
        on, speed = bool(cfg.get("splash_enabled", True)), float(cfg.get("splash_speed") or 1)
    except Exception:
        on, speed = True, 1.0
    on = on and (STATIC / "splash.webp").exists() and not os.environ.get("AIMIND_NO_SPLASH")
    return on, max(0.25, min(4.0, speed))


class SplashApi:
    """给启动动画页面调用：speed() 取播放速度；done() 动画放完 → 等服务就绪 → 开主窗口 → 关掉动画窗口"""

    def __init__(self, on_done, speed: float = 1.0):
        self._on_done = on_done
        self._speed = speed

    def speed(self):
        return self._speed

    def done(self):
        self._on_done()


def splash_window(webview, on_done, speed: float):
    """Mac 的启动动画窗口（WebKit 透明窗口是真透明）。
    地址传普通文件路径（不是 file://），pywebview 会用自带的本地 http 服务打开，
    页面才能读到 splash.webp 的原始数据、按设置的速度逐帧播放。"""
    w, h = SPLASH_SIZE
    return webview.create_window(
        APP_NAME, str(STATIC / "splash.html"), width=w, height=h,
        frameless=True, transparent=True, on_top=True, resizable=False, easy_drag=False,
        js_api=SplashApi(on_done, speed))


def register_preview(webview) -> None:
    """设置里的「预览启动动画」：Windows 用分层窗口播放，Mac 再开一个动画窗口（放完自己关掉）"""
    from aimind.web import hub

    def preview(speed: float):
        if sys.platform == "win32":
            import splash_win
            threading.Thread(target=splash_win.play, args=(str(STATIC / "splash.webp"),),
                             kwargs={"css_width": SPLASH_SIZE[0], "speed": speed}, daemon=True).start()
            return
        box = {}

        def close():
            try:
                box["w"].destroy()
            except Exception:
                pass
        box["w"] = splash_window(webview, close, speed)

    hub.desktop_hooks["splash_preview"] = preview
    # 在线更新：安装程序已经启动，程序自己退出（安装程序会等它退出再换文件）
    hub.desktop_hooks["quit"] = lambda: threading.Timer(0.8, os._exit, (0,)).start()


def open_window() -> bool:
    """先播放启动动画（透明无边框窗口），放完再打开主窗口；主窗口关掉时返回。没装好窗口组件时返回 False。"""
    try:
        import webview
    except Exception:
        return False

    state = {"opened": False, "splash": None}
    lock = threading.Lock()

    def open_main():
        with lock:
            if state["opened"]:
                return
            state["opened"] = True
        if not wait_ready():
            show_error(friendly_error(SERVER_ERROR[0] if SERVER_ERROR else None))
            os._exit(1)
        webview.create_window(APP_NAME, URL, width=1280, height=860, min_size=(900, 600), text_select=True)
        if state["splash"] is not None:
            try:
                state["splash"].destroy()
            except Exception:
                pass

    register_preview(webview)
    use_splash, speed = splash_settings()
    if use_splash and sys.platform == "win32":
        # Windows：pywebview 的“透明窗口”会露出灰底，改用系统分层窗口播放（真正逐像素透明），放完再开主窗口
        use_splash = False
        try:
            import splash_win
            splash_win.play(str(STATIC / "splash.webp"), css_width=SPLASH_SIZE[0], speed=speed)
        except Exception as e:
            print(f"启动动画播放失败（不影响使用）：{e}", file=sys.stderr)

    try:
        if use_splash:     # Mac：WebKit 的透明窗口是真透明，直接用网页播放
            state["splash"] = splash_window(webview, open_main, speed)
            # 保险：动画页面出了问题也不会一直卡着
            timer = threading.Timer(15 / speed + 3, open_main)
            timer.daemon = True
            timer.start()
            webview.start(private_mode=False)
        else:
            open_main()   # 没有动画：直接开主窗口（pywebview 要求 start 之前至少有一个窗口）
            webview.start(private_mode=False)
        return state["opened"]
    except Exception as e:
        print(f"打开窗口失败：{e}", file=sys.stderr)
        return False


def browser_fallback() -> None:
    """系统里缺少窗口组件（比如很老的 Windows 没有 WebView2）：用浏览器打开，程序继续在后台运行。"""
    import run  # 复用 run.py 里“Edge/Chrome 应用模式”的打开方式
    run.open_window()


def main() -> None:
    if FROZEN:
        # 打包后的程序没有命令行窗口：输出写到数据目录的 app_log.txt，出错时发给 Claude
        f = open(log_file(), "a", encoding="utf-8", buffering=1)
        sys.stdout = sys.stderr = f
        print(f"\n==== {time.strftime('%Y-%m-%d %H:%M:%S')} 启动 ====")

    if running_from_archive():
        show_error("请不要在压缩软件里直接打开程序。\n\n"
                   "推荐：运行安装程序 AIMind-Setup.exe 安装后，从桌面或开始菜单打开。\n"
                   "或者先把整个 AIMind 文件夹解压出来（比如解压到 D:\\AIMind），再双击里面的 AIMind.exe。")
        sys.exit(1)

    already = port_busy() and is_ours(PORT)
    if not already:
        start_server()   # 后台启动服务，启动动画播放的同时就准备好了
    if PORT_MOVED:
        threading.Thread(target=notify_port_moved, daemon=True).start()

    if open_window():
        os._exit(0)   # 关掉窗口 = 退出程序

    if not wait_ready():
        show_error(friendly_error(SERVER_ERROR[0] if SERVER_ERROR else None))
        sys.exit(1)
    browser_fallback()
    if already:
        return
    # 没有窗口时一直在后台运行；Windows 上可以在任务管理器里结束它
    while True:
        time.sleep(3600)


if __name__ == "__main__":
    if FROZEN:
        import multiprocessing
        multiprocessing.freeze_support()
    main()
