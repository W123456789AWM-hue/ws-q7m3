"""把白底的 logo 动画做成启动动画：透明背景、60 帧、下面加“特别鸣谢”。

用法：python packaging/make_splash.py <原视频.mp4> [输出目录]
需要：ffmpeg（在 PATH 里）、numpy、pillow

输出：
  splash_60fps.webm   VP9 透明视频（浏览器 / 剪映等能直接用）
  splash_60fps.mov    ProRes 4444 透明视频（Premiere / Final Cut / AE 用）
  splash.webp         动态 WebP（透明、60 帧，缩小到 1000 宽）—— 程序启动动画用这个，
                      复制到 aimind/web/static/splash.webp
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

SRC_W, SRC_H = 1920, 1080
FPS = 60
# 内容范围（原视频里 logo 占的区域，四周留 40 像素）
X0, X1, Y0, Y1 = 217, 1693, 316, 728
TEXT_H = 150                      # 下方鸣谢文字区的高度
RED = (203, 18, 31)               # 从 logo 取的颜色
INK = (16, 16, 24)
CREDIT = [("特别鸣谢", RED), ("　则阳老师 & Claude", INK)]
FONT = "C:/Windows/Fonts/msyhbd.ttc" if sys.platform == "win32" else "/System/Library/Fonts/PingFang.ttc"
TEXT_IN = (4.6, 5.4)              # 文字淡入的时间段（秒）：logo 刚拼完整的时候
APP_WIDTH = 1000                  # 程序里用的 WebP 宽度


def frames_60fps(src: str):
    """先在白底上补帧到 60fps（运动补偿插帧，比简单混合清楚），再逐帧读出来"""
    vf = (f"minterpolate=fps={FPS}:mi_mode=mci:mc_mode=aobmc:me_mode=bidir:vsbmc=1,"
          f"crop={X1 - X0}:{Y1 - Y0}:{X0}:{Y0}")
    p = subprocess.Popen(["ffmpeg", "-v", "error", "-i", src, "-vf", vf, "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                         stdout=subprocess.PIPE)
    size = (X1 - X0) * (Y1 - Y0) * 3
    while True:
        buf = p.stdout.read(size)
        if len(buf) < size:
            break
        yield np.frombuffer(buf, np.uint8).reshape(Y1 - Y0, X1 - X0, 3)
    p.wait()


def white_to_alpha(rgb: np.ndarray) -> np.ndarray:
    """“颜色转透明”：白色变全透明，浅灰变半透明，边缘的抗锯齿保留下来，不会有白边"""
    c = rgb.astype(np.float32) / 255
    a = (1 - c).max(-1)
    a = np.clip((a - 0.02) / 0.98, 0, 1)            # 压缩噪点造成的极淡底色直接去掉
    safe = np.maximum(a, 1e-4)[..., None]
    col = np.clip(1 - (1 - c) / safe, 0, 1)
    out = np.dstack([col * 255, a * 255]).round().astype(np.uint8)
    out[a == 0] = 0
    return out


def credit_layer(width: int) -> Image.Image:
    font = ImageFont.truetype(FONT, 58)
    d = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    widths = [d.textlength(t, font=font) for t, _ in CREDIT]
    img = Image.new("RGBA", (width, TEXT_H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    x = (width - sum(widths)) / 2
    for (t, color), w in zip(CREDIT, widths):
        draw.text((x, TEXT_H / 2), t, font=font, fill=color + (255,), anchor="lm")
        x += w
    # 细细的白色描边光晕：放在深色桌面上也看得清
    halo = img.split()[3].filter(ImageFilter.MaxFilter(5)).filter(ImageFilter.GaussianBlur(3))
    glow = Image.new("RGBA", img.size, (255, 255, 255, 0))
    glow.putalpha(halo.point(lambda v: int(v * 0.55)))
    return Image.alpha_composite(glow, img)


def ease(t: float) -> float:
    t = min(max(t, 0.0), 1.0)
    return 1 - (1 - t) ** 3


def main() -> None:
    src = sys.argv[1]
    out = Path(sys.argv[2] if len(sys.argv) > 2 else "splash_out")
    tmp = out / "frames"
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    w, h = X1 - X0, Y1 - Y0
    credit = credit_layer(w)
    n = 0
    for i, rgb in enumerate(frames_60fps(src)):
        canvas = Image.new("RGBA", (w, h + TEXT_H), (0, 0, 0, 0))
        canvas.paste(Image.fromarray(white_to_alpha(rgb), "RGBA"), (0, 0))
        k = ease((i / FPS - TEXT_IN[0]) / (TEXT_IN[1] - TEXT_IN[0]))
        if k > 0:
            layer = credit.copy()
            layer.putalpha(layer.split()[3].point(lambda v, k=k: int(v * k)))
            canvas.alpha_composite(layer, (0, int(h - 30 + 24 * (1 - k))))   # 从下往上轻轻浮出来
        canvas.save(tmp / f"f{i:04d}.png", compress_level=1)
        n += 1
    print(f"{n} 帧，{n / FPS:.2f} 秒，{w}x{h + TEXT_H}")

    pat = str(tmp / "f%04d.png")
    def run(*a):
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-framerate", str(FPS), "-i", pat, *a], check=True)

    run("-c:v", "libvpx-vp9", "-pix_fmt", "yuva420p", "-b:v", "0", "-crf", "24", "-row-mt", "1",
        "-auto-alt-ref", "0", str(out / "splash_60fps.webm"))
    run("-c:v", "prores_ks", "-profile:v", "4444", "-pix_fmt", "yuva444p10le", "-vendor", "apl0",
        str(out / "splash_60fps.mov"))
    run("-vf", f"scale={APP_WIDTH}:-1:flags=lanczos", "-c:v", "libwebp_anim", "-lossless", "0", "-quality", "85",
        "-loop", "1", "-pix_fmt", "yuva420p", str(out / "splash.webp"))
    Image.open(tmp / f"f{n - 1:04d}.png").save(out / "last_frame.png")
    for f in ("splash_60fps.webm", "splash_60fps.mov", "splash.webp"):
        print(f, f"{(out / f).stat().st_size / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
