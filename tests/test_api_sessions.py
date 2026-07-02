"""M6.2 — 会话/任务操作端点：删除会话、事件历史 REST、取消任务。"""
from fastapi.testclient import TestClient

from api.main import API_PREFIX, app


def _new_session(c: TestClient, title: str = "t") -> str:
    return c.post(f"{API_PREFIX}/sessions", params={"title": title}).json()["id"]


def test_delete_session():
    with TestClient(app) as c:
        sid = _new_session(c)
        assert c.get(f"{API_PREFIX}/sessions/{sid}").status_code == 200
        r = c.delete(f"{API_PREFIX}/sessions/{sid}")
        assert r.status_code == 200
        assert r.json()["ok"] is True
        assert c.get(f"{API_PREFIX}/sessions/{sid}").status_code == 404


def test_delete_missing_session_404():
    with TestClient(app) as c:
        assert c.delete(f"{API_PREFIX}/sessions/does-not-exist").status_code == 404


def test_events_rest_history():
    with TestClient(app) as c:
        sid = _new_session(c)
        r = c.get(f"{API_PREFIX}/sessions/{sid}/events")
        assert r.status_code == 200
        evs = r.json()
        assert isinstance(evs, list)
        # create_session 会 emit 一个 status 事件
        assert len(evs) >= 1
        assert any(e["type"] == "status" for e in evs)


def test_events_missing_session_404():
    with TestClient(app) as c:
        assert c.get(f"{API_PREFIX}/sessions/nope/events").status_code == 404


def test_cancel_session_sets_idle_and_emits():
    with TestClient(app) as c:
        sid = _new_session(c)
        r = c.post(f"{API_PREFIX}/sessions/{sid}/cancel")
        assert r.status_code == 200
        assert c.get(f"{API_PREFIX}/sessions/{sid}").json()["status"] == "idle"
        evs = c.get(f"{API_PREFIX}/sessions/{sid}/events").json()
        assert any(e["type"] == "status" and "取消" in (e["payload"].get("note") or "") for e in evs)


def test_cancel_missing_session_404():
    with TestClient(app) as c:
        assert c.post(f"{API_PREFIX}/sessions/nope/cancel").status_code == 404
