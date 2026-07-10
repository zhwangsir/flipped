"""Shared pytest configuration for the flipped test suite."""
import os
import tempfile

import pytest

# Keep the in-memory session store backed by a temp file during tests so
# API tests don't leave .sessions.json in the project root.
_test_session_path = os.path.join(tempfile.gettempdir(), "flipped_test_sessions.json")
os.environ["FLIPPED_SESSION_STORE_PATH"] = _test_session_path
os.environ.setdefault("EXO_API_KEY", "dummy")
# M42: 测试中禁用默认 auto-proposer，避免不必要的 GLM 调用
os.environ.setdefault("FLIPPED_AUTO_PROPOSER", "0")
if os.path.exists(_test_session_path):
    os.remove(_test_session_path)


@pytest.fixture(autouse=True)
def _reset_session_store():
    """Clear the singleton SessionStore before/after each API test."""
    from api.session import store
    store._sessions.clear()
    store._events.clear()
    store._counter.clear()
    yield
    store._sessions.clear()
    store._events.clear()
    store._counter.clear()
