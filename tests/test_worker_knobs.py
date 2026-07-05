"""F8 经验 — Worker 迭代上限/超时旋钮环境变量化(默认与原值一致)。"""
from api.events import EventBus
from api.session import SessionStore
from executor.openhands_worker import OpenHandsWorker


def _worker(**kw):
    return OpenHandsWorker("s", "t", EventBus(SessionStore()), **kw)


def test_defaults_unchanged(monkeypatch):
    monkeypatch.delenv("FLIPPED_WORKER_TIMEOUT", raising=False)
    monkeypatch.delenv("FLIPPED_WORKER_MAX_ITERATIONS", raising=False)
    w = _worker()
    assert w.timeout == 600.0
    assert w.max_iterations == 50


def test_env_overrides(monkeypatch):
    monkeypatch.setenv("FLIPPED_WORKER_TIMEOUT", "300")
    monkeypatch.setenv("FLIPPED_WORKER_MAX_ITERATIONS", "25")
    w = _worker()
    assert w.timeout == 300.0
    assert w.max_iterations == 25


def test_explicit_timeout_beats_env(monkeypatch):
    monkeypatch.setenv("FLIPPED_WORKER_TIMEOUT", "300")
    assert _worker(timeout=120.0).timeout == 120.0
