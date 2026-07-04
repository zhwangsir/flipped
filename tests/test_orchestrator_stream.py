"""F2 — orchestrator 实时事件流桥接(注入假 bus/base 节点,无需 LLM/沙盒)。"""
from api.schemas import EventType, Role
from api.orchestrator_stream import (
    build_streaming_nodes,
    instrument_overseer,
    instrument_supervisor,
    instrument_verifier,
)


class _FakeBus:
    def __init__(self):
        self.events = []

    def emit(self, session_id, type_, agent=None, payload=None, parent_id=None):
        self.events.append({"session_id": session_id, "type": type_,
                            "agent": agent, "payload": payload or {}})


def test_supervisor_emits_subtask_and_passes_through():
    bus = _FakeBus()
    base = lambda state: {"current_subtask": "写 app.py", "believe_done": False}
    sup = instrument_supervisor(bus, "s1", base=base)
    upd = sup({"goal": "g"})
    # 透传 base 的产出
    assert upd["current_subtask"] == "写 app.py"
    # emit 了一条 supervisor 消息
    assert len(bus.events) == 1
    ev = bus.events[0]
    assert ev["session_id"] == "s1"
    assert ev["type"] == EventType.message
    assert ev["agent"] == Role.supervisor
    assert "写 app.py" in ev["payload"]["text"]
    assert ev["payload"]["believe_done"] is False


def test_supervisor_believe_done_message():
    bus = _FakeBus()
    base = lambda state: {"current_subtask": "", "believe_done": True}
    sup = instrument_supervisor(bus, "s1", base=base)
    sup({"goal": "g"})
    assert "已达成" in bus.events[0]["payload"]["text"]
    assert bus.events[0]["payload"]["believe_done"] is True


def test_overseer_emits_verdict():
    bus = _FakeBus()
    verdict = {"action": "continue", "efficiency": 0.9, "direction": 1.0, "rationale": "方向正确"}
    base = lambda state: {"verdict": verdict}
    over = instrument_overseer(bus, "s1", base=base)
    upd = over({"goal": "g"})
    assert upd["verdict"] == verdict
    ev = bus.events[0]
    assert ev["agent"] == Role.overseer
    assert ev["payload"]["verdict"] == verdict
    assert ev["payload"]["text"] == "方向正确"


def test_verifier_emits_pass():
    bus = _FakeBus()
    base = lambda cmd, cwd: (True, "3 passed")
    ver = instrument_verifier(bus, "s1", base)
    ok, output = ver(["pytest", "-q"], "/projects/demo")
    assert ok is True and output == "3 passed"
    ev = bus.events[0]
    assert ev["agent"] == Role.verify
    assert ev["payload"]["ok"] is True
    assert "✓" in ev["payload"]["text"]
    assert ev["payload"]["command"] == "pytest -q"


def test_verifier_emits_fail_with_output_tail():
    bus = _FakeBus()
    long_out = "E" * 5000
    base = lambda cmd, cwd: (False, long_out)
    ver = instrument_verifier(bus, "s1", base)
    ok, _ = ver(["pytest"], "/projects/demo")
    assert ok is False
    payload = bus.events[0]["payload"]
    assert payload["ok"] is False
    assert "✗" in payload["text"]
    # 只保留尾部,避免超大输出灌爆事件流
    assert len(payload["output"]) <= 1000


def test_build_streaming_nodes_shape():
    bus = _FakeBus()
    base_verifier = lambda cmd, cwd: (True, "")
    nodes = build_streaming_nodes(bus, "s1", base_verifier)
    assert set(nodes) == {"supervisor", "worker", "overseer", "verifier"}
    assert all(callable(v) for v in nodes.values())


def test_streaming_verifier_still_runs_base():
    # 包装后仍真正调用 base verifier 并返回其结果
    bus = _FakeBus()
    calls = []
    def base(cmd, cwd):
        calls.append((cmd, cwd))
        return False, "boom"
    nodes = build_streaming_nodes(bus, "s1", base)
    ok, output = nodes["verifier"](["make", "test"], "/projects/x")
    assert ok is False and output == "boom"
    assert calls == [(["make", "test"], "/projects/x")]
