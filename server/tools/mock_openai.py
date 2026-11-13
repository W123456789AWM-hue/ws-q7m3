"""假的 OpenAI 接口：测试时代替真实的 gpt-audio / 文字模型，不花钱、不联网。

    python -m tools.mock_openai            # 单独运行，监听 127.0.0.1:9100
    在设置里把「接口地址」填 http://127.0.0.1:9100/v1，Key 填 sk-test

测试里用 serve() 在后台线程启动，STATS 记录收到了多少次调用、多少段音频。
"""
from __future__ import annotations

import base64
import io
import json
import re
import socket
import threading
import time
import wave

import uvicorn
from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import JSONResponse

KEY = "sk-test"
app = FastAPI()
STATS = {"audio_calls": 0, "audio_parts": 0, "audio_sec": 0.0, "text_calls": 0, "labels": []}

REVIEW = {"trivial": False, "title": "辞职开店", "summary": "在考虑辞职开咖啡店。",
          "key_points": ["想开咖啡店"], "blind_spots": ["没提现金流"],
          "latent_needs": [{"need": "想要更自主的生活", "evidence": "反复提辞职"}],
          "divergent": [{"angle": "跨界类比", "idea": "先摆摊验证"}],
          "suggestions": [{"text": "先做周末快闪", "priority": "高"}], "questions": ["为什么是咖啡？"],
          "changes": [], "topics": [{"time": "10:00", "topic": "开店", "gist": "在想"}]}


def reply(content) -> dict:
    if not isinstance(content, str):
        content = "```json\n" + json.dumps(content, ensure_ascii=False) + "\n```"
    return {"choices": [{"message": {"content": content}}],
            "usage": {"prompt_tokens": 1200, "completion_tokens": 300,
                      "prompt_tokens_details": {"cached_tokens": 1024, "audio_tokens": 0}}}


@app.post("/v1/audio/transcriptions")
async def stt(file: UploadFile = File(...), model: str = Form(...)):
    await file.read()
    return {"text": "我在想要不要辞职开一家咖啡店。"}


@app.post("/v1/chat/completions")
async def chat(req: Request):
    if req.headers.get("authorization") != f"Bearer {KEY}":
        return JSONResponse({"error": {"message": "Incorrect API key provided"}}, status_code=401)
    j = await req.json()
    msgs = j["messages"]
    system = msgs[0]["content"] if len(msgs) > 1 else ""
    user = msgs[-1]["content"]
    if not isinstance(user, list):           # ---- 纯文字 ----
        STATS["text_calls"] += 1
        if "JSON" in system:
            return reply(REVIEW)
        return reply("## 整体在聊什么\n辞职开店\n## 行动清单\n- [ ] 做预算（高）")
    # ---- 带音频（gpt-audio）----
    assert j.get("modalities") == ["text"], j.get("modalities")
    STATS["audio_calls"] += 1
    texts, pids = [], []
    for part in user:
        if part["type"] == "text":
            texts.append(part["text"])
            for m in re.finditer(r"【段落 #(\d+)([^】]*)】", part["text"]):
                pids.append(int(m.group(1)))
                STATS["labels"].append(m.group(0))
        elif part["type"] == "input_audio":
            assert part["input_audio"]["format"] == "wav"
            w = wave.open(io.BytesIO(base64.b64decode(part["input_audio"]["data"])))
            assert (w.getframerate(), w.getnchannels(), w.getsampwidth()) == (16000, 1, 2)
            STATS["audio_parts"] += 1
            STATS["audio_sec"] += w.getnframes() / 16000
    if "测试" in "".join(texts) and not pids:
        return reply("听到了一段提示音。")
    tr = [{"id": p, "text": f"（段落{p}听写）开店的事再想想。"} for p in pids]
    if "blind_spots" in system:
        return reply({**REVIEW, "transcripts": tr, "voice_cues": ["说到辞职时语气犹豫"]})
    return reply({"transcripts": tr, "voice_cues": ["语速偏快"]})   # 分批听写


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def serve(port: int = 0) -> str:
    """后台线程启动，返回接口地址（.../v1）"""
    port = port or free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    while not server.started:
        time.sleep(0.05)
    return f"http://127.0.0.1:{port}/v1"


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=9100, log_level="warning")
