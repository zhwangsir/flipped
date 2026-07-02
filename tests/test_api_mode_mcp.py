"""M7.3/M7.4 — MCP 端点 + 模式路由（对话/规划）后端集成测试。"""
import time

from fastapi.testclient import TestClient

import api.main as main
from api.main import API_PREFIX, app


def _new_session(c: TestClient, title: str = "t") -> str:
    return c.post(f"{API_PREFIX}/sessions", params={"title": title}).json()["id"]


# ---------- M7.3 MCP 端点 ----------

def test_mcp_servers_list(monkeypatch, tmp_path):
    monkeypatch.setenv("FLIPPED_MCP_CONFIG_PATH", str(tmp_path / "m.json"))
    with TestClient(app) as c:
        r = c.get(f"{API_PREFIX}/mcp/servers")
        assert r.status_code == 200
        servers = r.json()
        names = {s["name"] for s in servers}
        assert "flipped" in names
        flipped = next(s for s in servers if s["name"] == "flipped")
        assert "web_search" in flipped["tools"]
        assert all(s["enabled"] is False for s in servers)


def test_mcp_toggle_and_persist(monkeypatch, tmp_path):
    monkeypatch.setenv("FLIPPED_MCP_CONFIG_PATH", str(tmp_path / "m.json"))
    with TestClient(app) as c:
        r = c.post(f"{API_PREFIX}/mcp/servers/filesystem/toggle", params={"enabled": True})
        assert r.status_code == 200
        assert r.json()["enabled"] is True
        servers = c.get(f"{API_PREFIX}/mcp/servers").json()
        assert next(s["enabled"] for s in servers if s["name"] == "filesystem") is True


def test_mcp_toggle_unknown_404(monkeypatch, tmp_path):
    monkeypatch.setenv("FLIPPED_MCP_CONFIG_PATH", str(tmp_path / "m.json"))
    with TestClient(app) as c:
        r = c.post(f"{API_PREFIX}/mcp/servers/nope/toggle", params={"enabled": True})
        assert r.status_code == 404


# ---------- M7.4 模式路由 ----------

def test_task_mode_chat_routes_to_run_chat(monkeypatch):
    """mode=chat 应路由到 _run_chat（而非沙盒 worker），并透传 model。"""
    calls: dict[str, str] = {}

    async def fake_chat(session_id, task_id, description, model_alias, mode):
        calls["mode"] = mode
        calls["model"] = model_alias
        from api.schemas import SessionStatus
        from api.session import store as _store

        _store.update_status(session_id, SessionStatus.done)

    monkeypatch.setattr(main, "_run_chat", fake_chat)
    with TestClient(app) as c:
        sid = _new_session(c, "chat")
        r = c.post(
            f"{API_PREFIX}/sessions/{sid}/tasks",
            json={"description": "hi", "context": {"mode": "chat", "model": "architect"}},
        )
        assert r.status_code == 200
        deadline = time.time() + 5
        while time.time() < deadline and "mode" not in calls:
            time.sleep(0.05)
    assert calls.get("mode") == "chat"
    assert calls.get("model") == "architect"
