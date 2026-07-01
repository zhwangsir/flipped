"""API-level crash recovery tests for M5.4."""
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from fastapi.testclient import TestClient  # noqa: E402
from langgraph.checkpoint.sqlite import SqliteSaver  # noqa: E402

from api.main import _mock_orchestrator_fns, app, store  # noqa: E402
from driving.orchestrator import build_orchestrator  # noqa: E402


def _initial_state():
    return {
        "goal": "G",
        "cwd": "/tmp",
        "verify_cmd": ["true"],
        "max_iterations": 4,
        "loop_threshold": 3,
        "iteration": 0,
        "signatures": [],
        "feedback": "",
        "verified": False,
        "done": False,
        "stop_reason": "",
        "history": [],
    }


def test_resume_endpoint_returns_404_for_missing_session():
    with TestClient(app) as client:
        resp = client.post("/api/v1/sessions/missing/resume")
    assert resp.status_code == 404


def test_resume_endpoint_returns_400_without_checkpoint():
    with TestClient(app) as client:
        created = client.post("/api/v1/sessions", params={"title": "no-checkpoint"})
        assert created.status_code == 200
        sid = created.json()["id"]
        resp = client.post(f"/api/v1/sessions/{sid}/resume")
        assert resp.status_code == 400


def test_resume_endpoint_recovers_from_checkpoint(tmp_path: Path, monkeypatch):
    with TestClient(app) as client:
        created = client.post("/api/v1/sessions", params={"title": "recover"})
        assert created.status_code == 200
        sid = created.json()["id"]

        db_path = str(tmp_path / f"{sid}.db")
        sup, work, over, ver = _mock_orchestrator_fns()

        # Simulate a crash after the first supervisor step, using the same thread_id as the API.
        with SqliteSaver.from_conn_string(db_path) as cp:
            graph = build_orchestrator(sup, work, over, ver, checkpointer=cp)
            config = {"configurable": {"thread_id": sid}}
            for _ in graph.stream(_initial_state(), config, stream_mode="updates"):
                break

        store.update(sid, checkpoint_db_path=db_path, goal="G", verify_cmd=["true"], cwd="/tmp")

        monkeypatch.setenv("FLIPPED_MOCK_ORCHESTRATOR", "1")
        resp = client.post(f"/api/v1/sessions/{sid}/resume")
        assert resp.status_code == 200

        # Poll until the background resume task finishes.
        final_status = "idle"
        for _ in range(50):
            session = client.get(f"/api/v1/sessions/{sid}")
            final_status = session.json()["status"]
            if final_status == "done":
                break
            time.sleep(0.05)
        assert final_status == "done"
