"""测试环境：数据目录放到临时文件夹（必须在 import aimind 之前设置），AI 用假的接口"""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ["AIMIND_DATA"] = tempfile.mkdtemp(prefix="aimind_test_")
os.environ["NO_PROXY"] = os.environ["no_proxy"] = "127.0.0.1,localhost"

import pytest  # noqa: E402


@pytest.fixture(scope="session")
def mock_ai():
    from tools import mock_openai
    return mock_openai.serve()


@pytest.fixture(scope="session")
def client(mock_ai):
    from fastapi.testclient import TestClient

    from aimind.web.app import app
    with TestClient(app) as c:
        r = c.post("/api/config", json={
            "audio_base_url": mock_ai, "audio_api_key": "sk-test",
            "llm_base_url": mock_ai, "llm_api_key": "sk-test", "llm_model": "m",
            "review_input": "audio", "review_mode": "realtime", "realtime_min_sec": 2,
            "pause_close_sec": 3, "daily_review_time": "", "nas_dir": str(Path(os.environ["AIMIND_DATA"]) / "nas")})
        assert r.status_code == 200
        yield c


def wait_for(cond, timeout=60.0, step=0.1):
    import time
    end = time.time() + timeout
    while time.time() < end:
        v = cond()
        if v:
            return v
        time.sleep(step)
    raise AssertionError("等待超时")
