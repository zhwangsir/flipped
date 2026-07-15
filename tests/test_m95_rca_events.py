"""M95 — RCA 结果与 parallel_verifier SemanticVerdict 作为结构化 WS 事件发射。

测试覆盖:
1. EventType.rca / EventType.verifier_verdict 在枚举中存在
2. instrument_verifier 在 verify 失败时 emit rca 事件(结构化字段完整)
3. instrument_verifier 在 verify 通过时不 emit rca 事件
4. make_parallel_verifier 的 verdict_callback 在 GLM checked 时被调用
5. make_parallel_verifier 的 verdict_callback 在 GLM skip 时不被调用
6. /api/v1/rca/failure_counter 端点返回正确格式
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from api.schemas import EventType, Role
from api.orchestrator_stream import instrument_verifier
from driving.parallel_verifier import make_parallel_verifier
from driving.rca import reset_failure_counter


# ---------- 共用 mock bus ----------

class _FakeBus:
    def __init__(self):
        self.events: list[dict] = []

    def emit(self, session_id, type_, agent=None, payload=None, parent_id=None):
        self.events.append({
            "session_id": session_id, "type": type_,
            "agent": agent, "payload": payload or {},
        })

    def by_type(self, t: EventType) -> list[dict]:
        return [e for e in self.events if e["type"] == t]


# ---------- 1. 枚举存在 ----------

def test_event_type_rca_exists():
    assert EventType.rca == "rca"


def test_event_type_verifier_verdict_exists():
    assert EventType.verifier_verdict == "verifier_verdict"


def test_event_type_enum_has_both_new_members():
    members = {e.value for e in EventType}
    assert "rca" in members
    assert "verifier_verdict" in members


# ---------- 2/3. instrument_verifier emit RCA ----------

@pytest.fixture(autouse=True)
def _reset_rca_counter():
    """每个测试前后重置 RCA 全局失败计数器,避免交叉污染。"""
    reset_failure_counter()
    yield
    reset_failure_counter()


def test_instrument_verifier_emits_rca_on_failure():
    """verify 失败 → emit 一条 EventType.rca 事件,字段完整。"""
    bus = _FakeBus()
    base = lambda cmd, cwd: (False, "AssertionError: assert 1 == 2")
    ver = instrument_verifier(bus, "sess-m95", base)
    ok, _ = ver(["pytest", "-q"], "/projects/demo")
    assert ok is False
    rca_events = bus.by_type(EventType.rca)
    assert len(rca_events) == 1, "失败时应 emit 恰好一条 rca 事件"
    ev = rca_events[0]
    assert ev["session_id"] == "sess-m95"
    assert ev["agent"] == Role.overseer
    p = ev["payload"]
    # 结构化字段齐全
    assert "cause" in p and isinstance(p["cause"], str)
    assert "confidence" in p and isinstance(p["confidence"], (int, float))
    assert "detail" in p
    assert "fix_suggestion" in p
    assert "history_hint" in p
    assert "related_rules" in p and isinstance(p["related_rules"], list)
    assert "failure_counter" in p and isinstance(p["failure_counter"], dict)
    # AssertionError → verify_mismatch 根因
    assert p["cause"] == "verify_mismatch"


def test_instrument_verifier_no_rca_on_success():
    """verify 通过 → 不 emit rca 事件。"""
    bus = _FakeBus()
    base = lambda cmd, cwd: (True, "3 passed")
    ver = instrument_verifier(bus, "sess-m95", base)
    ver(["pytest", "-q"], "/projects/demo")
    assert bus.by_type(EventType.rca) == [], "通过时不应 emit rca 事件"


def test_instrument_verifier_rca_fail_open():
    """RCA 抛异常时不影响主流程(仍返回 base 结果,不 emit rca)。"""
    bus = _FakeBus()
    base = lambda cmd, cwd: (False, "boom")
    ver = instrument_verifier(bus, "s1", base)
    with patch("driving.rca.analyze_failure_with_memory", side_effect=RuntimeError("rca broke")):
        ok, output = ver(["pytest"], "/x")
    assert ok is False and output == "boom"
    assert bus.by_type(EventType.rca) == [], "RCA 异常时 fail-open,不 emit rca"


def test_instrument_verifier_rca_payload_has_failure_counter():
    """rca 事件 payload 的 failure_counter 反映连续失败计数。"""
    bus = _FakeBus()
    base = lambda cmd, cwd: (False, "SyntaxError: unexpected indent")
    ver = instrument_verifier(bus, "s1", base)
    ver(["pytest"], "/x")
    rca_ev = bus.by_type(EventType.rca)[0]
    counter = rca_ev["payload"]["failure_counter"]
    # 一次 SyntaxError 失败 → counter 中 syntax_error=1
    assert counter.get("syntax_error") == 1


def test_instrument_verifier_still_returns_base_result():
    """包装后仍透传 base 的 (ok, output) 返回值。"""
    bus = _FakeBus()
    base = lambda cmd, cwd: (False, "fail-output")
    ver = instrument_verifier(bus, "s1", base)
    ok, output = ver(["make", "test"], "/projects/x")
    assert ok is False
    assert output == "fail-output"
    # 同时仍 emit verify 消息(原有功能不破坏)
    assert len(bus.by_type(EventType.message)) == 1


# ---------- 4/5. make_parallel_verifier verdict_callback ----------

def _fake_glm_post(content: str):
    """构造一个返回给定 content 的 fake httpx.post。"""
    def fake_post(url, **kwargs):
        class R:
            status_code = 200
            def raise_for_status(self): pass
            def json(self):
                return {"choices": [{"message": {"content": content}}]}
        return R()
    return fake_post


def test_verdict_callback_called_when_glm_checked(tmp_path):
    """GLM 真正执行验证(checked=True)时,verdict_callback 被调用。"""
    (tmp_path / "index.html").write_text("<html></html>", encoding="utf-8")
    captured: list = []

    def cb(verdict):
        captured.append(verdict)

    def base_ok(cmd, cwd):
        return True, "det: ok"

    with patch("driving.parallel_verifier.resolve_model_config",
               return_value=("http://fake/v1", "fake")):
        with patch("httpx.post",
                   side_effect=_fake_glm_post('{"severity":"warning","issues":["minor"],"rationale":"ok"}')):
            verifier = make_parallel_verifier(base_ok, glm_timeout=5, verdict_callback=cb)
            verifier([], str(tmp_path))
    assert len(captured) == 1, "GLM checked 时 callback 应被调用一次"
    v = captured[0]
    assert v.checked is True
    assert v.severity == "warning"
    assert "minor" in v.issues[0]


def test_verdict_callback_not_called_when_glm_skipped(tmp_path):
    """GLM 跳过(checked=False)时,verdict_callback 不被调用。"""
    (tmp_path / "index.html").write_text("<html></html>", encoding="utf-8")
    captured: list = []

    def cb(verdict):
        captured.append(verdict)

    def base_ok(cmd, cwd):
        return True, "det: ok"

    def fake_post(url, **kwargs):
        raise Exception("GLM unavailable")  # → fail-open, checked=False

    with patch("driving.parallel_verifier.resolve_model_config",
               return_value=("http://fake/v1", "fake")):
        with patch("httpx.post", side_effect=fake_post):
            verifier = make_parallel_verifier(base_ok, glm_timeout=5, verdict_callback=cb)
            ok, _ = verifier([], str(tmp_path))
    assert ok is True  # fail-open
    assert captured == [], "GLM skip 时 callback 不应被调用"


def test_verdict_callback_none_by_default(tmp_path):
    """不传 verdict_callback 时(默认 None)正常运行,向后兼容。"""
    (tmp_path / "index.html").write_text("<html></html>", encoding="utf-8")

    def base_ok(cmd, cwd):
        return True, "det: ok"

    with patch("driving.parallel_verifier.resolve_model_config",
               return_value=("http://fake/v1", "fake")):
        with patch("httpx.post",
                   side_effect=_fake_glm_post('{"severity":"ok","issues":[]}')):
            verifier = make_parallel_verifier(base_ok, glm_timeout=5)
            ok, msg = verifier([], str(tmp_path))
    assert ok is True
    assert "glm_semantic 通过" in msg


def test_verdict_callback_blocker_still_emitted(tmp_path):
    """GLM blocker 时 callback 也被调用(blocker 也是 checked=True)。"""
    (tmp_path / "index.html").write_text("<html></html>", encoding="utf-8")
    captured: list = []

    def cb(verdict):
        captured.append(verdict)

    def base_ok(cmd, cwd):
        return True, "det: ok"

    with patch("driving.parallel_verifier.resolve_model_config",
               return_value=("http://fake/v1", "fake")):
        with patch("httpx.post", side_effect=_fake_glm_post(
                '{"severity":"blocker","issues":["missing alt"],"rationale":"a11y broken"}')):
            verifier = make_parallel_verifier(base_ok, glm_timeout=5, verdict_callback=cb)
            ok, _ = verifier([], str(tmp_path))
    assert ok is False  # blocker 阻断
    assert len(captured) == 1
    assert captured[0].is_blocker


def test_verdict_callback_exception_fail_open(tmp_path):
    """callback 抛异常时不影响验证主流程(fail-open)。"""
    (tmp_path / "index.html").write_text("<html></html>", encoding="utf-8")

    def cb(verdict):
        raise RuntimeError("callback broke")

    def base_ok(cmd, cwd):
        return True, "det: ok"

    with patch("driving.parallel_verifier.resolve_model_config",
               return_value=("http://fake/v1", "fake")):
        with patch("httpx.post",
                   side_effect=_fake_glm_post('{"severity":"ok","issues":[]}')):
            verifier = make_parallel_verifier(base_ok, glm_timeout=5, verdict_callback=cb)
            ok, msg = verifier([], str(tmp_path))
    assert ok is True, "callback 异常不应翻转验证结果"


# ---------- 6. /api/v1/rca/failure_counter 端点 ----------

def test_failure_counter_endpoint_format():
    """/rca/failure_counter 返回 {"counter": {<cause>: <int>}} 格式。"""
    from fastapi.testclient import TestClient
    from api.main import API_PREFIX, app

    reset_failure_counter()
    with TestClient(app) as c:
        r = c.get(f"{API_PREFIX}/rca/failure_counter")
    assert r.status_code == 200
    body = r.json()
    assert "counter" in body
    assert isinstance(body["counter"], dict)


def test_failure_counter_endpoint_reflects_failures():
    """触发失败后端点计数器反映失败次数。"""
    from fastapi.testclient import TestClient
    from api.main import API_PREFIX, app
    from driving.rca import analyze_failure

    reset_failure_counter()
    # 触发 2 次 syntax_error 失败
    analyze_failure(summary="SyntaxError: line 1")
    analyze_failure(summary="SyntaxError: line 2")
    with TestClient(app) as c:
        r = c.get(f"{API_PREFIX}/rca/failure_counter")
    body = r.json()
    assert body["counter"].get("syntax_error") == 2


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
