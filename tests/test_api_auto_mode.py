"""F3 — 一等「自主」模式:mode=auto 路由到多 Agent 监督循环。"""
import time

from fastapi.testclient import TestClient

from api.main import API_PREFIX, app, _select_runner
from api import project_state as ps


# ---- 纯函数路由选择 ----

def test_auto_mode_selects_orchestrator():
    assert _select_runner("auto", False, False) == "orchestrator"


def test_explicit_orchestrator_cfg_selects_orchestrator():
    assert _select_runner("agent", True, False) == "orchestrator"


def test_chat_and_plan_select_chat():
    assert _select_runner("chat", False, False) == "chat"
    assert _select_runner("plan", False, False) == "chat"


def test_agent_selects_openhands_or_mock():
    assert _select_runner("agent", False, False) == "openhands"
    assert _select_runner("agent", False, True) == "mock"


def test_auto_beats_mock_flag():
    # 自主模式即便 MOCK_WORKER 开着也要走 orchestrator
    assert _select_runner("auto", False, True) == "orchestrator"


# ---- 端到端:mode=auto 经后台跑完整(mock)循环到 done ----

def test_auto_mode_runs_full_loop(tmp_path, monkeypatch):
    ps.clear_active()
    monkeypatch.setenv("FLIPPED_MOCK_ORCHESTRATOR", "1")
    monkeypatch.setattr("api.main.FLIPPED_CHECKPOINT_DB", str(tmp_path / "cp.db"))
    with TestClient(app) as client:
        sid = client.post(f"{API_PREFIX}/sessions",
                          params={"title": "auto", "mode": "auto"}).json()["id"]
        resp = client.post(
            f"{API_PREFIX}/sessions/{sid}/tasks",
            json={"description": "建一个待办 API", "context": {"mode": "auto"}},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "running"
        final = "running"
        for _ in range(80):
            final = client.get(f"{API_PREFIX}/sessions/{sid}").json()["status"]
            if final in ("done", "review", "error"):
                break
            time.sleep(0.05)
        assert final == "done"
