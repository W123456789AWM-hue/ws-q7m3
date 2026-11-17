"""不依赖网络和后台线程的小单元"""
from datetime import datetime

import numpy as np
import pytest

from aimind.audio import SR, Segmenter
from aimind.audio.adpcm import decode
from aimind.evalset import edit_ops, normalize
from aimind.review.listen import split_groups
from aimind.review.llm import parse_json
from tools.device_sim import adpcm_encode, synth

CFG = {"vad_margin_db": 10, "vad_min_db": -50}


def test_segmenter_cuts_utterances_with_recording_time():
    got = []
    seg = Segmenter("a", CFG, got.append)
    t0 = datetime(2026, 1, 1, 10, 0, 0)
    seg.feed(synth([(2, False), (3, True), (2, False), (3, True), (2, False)]), t0)
    seg.flush()
    assert len(got) == 2
    assert 1.4 < (got[0].t0 - t0).total_seconds() < 2.2
    assert 6.4 < (got[1].t0 - t0).total_seconds() < 7.2
    assert all(u.device == "a" for u in got)


def test_segmenter_gap_skips_time():
    got = []
    seg = Segmenter("a", CFG, got.append)
    t0 = datetime(2026, 1, 1, 10, 0, 0)
    seg.feed(synth([(1, False)]), t0)
    seg.skip(60)                                   # 一分钟静音（只传了标记）
    seg.feed(synth([(3, True), (2, False)], seed=1))
    seg.flush()
    assert len(got) == 1 and 60 < (got[0].t0 - t0).total_seconds() < 62


def test_adpcm_roundtrip():
    pcm = synth([(1, True)])
    back = decode(adpcm_encode(pcm), len(pcm))
    assert len(back) == len(pcm)
    err = np.sqrt(np.mean((back.astype(float) - pcm) ** 2)) / np.sqrt(np.mean(pcm.astype(float) ** 2))
    assert err < 0.2


def test_parse_json_variants():
    assert parse_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert parse_json('<think>想想{x}</think>好的：{"a": [1, 2]} 以上') == {"a": [1, 2]}
    assert parse_json("没有 JSON") is None


def test_normalize_and_edit_ops():
    ref, hyp = normalize("我用 Python 写了 3 个脚本。"), normalize("我用python写了三个脚本")
    n, _ = edit_ops(ref, hyp)
    assert n == 0


def test_split_groups_by_duration():
    groups = [{"pid": i, "clips": [f"{i}.pcm"], "secs": [50.0]} for i in range(5)]
    batches = split_groups(groups, 120)
    assert [len(b) for b in batches] == [2, 2, 1]
    assert SR == 16000


def test_trim_silence_keeps_speech_and_cuts_long_edges():
    from aimind.review.listen import trim_silence
    pcm = synth([(1.2, False), (2, True), (0.9, False)])
    out = trim_silence(pcm)
    assert len(out) < len(pcm) - int(SR * 1.2)          # 前后静音大部分去掉了
    assert len(out) >= int(SR * 2)                     # 说话部分一点没少
    quiet = np.zeros(SR, dtype=np.int16)
    assert len(trim_silence(quiet)) == SR              # 全静音不处理


def test_usage_record_and_summary():
    from aimind.review import usage
    usage.record("gpt-audio-x", {"prompt_tokens": 1000, "completion_tokens": 200,
                                 "prompt_tokens_details": {"cached_tokens": 600, "audio_tokens": 700}},
                 "audio", audio_sec=30, saved_sec=4)
    usage.record("claude-x", {"input_tokens": 100, "cache_read_input_tokens": 50, "output_tokens": 20}, "text")
    t = usage.day_summary()["total"]
    assert t["calls"] >= 2 and t["input"] >= 1150 and t["cached"] >= 650 and t["audio_tokens"] >= 700
    assert t["saved_sec"] >= 4


def test_due_reports_timing(monkeypatch):
    from aimind.review import daily
    monkeypatch.setattr(daily, "read_report", lambda p, k: "")
    monkeypatch.setattr(daily, "has_data", lambda p, k: True)
    cfg = {"daily_review_time": "23:00", "period_review_time": "23:30",
           "monthly_review": "month_end", "yearly_review": "year_end"}
    due = daily.due_reports(cfg, datetime(2026, 11, 30, 23, 31))
    assert ("day", "2026-11-30") in due and ("month", "2026-11") in due and ("month", "2026-10") in due
    assert ("year", "2025") in due and ("year", "2026") not in due
    assert ("month", "2026-11") not in daily.due_reports(cfg, datetime(2026, 11, 30, 23, 10))
    nxt = {**cfg, "monthly_review": "next_month", "yearly_review": "next_year"}
    assert ("month", "2026-11") not in daily.due_reports(nxt, datetime(2026, 11, 30, 23, 31))
    assert ("month", "2026-11") in daily.due_reports(nxt, datetime(2026, 12, 1, 23, 31))
    assert ("year", "2026") in daily.due_reports(nxt, datetime(2027, 1, 1, 23, 40))
    off = {**cfg, "monthly_review": "off", "yearly_review": "off", "daily_review_time": ""}
    assert daily.due_reports(off, datetime(2026, 12, 31, 23, 59)) == []


def test_port_taken_by_other_app_moves_to_free_port():
    """8765 被别的程序（比如 Loon 配置服务）占着：不能当成自己，要换端口并记住"""
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    from aimind import config, portpick

    class Other(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"<html>Loon config</html>")

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), Other)
    taken = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    old = config.load().get("server_port")
    try:
        config.save({"server_port": taken})
        assert portpick.port_busy(taken) and not portpick.is_ours(taken)
        port, moved, wanted = portpick.choose_port()
        assert moved and wanted == taken and port != taken and not portpick.port_busy(port)
        assert config.load()["server_port"] == port          # 记住了，下次直接用
        assert portpick.choose_port("9999") == (9999, False, 9999)   # 环境变量指定的照用
    finally:
        srv.shutdown()
        config.save({"server_port": old or 8765})


def test_update_manifest_signature_and_versions(monkeypatch):
    import base64
    import json

    import pytest

    from aimind import ed25519, updater
    from aimind.version import newer, parse
    assert parse("v0.9.10") == (0, 9, 10) and newer("0.10.0", "0.9.9") and not newer("0.9.2", "0.9.2")
    seed = bytes(range(32))
    monkeypatch.setattr(updater, "PUBLIC_KEY", base64.b64encode(ed25519.public_key(seed)).decode())
    asset = {"name": "a.exe", "url": "u", "size": 1, "sha256": "x"}
    raw = json.dumps({"version": "9.9.9", "assets": {"windows": asset}}).encode()
    sig = base64.b64encode(ed25519.sign(seed, raw))
    assert updater.verify_manifest(raw, sig)["version"] == "9.9.9"
    with pytest.raises(RuntimeError, match="签名"):
        updater.verify_manifest(raw.replace(b"9.9.9", b"9.9.8"), sig)        # 清单被改过
    with pytest.raises(RuntimeError, match="签名"):
        updater.verify_manifest(raw, base64.b64encode(b"\0" * 64))          # 签名是假的


def test_update_download_falls_back_to_other_routes(monkeypatch):
    """直连 GitHub 被掐断（国内常见）：自动换镜像线路，并记住能用的那条"""
    import ssl

    import pytest

    from aimind import updater
    calls = []

    class Resp:
        def read(self):
            return b"ok"

    def fake_open(url, timeout=30, proxy=True):
        calls.append((url, proxy))
        if not url.startswith("https://gh-proxy.com/"):
            raise ssl.SSLError("UNEXPECTED_EOF_WHILE_READING")
        return Resp()

    monkeypatch.setattr(updater, "_open", fake_open)
    monkeypatch.setattr(updater, "_good_route", None)
    url = "https://github.com/x/y/releases/latest/download/latest.json"
    assert updater._get(url, {}) == b"ok"
    assert calls[-1] == ("https://gh-proxy.com/" + url, True)
    assert calls[0] == (url, True)                         # 先试系统代理直连
    calls.clear()
    assert updater._get(url, {}) == b"ok" and len(calls) == 1   # 第二次直接用记住的线路
    monkeypatch.setattr(updater, "_open", lambda *a, **k: (_ for _ in ()).throw(OSError("断了")))
    with pytest.raises(RuntimeError, match="线路"):
        updater._get(url, {})


def test_feedback_sends_signed_card_and_queues_when_offline(monkeypatch, tmp_path):
    """反馈发到（模拟的）飞书机器人：签名对得上；发不出去先存着，恢复后重发"""
    import json
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    from aimind import feedback
    got, mode = [], {"down": True}

    class Lark(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            if mode["down"]:
                self.send_response(503)
                self.end_headers()
                return
            ok = body.get("sign") == feedback._sign("s3cret", int(body["timestamp"]))
            got.append(body)
            self.send_response(200)
            self.end_headers()
            self.wfile.write(json.dumps({"code": 0 if ok else 19021, "msg": "sign match fail"}).encode())

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), Lark)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    monkeypatch.setattr(feedback, "FEEDBACK_DIR", tmp_path)
    monkeypatch.setenv("AIMIND_FEEDBACK_WEBHOOK", f"http://127.0.0.1:{srv.server_address[1]}/hook")
    monkeypatch.setenv("AIMIND_FEEDBACK_SECRET", "s3cret")
    try:
        r = feedback.submit("bug", "点结束本场没反应", "微信 abc", include_diag=True, source="客厅手机")
        assert r["status"] == "pending" and "diag" not in r and feedback.history()[0]["id"] == r["id"]
        mode["down"] = False
        assert feedback.retry_pending() == 1 and feedback.history()[0]["status"] == "sent"
        card = got[0]["card"]
        assert "【问题】" in card["header"]["title"]["content"] and "客厅手机" in card["header"]["title"]["content"]
        assert "点结束本场没反应" in card["elements"][0]["text"]["content"]
        assert feedback.retry_pending() == 0                       # 已送达的不会重复发
        monkeypatch.setenv("AIMIND_FEEDBACK_SECRET", "wrong")      # 签名不对：飞书拒收 → 留着重发
        assert feedback.submit("idea", "加个导出")["status"] == "pending"
    finally:
        srv.shutdown()
    with pytest.raises(RuntimeError):
        feedback.submit("bug", "   ")


def test_feedback_images_upload_to_feishu_and_degrade_gracefully(monkeypatch, tmp_path):
    """附图：配了自建应用就上传拿 image_key 放进卡片；没配 / 卡片不收图片时文字照样送到并注明"""
    import json
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    from aimind import feedback
    cards, uploads, mode = [], [], {"reject_img": False}
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 100

    class Lark(BaseHTTPRequestHandler):
        def reply(self, obj):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(json.dumps(obj).encode())

        def do_POST(self):
            raw = self.rfile.read(int(self.headers["Content-Length"]))
            if self.path.endswith("/tenant_access_token/internal"):
                ok = json.loads(raw) == {"app_id": "cli_x", "app_secret": "appsec"}
                return self.reply({"code": 0, "tenant_access_token": "t-1", "expire": 7200} if ok else {"code": 10014})
            if self.path.endswith("/im/v1/images"):
                assert self.headers["Authorization"] == "Bearer t-1" and b'name="image_type"' in raw and png in raw
                uploads.append(1)
                return self.reply({"code": 0, "data": {"image_key": f"img_v3_{len(uploads)}"}})
            card = json.loads(raw)["card"]
            has_img = any(e["tag"] == "img" for e in card["elements"])
            if has_img and mode["reject_img"]:
                return self.reply({"code": 11310, "msg": "image key invalid"})
            cards.append(card)
            self.reply({"code": 0})

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), Lark)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    monkeypatch.setattr(feedback, "FEEDBACK_DIR", tmp_path)
    monkeypatch.setattr(feedback, "FEISHU", base)
    monkeypatch.setattr(feedback, "_token", {"value": "", "until": 0.0})
    monkeypatch.setenv("AIMIND_FEEDBACK_WEBHOOK", base + "/hook")
    monkeypatch.delenv("AIMIND_FEEDBACK_SECRET", raising=False)
    try:
        r = feedback.submit("bug", "没配图片通道", include_diag=False, images=[png])
        assert r["status"] == "sent" and r["images"] == ["1.png"] and (tmp_path / r["id"] / "1.png").read_bytes() == png
        assert "还有 1 张附图没能显示" in json.dumps(cards[-1], ensure_ascii=False)

        monkeypatch.setenv("AIMIND_FEEDBACK_APP_ID", "cli_x")
        monkeypatch.setenv("AIMIND_FEEDBACK_APP_SECRET", "appsec")
        r = feedback.submit("bug", "两张图", include_diag=False, images=[png, png])
        imgs = [e for e in cards[-1]["elements"] if e["tag"] == "img"]
        assert r["status"] == "sent" and [e["img_key"] for e in imgs] == ["img_v3_1", "img_v3_2"]
        assert "image_keys" not in r and "没能显示" not in json.dumps(cards[-1], ensure_ascii=False)

        mode["reject_img"] = True                     # 卡片不收这些图片：文字先送到，注明原因
        r = feedback.submit("idea", "图片被拒", include_diag=False, images=[png])
        assert r["status"] == "sent" and "卡片放不进图片" in json.dumps(cards[-1], ensure_ascii=False)
    finally:
        srv.shutdown()
    with pytest.raises(RuntimeError):
        feedback.submit("bug", "不是图片", images=[b"hello world"])
    with pytest.raises(RuntimeError):
        feedback.submit("bug", "太多", images=[png] * 4)


def test_feedback_redacts_secrets():
    from aimind.feedback import redact
    s = redact('api_key: "sk-abcDEF1234567890xyz" token=ghp_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa 正常的话 v0.9.5')
    assert "sk-abc" not in s and "ghp_aaaa" not in s and "正常的话 v0.9.5" in s


def test_ai_request_retries_once_when_pooled_connection_was_closed(monkeypatch):
    """连接池里的旧连接被服务器关掉了：自动重发一次，不让这一轮复盘失败"""
    import httpx

    from aimind.review import llm
    calls = []

    def flaky(self, *a, **k):
        calls.append(1)
        if len(calls) == 1:
            raise httpx.RemoteProtocolError("Server disconnected without sending a response.")
        return "ok"

    monkeypatch.setattr(httpx.Client, "post", flaky)
    assert llm.HTTP.post("http://x") == "ok" and len(calls) == 2
    calls.clear()
    monkeypatch.setattr(httpx.Client, "post", lambda *a, **k: (_ for _ in ()).throw(httpx.ReadTimeout("慢")))
    with pytest.raises(httpx.ReadTimeout):       # 超时（服务器可能已经在处理）不重发，免得重复计费
        llm.HTTP.post("http://x")


def test_ui_sounds_are_valid_and_follow_splash_speed():
    """界面音效：合法的 WAV、不爆音、没有突然的咔嗒声；启动音效跟着动画速度变短，主和弦落在标志拼合的时刻"""
    import io
    import wave

    import numpy as np

    from aimind import sounds
    for data in (sounds.click_wav(), sounds.splash_wav(1), sounds.splash_wav(2)):
        with wave.open(io.BytesIO(data)) as w:
            assert (w.getnchannels(), w.getsampwidth(), w.getframerate()) == (1, 2, sounds.SR)
            x = np.frombuffer(w.readframes(w.getnframes()), "<i2") / 32768
        assert 0.2 < np.abs(x).max() < 0.75
        assert np.abs(np.diff(x)).max() < 0.2           # 没有突变（咔嗒声）
    assert 0.03 < len(sounds.click()) / sounds.SR < 0.06
    one, two = sounds.splash(1), sounds.splash(2)
    assert len(two) < len(one)

    def loudest(x):          # 最响的 0.1 秒在哪
        w = int(0.1 * sounds.SR)
        e = [np.sum(x[i:i + w] ** 2) for i in range(0, len(x) - w, w // 2)]
        return int(np.argmax(e)) * (w // 2) / sounds.SR

    assert abs(loudest(one) - sounds.SPLASH_EVENTS["reveal"]) < 0.25
    assert abs(loudest(two) - sounds.SPLASH_EVENTS["reveal"] / 2) < 0.25


def test_desktop_splash_sound_respects_setting(monkeypatch, tmp_path):
    import desktop_app
    from aimind import config
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "config.json", raising=False)
    monkeypatch.setattr(config, "load", lambda: {**config.DEFAULTS, "splash_sound": True})
    s = desktop_app.SplashSound(1.5)
    assert s.path and s.path.exists() and s.path.stat().st_size > 100_000
    monkeypatch.setattr(config, "load", lambda: {**config.DEFAULTS, "splash_sound": False})
    assert desktop_app.SplashSound(1.5).path is None
    desktop_app.SplashSound(1.5).stop()              # 没开声音时停也不出错
    # 音量：设置不同的音量用不同的缓存文件，“轻”的峰值明显更小
    peaks = {}
    for vol in (0.3, 1.4):
        monkeypatch.setattr(config, "load", lambda v=vol: {**config.DEFAULTS, "splash_sound_volume": v})
        p = desktop_app.SplashSound(1.5).path
        peaks[vol] = np.abs(np.frombuffer(p.read_bytes()[44:], "<i2")).max()
    assert peaks[0.3] < peaks[1.4] * 0.3 and peaks[1.4] <= 32767


def test_web_scripts_have_no_syntax_errors(tmp_path):
    """界面脚本没有语法错误。（0.10.1 起 splash.html 里重复声明了 started，整段脚本不运行：
    Mac 的启动动画和音效都没了，要等兜底计时器才进主窗口。）需要 node；本机没装时跳过，云端有"""
    import re
    import shutil
    import subprocess
    from pathlib import Path
    node = shutil.which("node")
    if not node:
        pytest.skip("没有 node")
    static = Path(__file__).resolve().parent.parent / "aimind" / "web" / "static"
    files = []
    for html in static.rglob("*.html"):
        inline = re.findall(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", html.read_text("utf-8"), re.S)
        for i, code in enumerate(inline):
            f = tmp_path / f"{html.stem}-{i}.mjs"
            f.write_text(code, "utf-8")
            files.append(f)
    for js in static.rglob("*.js"):
        f = tmp_path / (js.relative_to(static).as_posix().replace("/", "_") + ".mjs")
        f.write_text(js.read_text("utf-8"), "utf-8")
        files.append(f)
    assert files
    bad = []
    for f in files:
        r = subprocess.run([node, "--check", str(f)], capture_output=True, text=True, encoding="utf-8")
        if r.returncode:
            bad.append(f"{f.name}: {r.stderr.strip()[-300:]}")
    assert not bad, "\n".join(bad)


def test_file_writes_survive_brief_windows_locks(monkeypatch, tmp_path):
    """Windows 上文件偶尔被杀毒软件 / 同步线程短暂占用（PermissionError）：等一等再写，不让复盘失败。
    （云端测试曾因此偶发失败：transcript.jsonl 拒绝访问 → 那一轮复盘报错）"""
    import builtins
    import json
    from pathlib import Path

    from aimind import fsutil
    monkeypatch.setattr(fsutil, "DELAYS", (0, 0, 0, 0))
    real_open, real_replace = builtins.open, Path.replace
    fails = {"open": 2, "replace": 2}

    def flaky_open(file, mode="r", *a, **k):
        if "a" in mode and fails["open"] > 0:
            fails["open"] -= 1
            raise PermissionError(13, "Permission denied", str(file))
        return real_open(file, mode, *a, **k)

    def flaky_replace(self, target):
        if fails["replace"] > 0:
            fails["replace"] -= 1
            raise PermissionError(13, "Permission denied", str(target))
        return real_replace(self, target)

    monkeypatch.setattr(builtins, "open", flaky_open)
    monkeypatch.setattr(Path, "replace", flaky_replace)
    log = tmp_path / "transcript.jsonl"
    assert fsutil.append_jsonl(log, [{"text": "第一句"}, {"text": "第二句"}])
    assert [json.loads(x)["text"] for x in log.read_text(encoding="utf-8").splitlines()] == ["第一句", "第二句"]
    fsutil.write_atomic(tmp_path / "session.json", '{"ok": 1}')
    assert json.loads((tmp_path / "session.json").read_text(encoding="utf-8")) == {"ok": 1}

    # 一直被占着：附带的日志写不进去也只是记一笔，不抛错
    fails["open"] = 99
    assert fsutil.append_jsonl(log, [{"text": "第三句"}]) is False


def test_google_gemini_vendor(monkeypatch, tmp_path):
    """选 Google：听录音和文字 AI 都走 Gemini 的 OpenAI 兼容接口，用 Google 的 Key 和 gemini 模型；
    不发 modalities、思考调到最省；录音每次最多 6 分钟（一次请求最大 20MB）；换回 OpenAI 时模型名恢复"""
    from aimind.review import listen, llm
    sent = []

    class Resp:
        status_code = 200
        text = ""

        def json(self):
            return {"choices": [{"message": {"content": '{"title": "t", "summary": "s"}'}}],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 5}}

    class FakeClient:
        def post(self, url, headers=None, json=None, timeout=None):
            sent.append((url, headers, json))
            return Resp()

    monkeypatch.setattr(llm, "client_for", lambda base: FakeClient())
    monkeypatch.setattr(listen, "client_for", lambda base: FakeClient())
    monkeypatch.setattr(llm.usage, "record", lambda *a, **k: None)
    monkeypatch.setattr(listen.usage, "record", lambda *a, **k: None)

    cfg = {"audio_vendor": "google", "google_api_key": "AIzaTEST", "audio_model": "gpt-audio-1.5",
           "audio_api_key": "sk-openai", "llm_provider": "openai", "llm_model": "", "llm_api_key": ""}
    assert listen.audio_endpoint(cfg) == (llm.GEMINI_BASE, "AIzaTEST", llm.GEMINI_MODEL)
    # 听录音
    (tmp_path / "clips").mkdir()
    (tmp_path / "clips" / "a.pcm").write_bytes((np.sin(np.arange(16000) / 5) * 8000).astype(np.int16).tobytes())
    listen.call_audio(cfg, "sys", "head", [{"pid": 1, "clock": "10:00:00", "clips": ["a.pcm"]}], tmp_path)
    url, headers, body = sent[-1]
    assert url == llm.GEMINI_BASE + "/chat/completions" and headers["Authorization"] == "Bearer AIzaTEST"
    assert body["model"] == llm.GEMINI_MODEL and "modalities" not in body and body["reasoning_effort"] == "low"
    assert any(p.get("type") == "input_audio" for p in body["messages"][1]["content"])
    # 文字 AI 没单独配：借用听录音的 Google
    llm.chat(cfg, "sys", "hi")
    assert sent[-1][0].startswith(llm.GEMINI_BASE) and sent[-1][2]["model"] == llm.GEMINI_MODEL
    # 文字 AI 选 Google、Key 没单独填：用 Google Key；模型名不是 gemini 的换成默认
    t = llm.text_cfg({**cfg, "audio_vendor": "openai", "llm_provider": "google", "llm_model": "deepseek-chat"})
    assert (t["llm_base_url"], t["llm_api_key"], t["llm_model"]) == (llm.GEMINI_BASE, "AIzaTEST", llm.GEMINI_MODEL)
    # 换回 OpenAI：gemini 模型名不会被带过去
    o = listen.audio_endpoint({**cfg, "audio_vendor": "openai", "audio_model": "gemini-3.8-flash"})
    assert o == ("https://api.openai.com/v1", "sk-openai", "gpt-audio-1.5")
    # 每次最多发多少录音：设置是 8 分钟，Google 压到 6 分钟，OpenAI 照旧
    groups = [{"pid": 1, "clock": "", "clips": []}]
    monkeypatch.setattr(listen, "call_audio", lambda *a, **k: '{"title": "t"}')
    caps = []
    monkeypatch.setattr(listen, "split_groups", lambda g, max_sec: caps.append(max_sec) or [g])
    listen.audio_review({**cfg, "audio_max_min": 8}, groups, tmp_path, "", [])
    listen.audio_review({**cfg, "audio_vendor": "openai", "audio_max_min": 8}, groups, tmp_path, "", [])
    assert caps == [360.0, 480.0]


def test_google_uses_system_proxy(monkeypatch):
    """httpx 不认系统代理：连 Google 时自动用系统代理（国内直连不通）；别的接口、设了环境变量时不动"""
    import urllib.request

    from aimind.review import llm
    for k in ("HTTPS_PROXY", "https_proxy", "ALL_PROXY", "all_proxy"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(urllib.request, "getproxies", lambda: {"https": "http://127.0.0.1:7890"})
    c = llm.client_for(llm.GEMINI_BASE)
    assert c is not llm.HTTP and llm.client_for(llm.GEMINI_BASE) is c       # 复用同一个
    assert llm.client_for("https://api.openai.com/v1") is llm.HTTP
    monkeypatch.setattr(urllib.request, "getproxies", lambda: {})
    assert llm.client_for(llm.GEMINI_BASE) is llm.HTTP
    monkeypatch.setattr(urllib.request, "getproxies", lambda: {"https": "http://127.0.0.1:7890"})
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:1")
    assert llm.client_for(llm.GEMINI_BASE) is llm.HTTP


def test_busy_server_retries_then_falls_back(monkeypatch):
    """Gemini 返回 503 “high demand”：自动等一会儿重试；一直忙就最后换备用模型；全不行给好懂的提示"""
    from aimind.review import llm

    class Resp:
        def __init__(self, code):
            self.status_code, self.text = code, '{"error": {"code": %d}}' % code

        def json(self):
            return {"choices": [{"message": {"content": "ok"}}], "usage": {}}

    seq, models = [], []

    class FakeClient:
        def post(self, url, headers=None, json=None, timeout=None):
            models.append(json["model"])
            return Resp(seq.pop(0))

    monkeypatch.setattr(llm, "BUSY_WAITS", (0, 0, 0))
    monkeypatch.setattr(llm, "client_for", lambda base: FakeClient())
    monkeypatch.setattr(llm.usage, "record", lambda *a, **k: None)
    cfg = {"llm_provider": "google", "google_api_key": "AIzaTEST", "llm_model": ""}

    seq[:] = [503, 200]                        # 忙一次，第二次好了
    assert llm.chat(cfg, "s", "u") == "ok" and models == [llm.GEMINI_MODEL] * 2
    seq[:], models[:] = [503, 503, 503, 200], []   # 一直忙：最后一次换备用模型
    assert llm.chat(cfg, "s", "u") == "ok" and models[-1] == llm.GEMINI_FALLBACK
    seq[:] = [503, 503, 503, 404]              # 备用模型也不能用：报原来的“太忙”
    with pytest.raises(RuntimeError, match="太忙"):
        llm.chat(cfg, "s", "u")
