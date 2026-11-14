"""不依赖网络和后台线程的小单元"""
from datetime import datetime

import numpy as np

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
