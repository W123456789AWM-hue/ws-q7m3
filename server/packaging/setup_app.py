"""Windows 安装程序 AIMind-Setup.exe（中文界面，和主程序同一套科技风）

- 装到 %LOCALAPPDATA%\\Programs\\AIMind（路径短、不需要管理员权限），也可以换位置
- 开始菜单快捷方式；可选桌面快捷方式、开机自启
- 在「设置 → 应用」里能卸载（卸载不删录音和复盘数据：它们在 %APPDATA%\\AIMind）
- 覆盖安装 = 升级：先关掉正在运行的旧版本

打包：packaging/build_windows.ps1 会把主程序压成 payload.zip，再用 packaging/setup.spec 打成单个 exe。
测试用命令行（不弹界面）：AIMind-Setup.exe --silent --dir D:\\x\\AIMind [--no-shortcuts]
"""
from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess
import sys
import threading
import winreg
import zipfile
from pathlib import Path

APP_NAME = "AI 录音思考助手"
EXE = "AIMind.exe"
VERSION = "0.9.0"
PUBLISHER = "AI Mind"
REG_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\AIMind"
NO_WINDOW = 0x08000000
LOCAL = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
DEFAULT_DIR = LOCAL / "Programs" / "AIMind"
DATA_DIR = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming") / "AIMind"


def res(name: str) -> Path:
    base = getattr(sys, "_MEIPASS", None) or Path(__file__).resolve().parent
    return Path(base) / name


def _shell_folder(name: str) -> Path:
    """桌面 / 开始菜单 / 启动 文件夹的真实位置（桌面可能被 OneDrive 挪走了）"""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders") as k:
            return Path(os.path.expandvars(winreg.QueryValueEx(k, name)[0]))
    except OSError:
        fallback = {"Desktop": Path.home() / "Desktop",
                    "Programs": Path(os.environ["APPDATA"]) / r"Microsoft\Windows\Start Menu\Programs",
                    "Startup": Path(os.environ["APPDATA"]) / r"Microsoft\Windows\Start Menu\Programs\Startup"}
        return fallback[name]


def _ps(script: str) -> None:
    """运行一小段 PowerShell（用 -EncodedCommand 传，中文路径不会乱码）"""
    enc = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-EncodedCommand", enc],
                   creationflags=NO_WINDOW, check=False, capture_output=True)


def _q(p) -> str:
    return "'" + str(p).replace("'", "''") + "'"


def make_shortcut(lnk: Path, target: Path) -> None:
    lnk.parent.mkdir(parents=True, exist_ok=True)
    _ps(f"$s=(New-Object -ComObject WScript.Shell).CreateShortcut({_q(lnk)});"
        f"$s.TargetPath={_q(target)};$s.WorkingDirectory={_q(target.parent)};"
        f"$s.IconLocation={_q(str(target) + ',0')};$s.Description={_q(APP_NAME)};$s.Save()")


def installed_dir() -> Path | None:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_KEY) as k:
            return Path(winreg.QueryValueEx(k, "InstallLocation")[0])
    except OSError:
        return None


def installed_version() -> str:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_KEY) as k:
            return winreg.QueryValueEx(k, "DisplayVersion")[0]
    except OSError:
        return ""


def stop_running() -> None:
    """关掉正在运行的 AIMind（升级时文件被占用会装不上）"""
    subprocess.run(["taskkill", "/F", "/IM", EXE], creationflags=NO_WINDOW, check=False, capture_output=True)


UNINSTALL_PS1 = r"""# AI 录音思考助手 卸载脚本（安装程序自动生成）
$ErrorActionPreference = 'SilentlyContinue'
Add-Type -AssemblyName System.Windows.Forms
$dir = __DIR__
$r = if ($env:AIMIND_UNINSTALL_QUIET) { 'Yes' } else { [System.Windows.Forms.MessageBox]::Show("确定要卸载「AI 录音思考助手」吗？`n`n你的录音、复盘和设置保存在：`n$env:APPDATA\AIMind`n卸载不会删除它们（以后重新安装还能接着用）。", '卸载 AI 录音思考助手', 'YesNo', 'Question') }
if ($r -ne 'Yes') { exit 1 }
Set-Location $env:TEMP
Get-Process -Name AIMind | Where-Object { $_.Path -and $_.Path.StartsWith($dir, [StringComparison]::OrdinalIgnoreCase) } | Stop-Process -Force
Start-Sleep -Milliseconds 800
foreach ($l in @(__LINKS__)) { Remove-Item -LiteralPath $l -Force }
Remove-Item -LiteralPath 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\AIMind' -Recurse -Force
Remove-Item -LiteralPath $dir -Recurse -Force
if (-not $env:AIMIND_UNINSTALL_QUIET) { [System.Windows.Forms.MessageBox]::Show('已卸载。', '卸载 AI 录音思考助手') | Out-Null }
"""


def install(target: Path, desktop: bool = True, startmenu: bool = True, autostart: bool = False,
            progress=lambda pct, msg: None) -> None:
    target = Path(target)
    if len(str(target)) > 150:
        raise RuntimeError("安装位置的路径太长了，请换一个短一点的文件夹（比如 D:\\AIMind）")
    payload = res("payload.zip")
    if not payload.exists():
        raise RuntimeError("安装包不完整（缺少 payload.zip），请重新下载安装程序")

    progress(2, "正在关闭正在运行的旧版本…")
    stop_running()

    if target.exists() and any(target.iterdir()):
        if not (target / EXE).exists():
            raise RuntimeError(f"「{target}」里已经有别的文件。为了不误删你的东西，请选一个空文件夹或新文件夹")
        progress(5, "正在移除旧版本的程序文件（数据不受影响）…")
        for p in target.iterdir():
            try:
                shutil.rmtree(p) if p.is_dir() else p.unlink()
            except OSError as e:
                raise RuntimeError(f"旧版本的文件删不掉（{p.name}）：{e}。请先关闭程序再重试") from e
    target.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(payload) as z:
        items = [i for i in z.infolist() if not i.is_dir()]
        total = sum(i.file_size for i in items) or 1
        done = 0
        for n, i in enumerate(items):
            rel = Path(*Path(i.filename).parts[1:])        # 去掉压缩包里最外层的 AIMind/
            dst = target / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            with z.open(i) as src, open(dst, "wb") as out:
                shutil.copyfileobj(src, out, 1 << 20)
            done += i.file_size
            if n % 20 == 0:
                progress(8 + int(84 * done / total), f"正在复制程序文件… {rel.name}")

    progress(93, "正在创建快捷方式…")
    exe = target / EXE
    links = []
    if startmenu:
        links.append(_shell_folder("Programs") / f"{APP_NAME}.lnk")
    if desktop:
        links.append(_shell_folder("Desktop") / f"{APP_NAME}.lnk")
    if autostart:
        links.append(_shell_folder("Startup") / f"{APP_NAME}.lnk")
    for lnk in links:
        make_shortcut(lnk, exe)

    progress(97, "正在登记到「设置 → 应用」…")
    ps1 = target / "uninstall.ps1"
    body = UNINSTALL_PS1.replace("__DIR__", _q(target)).replace("__LINKS__", ",".join(_q(x) for x in links) or "''")
    ps1.write_text(body, encoding="utf-8-sig")          # 带 BOM：Windows PowerShell 5.1 才认得中文
    size_kb = sum(f.stat().st_size for f in target.rglob("*") if f.is_file()) // 1024
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, REG_KEY) as k:
        for name, kind, val in [
            ("DisplayName", winreg.REG_SZ, APP_NAME), ("DisplayVersion", winreg.REG_SZ, VERSION),
            ("Publisher", winreg.REG_SZ, PUBLISHER), ("InstallLocation", winreg.REG_SZ, str(target)),
            ("DisplayIcon", winreg.REG_SZ, f"{exe},0"),
            ("UninstallString", winreg.REG_SZ,
             f'powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "{ps1}"'),
            ("NoModify", winreg.REG_DWORD, 1), ("NoRepair", winreg.REG_DWORD, 1),
            ("EstimatedSize", winreg.REG_DWORD, size_kb)]:
            winreg.SetValueEx(k, name, 0, kind, val)
    progress(100, "安装完成")


# ======================= 界面 =======================
class Api:
    """给安装界面（setup_ui.html）调用"""

    def __init__(self):
        self._window = None
        self._target = installed_dir() or DEFAULT_DIR

    def info(self):
        size = res("payload.zip").stat().st_size if res("payload.zip").exists() else 0
        return {"dir": str(self._target), "version": VERSION, "old": installed_version(),
                "data": str(DATA_DIR), "size_mb": round(size * 2.2 / 1e6)}

    def choose(self):
        import webview
        kind = getattr(getattr(webview, "FileDialog", None), "FOLDER", None) or webview.FOLDER_DIALOG
        r = self._window.create_file_dialog(kind, directory=str(self._target.parent))
        if r:
            p = Path(r[0] if isinstance(r, (list, tuple)) else r)
            self._target = p if p.name.lower() == "aimind" else p / "AIMind"
        return str(self._target)

    def install(self, opts):
        def prog(pct, msg):
            try:
                self._window.evaluate_js(f"progress({int(pct)}, {json.dumps(msg, ensure_ascii=False)})")
            except Exception:
                pass
        try:
            install(self._target, bool(opts.get("desktop")), bool(opts.get("startmenu", True)),
                    bool(opts.get("autostart")), prog)
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "msg": str(e)}

    def launch(self):
        exe = self._target / EXE
        subprocess.Popen([str(exe)], cwd=str(self._target), close_fds=True)
        threading.Timer(0.3, self.close).start()

    def close(self):
        try:
            self._window.destroy()
        except Exception:
            pass


def gui() -> None:
    import webview
    api = Api()
    api._window = webview.create_window(f"安装 {APP_NAME}", str(res("setup_ui.html")), js_api=api,
                                        width=720, height=500, resizable=False, background_color="#080b12")
    webview.start()


def main() -> None:
    args = sys.argv[1:]
    if "--silent" in args:
        target = Path(args[args.index("--dir") + 1]) if "--dir" in args else DEFAULT_DIR
        no_links = "--no-shortcuts" in args
        # 窗口程序没有控制台：进度写到 %TEMP%\AIMind-Setup.log
        log = open(Path(os.environ.get("TEMP", ".")) / "AIMind-Setup.log", "w", encoding="utf-8")
        try:
            install(target, desktop=not no_links, startmenu=not no_links,
                    progress=lambda p, m: log.write(f"{p:3d}% {m}\n"))
            log.write("OK\n")
        except Exception as e:
            log.write(f"安装失败：{e}\n")
            sys.exit(1)
        finally:
            log.close()
        return
    try:
        gui()
    except Exception as e:     # 很老的 Windows 没有 WebView2：退回到最简单的确认框
        import ctypes
        ok = ctypes.windll.user32.MessageBoxW(None, f"安装「{APP_NAME}」到：\n{DEFAULT_DIR}\n\n（界面组件加载失败：{e}）",
                                              f"安装 {APP_NAME}", 0x41)
        if ok == 1:
            install(DEFAULT_DIR)
            ctypes.windll.user32.MessageBoxW(None, "安装完成，可以从桌面或开始菜单打开。", f"安装 {APP_NAME}", 0x40)


if __name__ == "__main__":
    main()
