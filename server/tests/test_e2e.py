"""整条流程：几台设备同时上传 → 切句 → AI 听录音复盘 → 收尾。AI 用 tools/mock_openai.py 代替"""
from datetime import datetime, timedelta

from conftest import wait_for

from tools import mock_openai
from tools.device_sim import DeviceSim, synth


def done_session(client, sid=None):
    def check():
        for s in client.get("/api/sessions").json():
            if (sid is None or s["id"] == sid) and s["status"] == "done":
                return client.get(f"/api/sessions/{s['id']}").json()
        return None
    return wait_for(check, timeout=90)


def test_pages_and_settings(client):
    assert client.get("/").status_code == 200
    assert client.get("/static/app.js").status_code == 200
    # 界面是 ES 模块：入口 import 的每个文件都要能取到
    import re
    from pathlib import Path
    static = Path(__file__).resolve().parent.parent / "aimind" / "web" / "static"
    for js in [static / "app.js", *static.glob("js/**/*.js")]:
        for imp in re.findall(r"from '(\.[^']+)'", js.read_text(encoding="utf-8")):
            target = (js.parent / imp).resolve().relative_to(static).as_posix()
            assert client.get("/static/" + target).status_code == 200, (js.name, imp)
    for css in re.findall(r'href="(/static/css/[^"]+)"', client.get("/").text):
        assert client.get(css).status_code == 200, css
    assert client.get("/static/js/dom.js").headers.get("cache-control") == "no-cache"
    # 关着的浮层不能挡住鼠标（曾经出过：display:flex 盖掉了 hidden，透明的抽屉 / 设置弹窗挡住了按钮）
    css = client.get("/static/css/base.css").text + client.get("/static/css/motion.css").text
    assert "[hidden]{display:none !important}" in css
    assert ".drawer:not([data-open])" in css and ".sheet:not([data-open])" in css and "pointer-events:none" in css
    assert client.post("/api/test/audio").json()["ok"]
    assert client.post("/api/test/llm").json()["ok"]
    assert client.post("/api/test/nas").json()["ok"]


def test_two_devices_one_session(client):
    t0 = datetime(2026, 11, 10, 9, 0, 0)
    talk_a = synth([(1, False), (4, True), (6, False), (4, True), (15, False)], seed=1)
    talk_b = synth([(6, False), (4, True), (6, False), (4, True), (10, False)], seed=2)
    a = DeviceSim(client.post, "kitchen", "厨房手机")
    b = DeviceSim(client.post, "office", "办公室 iPad", adpcm=True)   # 移动网络压缩上传
    a.upload(talk_a, t0)
    b.upload(talk_b, t0 + timedelta(seconds=0.5))
    a.upload(talk_a[:0], t0)            # 空上传无影响
    st = wait_for(lambda: (lambda s: s if s["session"] and len(s["devices"]) == 2 else None)(
        client.get("/api/state").json()))
    assert {d["name"] for d in st["devices"]} == {"厨房手机", "办公室 iPad"}
    a.stop()
    b.stop()
    s = done_session(client)
    names = {p["device_name"] for p in s["paragraphs"]}
    assert names == {"厨房手机", "办公室 iPad"}
    assert len(s["paragraphs"]) >= 4
    starts = [p["start_t"] for p in s["paragraphs"]]
    # 失败时把每轮复盘的错误原因打出来（云端偶发失败时好查）
    assert all(r["status"] == "done" for r in s["reviews"]) and s["reviews"], \
        [(r["status"], r.get("error")) for r in s["reviews"]]
    assert all("听写" in p["text"] for p in s["paragraphs"]), "AI 听写的文字要填回段落"
    assert any("厨房手机" in x for x in mock_openai.STATS["labels"])
    assert any("办公室 iPad" in x for x in mock_openai.STATS["labels"])
    assert s["devices"] and len(starts) == len(set(p["id"] for p in s["paragraphs"]))
    info = client.get("/api/phone/info").json()
    assert {d["id"] for d in info["phones"]} >= {"kitchen", "office"} and info["backlog"] == 0
    md = client.get(f"/api/sessions/{s['id']}/report.md").text
    assert "厨房手机" in md and "录音设备" in md


def test_old_app_without_device_param(client):
    t0 = datetime(2026, 11, 10, 14, 0, 0)
    old = DeviceSim(lambda url, params, **kw: client.post(
        url, params={k: v for k, v in params.items() if k not in ("device", "name")}, **kw), "", "")
    old.upload(synth([(1, False), (4, True), (5, False)], seed=3), t0)
    old.stop()
    s = done_session(client, "20261110_140000")
    assert {p["device_name"] for p in s["paragraphs"]} == {"手机"}


def test_review_now_and_finish_button(client):
    t0 = datetime(2026, 11, 10, 16, 0, 0)
    client.post("/api/config", json={"review_mode": "interval", "review_interval_min": 60})
    try:
        d = DeviceSim(client.post, "desk", "书桌手机")
        d.upload(synth([(1, False), (4, True), (5, False)], seed=4), t0)
        wait_for(lambda: (client.get("/api/state").json()["next_review"] or {}).get("new_chars", 0) > 2)
        assert client.post("/api/review_now").status_code == 200
        assert client.post("/api/finish").status_code == 200
        s = done_session(client, "20261110_160000")
        assert [r["kind"] for r in s["reviews"]][0] == "manual"
        assert client.post("/api/finish").status_code == 400   # 已经结束了
    finally:
        client.post("/api/config", json={"review_mode": "realtime"})


def test_analyze_text(client):
    wait_for(lambda: not client.get("/api/state").json()["recording"])
    assert client.post("/api/analyze_text", json={"text": "最近在想要不要辞职开咖啡店，存款不多。"}).status_code == 200
    s = wait_for(lambda: (lambda st: st if st["session"]["reviews"][0]["status"] == "done" else None)(
        client.get("/api/state").json()))
    assert s["session"]["reviews"][0]["analysis"]["title"]


def test_token_required_from_other_devices(client):
    from fastapi.testclient import TestClient

    from aimind.web.app import app
    other = TestClient(app, client=("192.168.1.50", 5000))
    assert other.get("/api/state").status_code == 401
    tok = client.get("/api/config").json()["server_token"]
    assert other.get("/api/state", headers={"X-Token": tok}).status_code == 200
    assert other.get(f"/?token={tok}").cookies.get("aim_token") == tok


def test_text_mode_with_stt(client, mock_ai):
    """旧方式：先识别成文字（这里用在线识别接口代替本地模型），再交给文字 AI"""
    client.post("/api/config", json={"review_input": "text", "stt_provider": "api", "stt_base_url": mock_ai,
                                     "stt_api_key": "sk-test", "realtime_min_chars": 5})
    try:
        wait_for(lambda: not client.get("/api/state").json()["recording"])
        d = DeviceSim(client.post, "desk", "书桌手机", stream="t1")
        d.upload(synth([(1, False), (4, True), (6, False), (3, True), (5, False)], seed=5),
                 datetime(2026, 11, 11, 8, 0, 0))
        d.stop()
        s = done_session(client, "20261111_080000")
        assert "咖啡店" in s["paragraphs"][0]["text"]
        assert s["reviews"] and s["reviews"][0]["status"] == "done"
    finally:
        client.post("/api/config", json={"review_input": "audio"})


def test_midnight_starts_new_session(client):
    wait_for(lambda: not client.get("/api/state").json()["recording"])
    d = DeviceSim(client.post, "night", "床头手机", stream="n1")
    d.upload(synth([(1, False), (4, True), (5, False)], seed=6), datetime(2026, 11, 12, 23, 59, 40))
    d.upload(synth([(1, False), (4, True), (5, False)], seed=7), datetime(2026, 11, 13, 0, 0, 30))
    d.stop()
    done_session(client, "20261112_235940")
    s2 = done_session(client, "20261113_000030")
    assert s2["paragraphs"]


def test_day_month_year_reports(client):
    """日复盘 → 月复盘（用日复盘，没做日复盘的日子用阶段复盘摘要）→ 年复盘（用月复盘）"""
    wait_for(lambda: not client.get("/api/state").json()["recording"])
    d = DeviceSim(client.post, "rp", "报告手机", stream="r1")
    d.upload(synth([(1, False), (4, True), (6, False), (3, True), (5, False)], seed=11),
             datetime(2026, 10, 5, 9, 0, 0))
    d.stop()
    done_session(client, "20261005_090000")
    assert client.get("/api/report?period=month&key=2026-10").json()["has_data"]
    r = client.post("/api/report?period=day&key=2026-10-05").json()
    assert r["md"].startswith("# 2026-10-05 日复盘")
    m = client.post("/api/report?period=month&key=2026-10").json()
    assert m["md"].startswith("# 2026-10 月复盘")
    y = client.post("/api/report?period=year&key=2026").json()
    assert y["md"].startswith("# 2026 年复盘")
    assert "2026-10" in client.get("/api/reports?period=month").json()
    assert client.get("/api/report?period=year&key=2026").json()["md"] == y["md"]
    assert client.post("/api/report?period=month&key=2019-01").status_code == 400   # 没有内容


def test_online_update_via_local_release_server(client, monkeypatch, tmp_path):
    """模拟发布服务器：签名清单 + 安装包。检查更新、手机通过电脑下载 APK、文件被篡改时拒绝"""
    import base64
    import hashlib
    import json
    import threading
    from functools import partial
    from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

    from aimind import ed25519, updater

    apk = b"PK fake apk " * 1000
    (tmp_path / "AIMind-99.0.0-android-arm64.apk").write_bytes(apk)
    (tmp_path / "AIMind-Setup-99.0.0.exe").write_bytes(b"MZ fake exe")
    srv = ThreadingHTTPServer(("127.0.0.1", 0), partial(SimpleHTTPRequestHandler, directory=str(tmp_path)))
    srv.RequestHandlerClass.log_message = lambda *a: None
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"

    def publish(apk_sha):
        name = "AIMind-99.0.0-android-arm64.apk"
        assets = {"android-arm64": {"name": name, "url": f"{base}/{name}", "size": len(apk), "sha256": apk_sha},
                  "windows": {"name": "AIMind-Setup-99.0.0.exe", "url": f"{base}/AIMind-Setup-99.0.0.exe", "size": 11,
                              "sha256": hashlib.sha256(b"MZ fake exe").hexdigest()}}
        raw = json.dumps({"version": "99.0.0", "notes": "测试版本", "assets": assets}).encode()
        (tmp_path / "latest.json").write_bytes(raw)
        (tmp_path / "latest.json.sig").write_bytes(base64.b64encode(ed25519.sign(seed, raw)))

    seed = bytes(range(1, 33))
    monkeypatch.setattr(updater, "PUBLIC_KEY", base64.b64encode(ed25519.public_key(seed)).decode())
    monkeypatch.setattr(updater, "UPDATES_DIR", tmp_path / "cache")
    publish(hashlib.sha256(apk).hexdigest())
    client.post("/api/config", json={"update_manifest_url": f"{base}/latest.json"})
    try:
        st = client.post("/api/update/check").json()
        assert st["latest"] == "99.0.0" and not st["error"]
        m = client.get("/api/update/mobile?platform=android&abi=arm64-v8a").json()
        assert m["latest"] == "99.0.0" and m["asset"]["size"] == len(apk)
        assert client.get("/api/update/file/android-arm64").content == apk
        assert client.post("/api/update/install").status_code == 400          # 源码方式运行：不自动安装

        (tmp_path / "cache" / "AIMind-99.0.0-android-arm64.apk").unlink()
        publish("0" * 64)                                                     # 清单说的校验码和文件对不上
        client.post("/api/update/check")
        r = client.get("/api/update/file/android-arm64")
        assert r.status_code == 400 and "校验" in r.json()["detail"]

        (tmp_path / "latest.json.sig").write_bytes(base64.b64encode(b"\1" * 64))   # 签名是假的
        assert "签名" in client.post("/api/update/check").json()["error"]
    finally:
        srv.shutdown()
        client.post("/api/config", json={"update_manifest_url": ""})


def test_feedback_from_phone_goes_through_desktop(client, monkeypatch, tmp_path):
    """手机 App 发反馈：带口令发给电脑，电脑转发；没配置机器人时先存着，界面能看到“等待发送”"""
    import json

    from fastapi.testclient import TestClient

    from aimind import feedback
    from aimind.web.app import app
    monkeypatch.setattr(feedback, "FEEDBACK_DIR", tmp_path)
    monkeypatch.setattr(feedback, "target", lambda: ("", ""))
    phone = TestClient(app, client=("192.168.1.50", 5000))
    assert phone.post("/api/feedback", json={"text": "hi"}).status_code == 401      # 没口令不行
    token = client.get("/api/config").json()["server_token"]
    r = phone.post("/api/feedback", headers={"X-Token": token}, json={
        "kind": "bug", "text": "上传卡住了", "source": "客厅手机", "client": "App 0.9.6 · android 14"}).json()
    assert r["status"] == "pending" and r["source"] == "客厅手机" and "diag" not in r
    saved = json.loads((tmp_path / f"{r['id']}.json").read_text(encoding="utf-8"))
    assert saved["diag"].startswith("发送设备：App 0.9.6 · android 14")
    j = client.get("/api/feedback").json()
    assert j["configured"] is False and j["items"][0]["id"] == r["id"]
    assert client.post("/api/feedback", json={"text": "  "}).status_code == 400
