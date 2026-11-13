"""Windows 上的透明启动动画：用系统的“分层窗口”（UpdateLayeredWindow）逐帧播放 splash.webp。

为什么不用网页窗口：pywebview 在 Windows 上只能让网页背景透明，外面的窗口还是不透明的（会露出灰底）；
分层窗口支持逐像素透明，logo 边缘的半透明也能正确显示，不会有白边/灰边。

play(path) 会阻塞到动画放完（或者用户点一下 / 按任意键跳过），然后返回。只依赖 ctypes、Pillow、numpy。
"""
from __future__ import annotations

import ctypes
import threading
import time
from ctypes import wintypes as wt

from PIL import Image

user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

WS_POPUP = 0x80000000
WS_EX_LAYERED, WS_EX_TOPMOST, WS_EX_TOOLWINDOW = 0x80000, 0x8, 0x80
WM_DESTROY, WM_KEYDOWN, WM_LBUTTONDOWN, WM_RBUTTONDOWN = 0x0002, 0x0100, 0x0201, 0x0204
PM_REMOVE, ULW_ALPHA, AC_SRC_OVER, AC_SRC_ALPHA = 1, 2, 0, 1
SW_SHOWNOACTIVATE, IDC_HAND = 4, 32649

LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM)


class WNDCLASSEXW(ctypes.Structure):
    _fields_ = [("cbSize", wt.UINT), ("style", wt.UINT), ("lpfnWndProc", WNDPROC), ("cbClsExtra", ctypes.c_int),
                ("cbWndExtra", ctypes.c_int), ("hInstance", wt.HINSTANCE), ("hIcon", wt.HICON),
                ("hCursor", wt.HANDLE), ("hbrBackground", wt.HBRUSH), ("lpszMenuName", wt.LPCWSTR),
                ("lpszClassName", wt.LPCWSTR), ("hIconSm", wt.HICON)]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wt.DWORD), ("biWidth", wt.LONG), ("biHeight", wt.LONG), ("biPlanes", wt.WORD),
                ("biBitCount", wt.WORD), ("biCompression", wt.DWORD), ("biSizeImage", wt.DWORD),
                ("biXPelsPerMeter", wt.LONG), ("biYPelsPerMeter", wt.LONG), ("biClrUsed", wt.DWORD),
                ("biClrImportant", wt.DWORD)]


class BLENDFUNCTION(ctypes.Structure):
    _fields_ = [("BlendOp", ctypes.c_ubyte), ("BlendFlags", ctypes.c_ubyte),
                ("SourceConstantAlpha", ctypes.c_ubyte), ("AlphaFormat", ctypes.c_ubyte)]


user32.DefWindowProcW.restype = LRESULT
user32.DefWindowProcW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
user32.CreateWindowExW.restype = wt.HWND
user32.CreateWindowExW.argtypes = [wt.DWORD, wt.LPCWSTR, wt.LPCWSTR, wt.DWORD, ctypes.c_int, ctypes.c_int,
                                   ctypes.c_int, ctypes.c_int, wt.HWND, wt.HMENU, wt.HINSTANCE, wt.LPVOID]
user32.UpdateLayeredWindow.argtypes = [wt.HWND, wt.HDC, ctypes.POINTER(wt.POINT), ctypes.POINTER(wt.SIZE), wt.HDC,
                                       ctypes.POINTER(wt.POINT), wt.COLORREF, ctypes.POINTER(BLENDFUNCTION), wt.DWORD]
user32.GetDC.restype = wt.HDC
user32.GetDC.argtypes = [wt.HWND]
user32.ReleaseDC.argtypes = [wt.HWND, wt.HDC]
user32.ShowWindow.argtypes = [wt.HWND, ctypes.c_int]
user32.DestroyWindow.argtypes = [wt.HWND]
user32.UnregisterClassW.argtypes = [wt.LPCWSTR, wt.HINSTANCE]
user32.TranslateMessage.argtypes = [ctypes.POINTER(wt.MSG)]
user32.DispatchMessageW.argtypes = [ctypes.POINTER(wt.MSG)]
gdi32.CreateCompatibleDC.argtypes = [wt.HDC]
user32.LoadCursorW.restype = wt.HANDLE
user32.LoadCursorW.argtypes = [wt.HINSTANCE, wt.LPVOID]
user32.PeekMessageW.argtypes = [ctypes.POINTER(wt.MSG), wt.HWND, wt.UINT, wt.UINT, wt.UINT]
kernel32.GetModuleHandleW.restype = wt.HMODULE
gdi32.CreateCompatibleDC.restype = wt.HDC
gdi32.CreateDIBSection.restype = wt.HBITMAP
gdi32.CreateDIBSection.argtypes = [wt.HDC, ctypes.POINTER(BITMAPINFOHEADER), wt.UINT,
                                   ctypes.POINTER(ctypes.c_void_p), wt.HANDLE, wt.DWORD]
gdi32.SelectObject.restype = wt.HGDIOBJ
gdi32.SelectObject.argtypes = [wt.HDC, wt.HGDIOBJ]
gdi32.DeleteObject.argtypes = [wt.HGDIOBJ]
gdi32.DeleteDC.argtypes = [wt.HDC]


def _screen_scale() -> float:
    try:
        user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))   # 按显示器 DPI 显示，画面清晰
    except Exception:
        pass
    try:
        return user32.GetDpiForSystem() / 96
    except Exception:
        return 1.0


def _frames(path: str, width: int):
    """逐帧解码动态 WebP，转成窗口要的“预乘透明度 BGRA”字节（全部用 Pillow 的 C 实现，一帧几毫秒）"""
    im = Image.open(path)
    for i in range(getattr(im, "n_frames", 1)):
        im.seek(i)
        f = im.convert("RGBa")                       # RGBa = 已乘上透明度的 RGBA
        # 时长要在解码之后才读得到；静止不动的部分编码时会合并成一帧长帧
        dur = (im.info.get("duration") or 16.67) / 1000
        if f.width != width:
            f = f.resize((width, round(f.height * width / f.width)), Image.BILINEAR)
        r, g, b, a = f.split()
        yield Image.merge("RGBa", (b, g, r, a)).tobytes(), dur   # 窗口要 BGRA 顺序


_playing = threading.Lock()


def play(path: str, css_width: int = 760, fade: float = 0.3, speed: float = 1.0) -> None:
    """speed：播放速度倍数（设置里的「启动动画速度」），2 = 快一倍"""
    if not _playing.acquire(blocking=False):   # 设置里连点「预览」时不要叠着放
        return
    try:
        _play(path, css_width, fade, max(0.25, min(4.0, float(speed or 1))))
    finally:
        _playing.release()


def _play(path: str, css_width: int, fade: float, speed: float) -> None:
    scale = _screen_scale()
    with Image.open(path) as im:
        src_w, src_h = im.size
    w = min(src_w, round(css_width * scale))
    if src_w - w < src_w * 0.2:     # 差得不多就不缩放，省时间（窗口稍微大一点点）
        w = src_w
    h = round(src_h * w / src_w)

    state = {"skip": False}

    @WNDPROC
    def wndproc(hwnd, msg, wp, lp):
        if msg in (WM_LBUTTONDOWN, WM_RBUTTONDOWN, WM_KEYDOWN):
            state["skip"] = True
            return 0
        if msg == WM_DESTROY:
            return 0
        return user32.DefWindowProcW(hwnd, msg, wp, lp)

    hinst = kernel32.GetModuleHandleW(None)
    wc = WNDCLASSEXW(cbSize=ctypes.sizeof(WNDCLASSEXW), lpfnWndProc=wndproc, hInstance=hinst,
                     hCursor=user32.LoadCursorW(None, ctypes.c_void_p(IDC_HAND)), lpszClassName="AIMindSplash")
    user32.RegisterClassExW(ctypes.byref(wc))
    sw, sh = user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)
    x, y = (sw - w) // 2, (sh - h) // 2
    hwnd = user32.CreateWindowExW(WS_EX_LAYERED | WS_EX_TOPMOST | WS_EX_TOOLWINDOW, "AIMindSplash",
                                  "AI 录音思考助手", WS_POPUP, x, y, w, h, None, None, hinst, None)
    if not hwnd:
        raise OSError(f"创建启动动画窗口失败：{ctypes.get_last_error()}")

    screen_dc = user32.GetDC(None)
    mem_dc = gdi32.CreateCompatibleDC(screen_dc)
    bmi = BITMAPINFOHEADER(biSize=ctypes.sizeof(BITMAPINFOHEADER), biWidth=w, biHeight=-h, biPlanes=1,
                           biBitCount=32, biCompression=0)
    bits = ctypes.c_void_p()
    dib = gdi32.CreateDIBSection(screen_dc, ctypes.byref(bmi), 0, ctypes.byref(bits), None, 0)
    old = gdi32.SelectObject(mem_dc, dib)
    buf = (ctypes.c_ubyte * (w * h * 4)).from_address(bits.value)
    pt, size, src = wt.POINT(x, y), wt.SIZE(w, h), wt.POINT(0, 0)
    blend = BLENDFUNCTION(AC_SRC_OVER, 0, 255, AC_SRC_ALPHA)

    def show(alpha: int = 255):
        blend.SourceConstantAlpha = alpha
        user32.UpdateLayeredWindow(hwnd, screen_dc, ctypes.byref(pt), ctypes.byref(size), mem_dc,
                                   ctypes.byref(src), 0, ctypes.byref(blend), ULW_ALPHA)

    msg = wt.MSG()

    def pump():
        while user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, PM_REMOVE):
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

    try:
        ctypes.WinDLL("winmm").timeBeginPeriod(1)   # 让 sleep 精确到 1 毫秒（默认 15 毫秒，60 帧会卡）
    except Exception:
        pass
    try:
        shown = False
        due = time.perf_counter()
        for frame, dur in _frames(path, w):
            dur /= speed
            now = time.perf_counter()
            if now > due + 0.05:          # 跟不上就丢帧，保证总时长不变
                due += dur
                continue
            ctypes.memmove(buf, frame, w * h * 4)
            while time.perf_counter() < due:
                pump()
                time.sleep(0.001)
            show()
            if not shown:
                user32.ShowWindow(hwnd, SW_SHOWNOACTIVATE)
                shown = True
            pump()
            if state["skip"]:
                break
            due += dur
        # 最后一帧（logo 拼完整 + 鸣谢）停留到动画结束，最后 fade 秒淡出
        while not state["skip"] and time.perf_counter() < due - fade:
            pump()
            time.sleep(0.005)
        t0 = time.perf_counter()
        while (k := (time.perf_counter() - t0) / fade) < 1:
            show(int(255 * (1 - k)))
            pump()
            time.sleep(0.008)
    finally:
        user32.ShowWindow(hwnd, 0)
        gdi32.SelectObject(mem_dc, old)
        gdi32.DeleteObject(dib)
        gdi32.DeleteDC(mem_dc)
        user32.ReleaseDC(None, screen_dc)
        user32.DestroyWindow(hwnd)
        user32.UnregisterClassW("AIMindSplash", hinst)


if __name__ == "__main__":
    import sys
    play(sys.argv[1])
