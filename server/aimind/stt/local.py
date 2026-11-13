"""本地语音识别（不联网、不调用 AI）

- sensevoice：sherpa-onnx + SenseVoice，中文准、CPU 就很快（默认）
- whisper：faster-whisper，可用 NVIDIA 显卡跑 large-v3（可选，需另装）
"""
from __future__ import annotations

import os
import shutil
import tarfile
from pathlib import Path
from typing import Callable

import httpx
import numpy as np

from ..config import DATA_DIR

SV_NAME = "sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17"
SV_FILES = ["model.int8.onnx", "tokens.txt"]
SV_SOURCES = [  # 按顺序尝试；单文件下载，只需约 240MB
    "https://hf-mirror.com/csukuangfj/{name}/resolve/main/{file}",
    "https://huggingface.co/csukuangfj/{name}/resolve/main/{file}",
]
SV_GITHUB_TAR = ("https://github.com/k2-fsa/sherpa-onnx/releases/download/"
                 "asr-models/{name}.tar.bz2")  # 最后的备选：整包约 1GB
MODELS_DIR = DATA_DIR / "models"

Progress = Callable[[str], None]


PF_NAME = "sherpa-onnx-paraformer-zh-2023-09-14"


def model_dir(name: str = SV_NAME) -> Path:
    return MODELS_DIR / name


def model_ready(name: str = SV_NAME) -> bool:
    d = model_dir(name)
    return all((d / f).exists() and (d / f).stat().st_size > 1000 for f in SV_FILES)


def sv_dir() -> Path:
    return model_dir(SV_NAME)


def sv_ready() -> bool:
    return model_ready(SV_NAME)


def _stream(url: str, dst: Path, progress: Progress, label: str):
    """下载一个文件，支持断点续传（.part 文件留着，下次接着下）"""
    tmp = dst.with_suffix(dst.suffix + ".part")
    have = tmp.stat().st_size if tmp.exists() else 0
    headers = {"Range": f"bytes={have}-"} if have else {}
    with httpx.stream("GET", url, follow_redirects=True, headers=headers,
                      timeout=httpx.Timeout(60.0, connect=15.0)) as r:
        if r.status_code == 416:  # 之前其实已经下完了
            tmp.replace(dst)
            return
        if r.status_code not in (200, 206):
            raise RuntimeError(f"HTTP {r.status_code}")
        if r.status_code == 200:
            have = 0  # 服务器不支持续传，从头来
        total = int(r.headers.get("content-length") or 0)
        total = total + have if total else 0
        got, last = have, -1
        with open(tmp, "ab" if have else "wb") as f:
            for chunk in r.iter_bytes(1 << 20):
                f.write(chunk)
                got += len(chunk)
                pct = int(got * 100 / total) if total else -1
                if pct != last:
                    last = pct
                    progress(f"下载{label}：{pct}%（{got >> 20}/{total >> 20}MB）" if pct >= 0
                             else f"下载{label}：{got >> 20}MB")
        if total and got < total:
            raise RuntimeError("连接中断（下次会从断点继续）")
    tmp.replace(dst)


def download_model(name: str, progress: Progress) -> None:
    """下载一个 sherpa-onnx 模型（只要 model.int8.onnx 和 tokens.txt），多个源依次尝试"""
    if model_ready(name):
        return
    d = model_dir(name)
    d.mkdir(parents=True, exist_ok=True)
    errors = []
    for src in SV_SOURCES:
        host = src.split("/")[2]
        try:
            for f in SV_FILES:
                if not (d / f).exists():
                    _stream(src.format(name=name, file=f), d / f, progress,
                            f"识别模型 {f}（{host}）")
            if model_ready(name):
                progress("识别模型下载完成")
                return
        except Exception as e:
            errors.append(f"{host}: {e}")
            progress(f"{host} 下载失败，换下一个源…")
    # 备选：GitHub 整包
    try:
        tar = MODELS_DIR / f"{name}.tar.bz2"
        if not tar.exists():
            _stream(SV_GITHUB_TAR.format(name=name), tar, progress, "识别模型整包（GitHub）")
        progress("解压中…")
        with tarfile.open(tar, "r:bz2") as t:
            for m in t.getmembers():
                base = os.path.basename(m.name)
                if base in SV_FILES and m.isfile():
                    with t.extractfile(m) as src, open(d / base, "wb") as out:
                        shutil.copyfileobj(src, out)
        tar.unlink(missing_ok=True)
        if model_ready(name):
            progress("识别模型下载完成")
            return
    except Exception as e:
        errors.append(f"github: {e}")
    raise RuntimeError("识别模型下载失败：" + "；".join(errors) +
                       f"。可手动把 {', '.join(SV_FILES)} 放到 {d}")


def download_sensevoice(progress: Progress) -> None:
    download_model(SV_NAME, progress)


class Paraformer:
    """中文为主、夹英文单词时最稳；嘈杂时不容易整句认错语言。不带标点。"""

    def __init__(self, cfg: dict, progress: Progress):
        import sherpa_onnx
        download_model(PF_NAME, progress)
        progress("加载识别模型…")
        d = model_dir(PF_NAME)
        self.rec = sherpa_onnx.OfflineRecognizer.from_paraformer(
            paraformer=str(d / "model.int8.onnx"), tokens=str(d / "tokens.txt"),
            num_threads=max(1, min(8, (os.cpu_count() or 4) // 2)))
        progress("本地识别已就绪（Paraformer）")

    def transcribe(self, pcm: np.ndarray) -> str:
        s = self.rec.create_stream()
        s.accept_waveform(16000, pcm.astype(np.float32) / 32768.0)
        self.rec.decode_stream(s)
        return s.result.text.strip()


class SenseVoice:
    def __init__(self, cfg: dict, progress: Progress):
        import sherpa_onnx
        download_sensevoice(progress)
        progress("加载识别模型…")
        d = sv_dir()
        lang = (cfg.get("stt_language") or "").strip()
        self.rec = sherpa_onnx.OfflineRecognizer.from_sense_voice(
            model=str(d / "model.int8.onnx"), tokens=str(d / "tokens.txt"),
            num_threads=max(1, min(8, (os.cpu_count() or 4) // 2)),
            language=lang if lang in ("zh", "en", "ja", "ko", "yue") else "auto",
            use_itn=True)  # use_itn：自动加标点、数字转阿拉伯数字
        progress("本地识别已就绪（SenseVoice）")

    def transcribe(self, pcm: np.ndarray) -> str:
        s = self.rec.create_stream()
        s.accept_waveform(16000, pcm.astype(np.float32) / 32768.0)
        self.rec.decode_stream(s)
        return s.result.text.strip()


def _add_cuda_dlls():
    """Windows：让 CTranslate2 找到 pip 装的 CUDA 运行库（nvidia-cublas-cu12 / nvidia-cudnn-cu12）"""
    if os.name != "nt":
        return
    import site
    for sp in site.getsitepackages():
        for b in Path(sp, "nvidia").glob("*/bin"):
            try:
                os.add_dll_directory(str(b))
                os.environ["PATH"] = str(b) + os.pathsep + os.environ.get("PATH", "")
            except Exception:
                pass


def import_faster_whisper():
    """导入 faster-whisper。
    它的几个依赖在很新的 Python 版本上还没有现成的安装包（av、PyYAML、onnxruntime），
    而我们用到的功能（把 PCM 数据交给显卡识别、自己下载模型）根本用不到它们，
    所以缺哪个就放一个空壳顶替，让 faster-whisper 能正常加载。"""
    import importlib
    import sys
    import types
    for name in ("av", "yaml", "huggingface_hub"):
        try:
            importlib.import_module(name)
        except Exception:
            sys.modules[name] = types.ModuleType(name)
    import faster_whisper
    return faster_whisper


WHISPER_FILES = ["config.json", "preprocessor_config.json", "tokenizer.json",
                 "vocabulary.json", "model.bin"]
HF_HOSTS = ["https://hf-mirror.com", "https://huggingface.co"]


def whisper_repo(size: str) -> str:
    """模型名 → HuggingFace 仓库名（large-v3 → Systran/faster-whisper-large-v3）"""
    try:
        import_faster_whisper()
        from faster_whisper.utils import _MODELS
        if size in _MODELS:
            return _MODELS[size]
    except Exception:
        pass
    return size if "/" in size else f"Systran/faster-whisper-{size}"


def whisper_dir(size: str) -> Path:
    return MODELS_DIR / "whisper" / whisper_repo(size).replace("/", "--")


def whisper_ready(size: str) -> bool:
    d = whisper_dir(size)
    return (d / "model.bin").exists() and (d / "config.json").exists() \
        and (d / "tokenizer.json").exists()


def download_whisper(size: str, progress: Progress) -> Path:
    """自己下载 Whisper 模型（large-v3 约 3GB）：多个源依次尝试，支持断点续传"""
    d = whisper_dir(size)
    if whisper_ready(size):
        return d
    d.mkdir(parents=True, exist_ok=True)
    repo = whisper_repo(size)
    errors = []
    for host in HF_HOSTS:
        name = host.split("/")[2]
        try:
            for f in WHISPER_FILES:
                if (d / f).exists():
                    continue
                try:
                    _stream(f"{host}/{repo}/resolve/main/{f}", d / f, progress,
                            f" Whisper {f}（{name}）")
                except RuntimeError as e:
                    # 有的模型没有 preprocessor_config.json / vocabulary.json，可以没有
                    if "404" in str(e) and f in ("preprocessor_config.json", "vocabulary.json"):
                        continue
                    raise
            if whisper_ready(size):
                progress("Whisper 模型下载完成")
                return d
        except Exception as e:
            errors.append(f"{name}: {e}")
            progress(f"{name} 下载失败，换下一个源…")
    raise RuntimeError("Whisper 模型下载失败：" + "；".join(errors) +
                       f"。可手动把模型文件放到 {d}")


class LocalWhisper:
    """Whisper large-v3，用 NVIDIA 显卡跑。准确度最高，尤其是中英混说。"""

    def __init__(self, cfg: dict, progress: Progress):
        _add_cuda_dlls()
        try:
            WhisperModel = import_faster_whisper().WhisperModel
        except ImportError:
            raise RuntimeError("还没安装 Whisper：请先关闭程序，双击 install_whisper_gpu.bat")
        self.cfg = cfg
        size = cfg.get("local_whisper_model") or "large-v3"
        self.lang = (cfg.get("stt_language") or "").strip() or None
        path = str(download_whisper(size, progress))
        dev = cfg.get("whisper_device", "auto")
        self.m = None
        errors = []
        if dev in ("auto", "cuda"):
            # 不同显卡/驱动支持的精度不一样：依次试，并且真的跑一小段确认能用
            for ct in ("float16", "int8_float16", "float32"):
                try:
                    progress(f"加载 Whisper {size}（显卡，{ct}）…")
                    m = WhisperModel(path, device="cuda", compute_type=ct)
                    self.m = m
                    self._run(np.zeros(16000, dtype=np.int16), "")  # 自检
                    self.device = f"显卡 {ct}"
                    break
                except Exception as e:
                    self.m = None
                    errors.append(f"{ct}: {str(e)[:160]}")
        if self.m is None:
            if dev != "cpu":
                # large-v3 在 CPU 上比说话还慢，会越积越多，所以不自动退到 CPU
                raise RuntimeError("显卡跑不起来 Whisper：" + "；".join(errors))
            progress(f"加载 Whisper {size}（CPU，很慢）…")
            self.m = WhisperModel(path, device="cpu", compute_type="int8")
            self.device = "CPU"
        progress(f"本地识别已就绪（Whisper {size}，{self.device}）")

    def _run(self, pcm: np.ndarray, prev: str) -> str:
        hint = None
        if self.lang == "zh":
            hint = "以下是普通话的句子，可能夹杂英文单词。" + (prev[-80:] if prev else "")
        elif prev:
            hint = prev[-80:]
        glossary = (self.cfg.get("glossary") or "").strip()
        segs, _ = self.m.transcribe(
            pcm.astype(np.float32) / 32768.0, language=self.lang, beam_size=5,
            vad_filter=False, condition_on_previous_text=False, without_timestamps=True,
            initial_prompt=hint, hotwords=glossary or None)
        out = []
        for s in segs:
            # 丢掉“没人说话却硬编出来”的内容（Whisper 在噪音上容易幻觉）
            if s.no_speech_prob > 0.6 and s.avg_logprob < -1.0:
                continue
            if s.compression_ratio > 2.6:
                continue
            out.append(s.text)
        return "".join(out).strip()

    def transcribe(self, pcm: np.ndarray, prev: str = "") -> str:
        return self._run(pcm, prev)
