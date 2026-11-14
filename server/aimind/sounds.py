"""界面音效：用代码合成（不用任何外部素材），电脑端和手机端共用。

- click：按钮的轻点声，约 40 毫秒，柔和的“嗒”。
- splash：启动动画的音效，和 splash.webp 的画面对齐（时间点见 SPLASH_EVENTS）：
  彗星划过（呼的一声）→ 落点的星光 → 第二个元素出现的轻拨 → 蓄力 →
  标志拼合时的主和弦 + 低音 → 鸣谢文字出现时的一声轻响 → 余音。
  speed：和动画速度一致（2 = 快一倍），只改变事件的时间点，不改变音高。

电脑端运行时按设置的速度生成（几十毫秒）；手机端和网页用的固定文件由 packaging/make_sounds.py 生成。
"""
from __future__ import annotations

import io
import wave

import numpy as np

SR = 44100

# 启动动画里的时间点（秒，1 倍速）：由逐帧分析 splash.webp 得到
SPLASH_EVENTS = {
    "comet": (0.32, 1.35),     # 彗星从出现到落下
    "land": 1.30,              # 彗星落下
    "second": 1.75,            # 第二个元素出现
    "rise": (2.45, 3.45),      # 蓄力
    "reveal": 3.45,            # 标志拼合（画面变化最大的时刻）
    "thanks": 4.75,            # 鸣谢文字出现
}


def _t(n: int) -> np.ndarray:
    return np.arange(n) / SR


def _bell(freq: float, dur: float, amp: float = 1.0, bright: float = 1.0) -> np.ndarray:
    """钟 / 钢片琴一样的音色：几个泛音，越高的泛音衰减越快"""
    n = int(dur * SR)
    t = _t(n)
    out = np.zeros(n)
    for ratio, a, decay in ((1, 1.0, 1.0), (2.0, .42 * bright, 1.8), (3.0, .2 * bright, 2.8),
                            (4.16, .1 * bright, 4.0), (5.43, .05 * bright, 5.5)):
        f = freq * ratio
        if f > SR / 2.3:
            continue
        out += a * np.sin(2 * np.pi * f * t + ratio) * np.exp(-t * decay * 3.2 / dur)
    attack = np.minimum(1, t / 0.004)
    # 最后 25% 平滑地收到 0：不然声音在结尾被突然切断，会有“咔”的一声
    tail = np.clip((dur - t) / (dur * .25), 0, 1) ** 2
    return amp * out * attack * tail


def _noise_sweep(dur: float, f0: float, f1: float, env: np.ndarray | None = None, width: float = .35,
                 seed: int = 1) -> np.ndarray:
    """带通噪声，中心频率从 f0 滑到 f1（“呼”的一声）。用短时傅里叶变换逐帧滤波"""
    n = int(dur * SR)
    rng = np.random.default_rng(seed)
    x = rng.standard_normal(n + 4096)
    hop, win = 512, 2048
    w = np.hanning(win)
    out = np.zeros(len(x))
    norm = np.zeros(len(x))
    freqs = np.fft.rfftfreq(win, 1 / SR)
    frames = (len(x) - win) // hop + 1
    for i in range(frames):
        a = i * hop
        k = min(1.0, a / max(1, n))
        fc = f0 * (f1 / f0) ** k                     # 按对数滑动，听起来均匀
        band = np.exp(-0.5 * (np.log(np.maximum(freqs, 1) / fc) / width) ** 2)
        seg = np.fft.irfft(np.fft.rfft(x[a:a + win] * w) * band, win)
        out[a:a + win] += seg * w
        norm[a:a + win] += w * w
    out = (out / np.maximum(norm, 1e-6))[:n]
    out /= np.max(np.abs(out)) or 1
    return out * (env if env is not None else 1)


def _reverb(x: np.ndarray, seconds: float = 1.6, wet: float = .28, seed: int = 7) -> np.ndarray:
    """简单的混响：和一段指数衰减的噪声做卷积"""
    n = int(seconds * SR)
    t = _t(n)
    rng = np.random.default_rng(seed)
    ir = rng.standard_normal(n) * np.exp(-t * 6.9 / seconds)
    # 混响尾巴的高频衰减得快一点，听起来更暖
    spec = np.fft.rfft(ir)
    spec *= 1 / (1 + (np.fft.rfftfreq(n, 1 / SR) / 4500) ** 2)
    ir = np.fft.irfft(spec, n)
    ir[: int(.012 * SR)] = 0                         # 12 毫秒的预延迟
    ir /= np.sqrt(np.sum(ir ** 2)) or 1
    m = len(x) + n
    size = 1 << (m - 1).bit_length()
    y = np.fft.irfft(np.fft.rfft(x, size) * np.fft.rfft(ir, size), size)[:m]
    dry = np.concatenate([x, np.zeros(n)])
    return dry * (1 - wet * .5) + y * wet


def _place(buf: np.ndarray, sound: np.ndarray, at: float) -> None:
    a = int(at * SR)
    if a >= len(buf):
        return
    b = min(len(buf), a + len(sound))
    buf[a:b] += sound[: b - a]


def _wav(x: np.ndarray) -> bytes:
    pcm = (np.clip(x, -1, 1) * 32767).astype("<i2")
    bio = io.BytesIO()
    with wave.open(bio, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())
    return bio.getvalue()


def _finish(x: np.ndarray, peak: float) -> np.ndarray:
    fade = int(.01 * SR)
    x[:fade] *= np.linspace(0, 1, fade)
    x[-fade * 4:] *= np.linspace(1, 0, fade * 4)
    return x / (np.max(np.abs(x)) or 1) * peak


def click() -> np.ndarray:
    """按钮的轻点声：一个很短的高音“嗒” + 一点点触感噪声，峰值 -9dB（足够听见，不刺耳）"""
    n = int(.045 * SR)
    t = _t(n)
    tone = .7 * np.sin(2 * np.pi * 1750 * t) * np.exp(-t / .0065)
    tone += .25 * np.sin(2 * np.pi * 3500 * t + 1) * np.exp(-t / .0028)
    tone += .12 * np.sin(2 * np.pi * 880 * t) * np.exp(-t / .012)       # 一点点“体积感”
    rng = np.random.default_rng(3)
    tick = rng.standard_normal(n) * np.exp(-t / .0009) * .35
    tick = np.convolve(tick, np.ones(6) / 6, "same")                      # 磨掉最尖的高频
    x = (tone + tick) * np.minimum(1, t / .0008)
    return _finish(x, .35)


def splash(speed: float = 1.0) -> np.ndarray:
    """启动动画音效。speed 和动画速度一致"""
    s = 1 / max(.25, min(4.0, float(speed or 1)))
    ev = SPLASH_EVENTS
    end = ev["thanks"] * s + 2.6
    buf = np.zeros(int(end * SR))

    # 1. 彗星划过：带通噪声从低滑到高，先变大再变小
    c0, c1 = ev["comet"][0] * s, ev["comet"][1] * s
    dur = c1 - c0 + .35
    t = _t(int(dur * SR))
    env = np.sin(np.pi * np.clip(t / dur, 0, 1)) ** 1.6
    _place(buf, .55 * _noise_sweep(dur, 260, 3800, env, .32, seed=11), c0)

    # 底下一层很轻的低音铺底，从彗星出现一直延续到最后
    pad_len = end - c0
    t = _t(int(pad_len * SR))
    pad = sum(a * np.sin(2 * np.pi * f * t) for f, a in ((110, .5), (164.81, .32), (220, .18)))
    pad *= np.minimum(1, t / (1.2 * s)) * np.exp(-np.maximum(0, t - (ev["reveal"] - .32) * s) / 1.4)
    _place(buf, .1 * pad, c0)

    # 2. 彗星落下：几颗星光（很高、很轻的叮）
    for i, f in enumerate((1318.5, 1975.5, 2637.0)):
        _place(buf, _bell(f, .55, .16 - i * .03, .5), ev["land"] * s + i * .055)

    # 3. 第二个元素出现：一声轻拨
    _place(buf, _bell(880, .7, .22, .6), ev["second"] * s)
    _place(buf, _bell(659.25, .7, .12, .4), ev["second"] * s + .03)

    # 4. 蓄力：噪声从中频升到高频，越来越响，到标志拼合时停
    r0, r1 = ev["rise"][0] * s, ev["rise"][1] * s
    dur = max(.3, r1 - r0)
    t = _t(int(dur * SR))
    _place(buf, .3 * _noise_sweep(dur, 600, 7000, (t / dur) ** 2.2, .4, seed=21), r0)

    # 5. 标志拼合：低音“咚” + 主和弦（A 大调）+ 往上走的闪光琶音
    at = ev["reveal"] * s
    t = _t(int(1.2 * SR))
    f = 46 + 50 * np.exp(-t / .05)                                        # 音高快速下滑的低音
    boom = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t / .28)
    boom *= np.minimum(1, t / .003) * np.clip((1.2 - t) / .3, 0, 1)
    _place(buf, .6 * boom, at)
    for f, a in ((220, .32), (440, .5), (554.37, .36), (659.25, .34), (880, .24)):
        _place(buf, _bell(f, 2.8, a, .8), at + .008)
    for i, f in enumerate((659.25, 880, 1108.73, 1318.5, 1760)):
        _place(buf, _bell(f, 1.0, .13 - i * .012, .7), at + .16 * s + i * .1 * s)

    # 6. 鸣谢文字出现：一声干净的轻响
    _place(buf, _bell(1760, 1.6, .16, .5), ev["thanks"] * s)
    _place(buf, _bell(2217.46, 1.6, .07, .4), ev["thanks"] * s + .04)

    return _finish(_reverb(buf, 1.8, .3)[: int((end + .4) * SR)], .7)


def click_wav() -> bytes:
    return _wav(click())


def splash_wav(speed: float = 1.0) -> bytes:
    return _wav(splash(speed))
