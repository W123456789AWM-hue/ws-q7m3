"""配置：保存在 data/config.json，界面里可以修改。

新增配置项时只需要在 DEFAULTS 里加一行（带注释），load()/save() 会自动处理。"""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path

PKG_DIR = Path(__file__).resolve().parent
# 数据目录：默认 server/data；测试或多开时可以用环境变量 AIMIND_DATA 指定
DATA_DIR = Path(os.environ.get("AIMIND_DATA") or PKG_DIR.parent / "data")
CONFIG_FILE = DATA_DIR / "config.json"

DEFAULTS: dict = {
    # ---- 语音识别（默认本地，不联网）----
    "stt_provider": "sensevoice",     # sensevoice / paraformer / whisper（都是本地）；api = 在线接口
    "stt_language": "zh",             # zh / en / ja / ko / yue；留空 = 自动
    "local_whisper_model": "large-v3",   # large-v3（最准）/ large-v3-turbo（快很多，略逊）
    "whisper_device": "auto",         # auto / cuda / cpu
    "stt_base_url": "https://api.openai.com/v1",
    "stt_api_key": "",
    "stt_model": "whisper-1",
    # ---- AI 听录音复盘（默认）----
    "review_input": "audio",          # audio = AI 直接听录音；text = 先本地识别成文字再复盘（旧方式）
    "audio_vendor": "openai",         # 听录音用哪家：openai（含其他兼容接口）/ google（Gemini）
    "google_api_key": "",             # Google AI Studio 的 API Key（听录音、文字 AI 选 Google 时共用）
    "audio_base_url": "https://api.openai.com/v1",
    "audio_api_key": "",
    "audio_model": "gpt-audio-1.5",
    "audio_max_min": 8,               # 每次最多发多少分钟录音给 AI（太长会分批）
    "audio_trim_silence": True,       # 发给 AI 前去掉每句前后多余的静音（按时长计费，省钱，不影响内容）
    "realtime_min_sec": 5,            # 实时复盘：一段少于多少秒语音先攒着
    "review_min_sec": 30,             # 周期复盘：新语音少于多少秒就跳过这一轮
    # ---- AI 复盘 ----
    "llm_provider": "openai",         # openai = OpenAI 兼容接口（含本机 Ollama）；anthropic = Claude；google = Gemini
    "llm_base_url": "https://api.siliconflow.com/v1",
    "llm_api_key": "",
    "llm_model": "",
    "about_me": "",                   # 关于我：身份、目标、在忙什么，帮 AI 推断潜在需求
    "extra_instructions": "",
    "glossary": "",                   # 我常说的词、专有名词、英文术语
    "review_mode": "interval",        # interval = 按自定义周期复盘；realtime = 实时复盘（每说完一段就复盘）
    "realtime_min_chars": 30,         # 实时模式：一段少于多少字就先攒着，并入下一段一起复盘
    "review_interval_min": 30,        # 每隔多少分钟复盘一次
    "review_min_chars": 200,          # 新内容少于多少字就跳过这次（没怎么说话时不浪费调用）
    # ---- 大复盘（总结）----
    "session_review": "end",          # end = 一场录音结束时做整场总复盘；off = 不做
    "daily_review_time": "23:00",     # 每天几点做日复盘；留空 = 不做
    "monthly_review": "month_end",    # month_end = 当月最后一天；next_month = 下个月 1 号；off = 不做
    "yearly_review": "year_end",      # year_end = 12 月 31 日；next_year = 次年 1 月 1 日；off = 不做
    "period_review_time": "23:30",    # 月复盘、年复盘在那天几点做（排在日复盘之后，能用上当天的日复盘）
    # ---- 分段（只影响左侧转写的排版和复盘里的段落划分）----
    "pause_close_sec": 15,
    "max_paragraph_sec": 180,
    # ---- 录音 ----
    "mic_device": None,
    "vad_margin_db": 10,
    "vad_min_db": -50,
    # ---- 存储 ----
    "nas_dir": "",                    # NAS 共享目录，例如 \\\\192.168.1.10\\recordings 或 Z:\\recordings
    "save_audio": True,
    "server_token": "",               # 手机连接口令（首次启动自动生成）
    "server_port": 8765,              # 端口；8765 被别的程序占用时会自动换一个并记在这里
    "phone_idle_stop_min": 30,        # 所有设备都多久没传录音，就自动收尾这一场
    # ---- 在线更新 ----
    "update_auto_check": True,        # 自动检查新版本（启动时 + 每 6 小时）
    "update_mirror": "",              # 下载镜像前缀，比如 https://ghproxy.net/（连不上 GitHub 时用）
    "update_manifest_url": "",        # 留空 = 官方发布地址；测试 / 自建发布时才填
    # ---- 桌面程序 ----
    "splash_enabled": True,           # 启动时播放启动动画
    "splash_speed": 1.0,              # 启动动画速度：0.5 = 慢一倍，2 = 快一倍
    "splash_sound": True,             # 启动动画的音效
    "splash_sound_volume": 1.0,       # 启动音效音量：0.3 很轻 / 0.6 轻 / 1 标准 / 1.4 响
    "sound_clicks": True,             # 界面按钮的点击音效
    "click_volume": 1.0,              # 按钮音效音量（同上）
    "config_version": 3,
}

_lock = threading.Lock()


def load() -> dict:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    cfg = dict(DEFAULTS)
    if CONFIG_FILE.exists():
        try:
            raw = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            if raw.get("config_version", 1) < 2:   # 旧版默认在线识别，升级后改为本地识别
                raw["stt_provider"] = "sensevoice"
            if raw.get("config_version", 1) < 3:   # v0.8 起默认改为 AI 直接听录音
                raw["review_input"] = "audio"
            raw["config_version"] = 3
            cfg.update(raw)
        except Exception:
            pass
    if not cfg.get("server_token"):
        import secrets
        cfg["server_token"] = secrets.token_hex(4)
        try:
            CONFIG_FILE.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass
    return cfg


def save(cfg: dict) -> dict:
    with _lock:
        merged = load()
        for k in DEFAULTS:
            if k in cfg:
                merged[k] = cfg[k]
        from .fsutil import write_atomic  # 放这里：避免和 config 互相导入
        write_atomic(CONFIG_FILE, json.dumps(merged, ensure_ascii=False, indent=2))
        return merged
