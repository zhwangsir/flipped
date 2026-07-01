"""Crash recovery tests for the orchestrator checkpoint / resume flow (M5.4)."""
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from langgraph.checkpoint.sqlite import SqliteSaver  # noqa: E402

from driving.orchestrator import build_orchestrator, resume_orchestrated  # noqa: E402


def _build_stateful_fns():
    """Return supervisor/worker/overseer/verifier closures that remember progress."""
    verify_count = [0]

    def supervisor(state):
        count = len([h for h in state.get("history", []) if h.get("step") == "supervisor"])
        done = (count == 1)
        return {
            "current_subtask": f"sub{count}",
            "believe_done": done,
            "history": state.get("history", []) + [{"step": "supervisor", "subtask": f"sub{count}"}],
        }

    def worker(state):
        i = len([h for h in state.get("history", []) if h.get("step") == "worker"])
        return {
            "last_obs": {"summary": {"tool_calls": 1}},
            "signatures": state.get("signatures", []) + [f"sig{i}"],
            "history": state.get("history", []) + [{"step": "worker", "i": i}],
        }

    def overseer(state):
        return {
            "verdict": {"action": "continue"},
            "history": state.get("history", []) + [{"step": "overseer"}],
        }

    def verifier(cmd, cwd):
        verify_count[0] += 1
        return verify_count[0] == 2, ("fail" if verify_count[0] == 1 else "ok")

    return supervisor, worker, overseer, verifier


def test_resume_from_partial_run_reaches_verified(tmp_path: Path):
    """Simulate a crash after the first supervisor step and resume to verified."""
    db_path = str(tmp_path / "recovery.db")
    supervisor, worker, overseer, verifier = _build_stateful_fns()

    initial = {
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

    with SqliteSaver.from_conn_string(db_path) as cp:
        graph = build_orchestrator(
            supervisor, worker, overseer, verifier, checkpointer=cp
        )
        config = {"configurable": {"thread_id": "rec"}}
        # Run exactly one update (supervisor) and then stop, as if the process crashed.
        for _ in graph.stream(initial, config, stream_mode="updates"):
            break

    final = resume_orchestrated(
        "rec",
        db_path,
        supervisor=supervisor,
        worker=worker,
        overseer=overseer,
        verifier=verifier,
    )
    assert final is not None
    assert final["verified"] is True
    assert final["stop_reason"] == "verified"


def test_resume_returns_none_when_no_checkpoint(tmp_path: Path):
    db_path = str(tmp_path / "empty.db")
    supervisor, worker, overseer, verifier = _build_stateful_fns()
    assert resume_orchestrated(
        "missing",
        db_path,
        supervisor=supervisor,
        worker=worker,
        overseer=overseer,
        verifier=verifier,
    ) is None


def test_resume_returns_done_state_when_already_finished(tmp_path: Path):
    """If the checkpoint already has done=True, resume should return it as-is."""
    db_path = str(tmp_path / "finished.db")
    supervisor, worker, overseer, verifier = _build_stateful_fns()

    initial = {
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

    with SqliteSaver.from_conn_string(db_path) as cp:
        graph = build_orchestrator(
            supervisor, worker, overseer, verifier, checkpointer=cp
        )
        config = {"configurable": {"thread_id": "rec"}}
        # Run to completion: first verify fails, second supervisor believes done, verify passes.
        final = graph.invoke(initial, config)
        assert final["done"] is True

    resumed = resume_orchestrated(
        "rec",
        db_path,
        supervisor=supervisor,
        worker=worker,
        overseer=overseer,
        verifier=verifier,
    )
    assert resumed is not None
    assert resumed["done"] is True
