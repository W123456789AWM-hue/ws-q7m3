"""音频处理：切句（vad）、录音文件（wavstore）、电脑麦克风（mic）、ADPCM 解码（adpcm）"""
from .vad import SR, Segmenter, Utterance, pcm_to_wav_bytes, read_wav_16k  # noqa: F401
