"""M190.2 · auto-generate 多源汇聚 + LLM 兜底 TDD 测试。

契约（PLAN.md M190.2）：
- main._collect_failure_texts：failure_kb 未解决 ∪ 全会话事件流 error 事件，
  dedup 保序，单源异常各自 fail-open，总量 cap limit*2。
- worker_rules.generate_auto_rules_llm：固定模板未命中时的 LLM 兜底。
  剥离 ```json 围栏解析 JSON array of str；strip 去重（existing + 候选内）；
  每条 ≤200 字符截断；FLIPPED_RULES_LLM=0 或任何异常 → []（fail-open）。
- 端点 /worker/rules/auto-generate：candidates 空且 texts 非空且开关开 → LLM 兜底；
  响应增 llm_used 字段。
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("FLIPPED_MOCK_ORCHESTRATOR", "1")
    monkeypatch.setattr("api.main.FLIPPED_CHECKPOINT_DB", str(tmp_path / "cp.db"))
    monkeypatch.setenv("FLIPPED_WORKER_RULES_PATH", str(tmp_path / "rules.json"))
    from api.main import app
    return TestClient(app)


def _emit_error(sid: str, message: str):
    from api.main import bus
    from api.schemas import EventType, Role
    return bus.emit(sid, EventType.error, Role.system, {"message": message})


def _new_session(client) -> str:
    return client.post("/api/v1/assistant/sessions", json={"title": "t"}).json()["id"]


# ====================================================================
# _collect_failure_texts：多源合并
# ====================================================================

def test_collect_merges_kb_and_error_events(client, monkeypatch):
    """failure_kb 两条 + 事件流 error 一条 → 合并保序去重。"""
    from api import main as m
    monkeypatch.setattr(m, "_recent_failure_texts", lambda limit=20: ["kb故障A", "kb故障B"])
    sid = _new_session(client)
    _emit_error(sid, "事件流故障C")
    texts = m._collect_failure_texts()
    assert "kb故障A" in texts and "kb故障B" in texts
    assert "事件流故障C" in texts
    # 保序：kb 在前，事件流在后
    assert texts.index("kb故障A") < texts.index("事件流故障C")


def test_collect_dedup_same_text(client, monkeypatch):
    """kb 与事件流相同文本只出现一次。"""
    from api import main as m
    monkeypatch.setattr(m, "_recent_failure_texts", lambda limit=20: ["相同故障"])
    sid = _new_session(client)
    _emit_error(sid, "相同故障")
    texts = m._collect_failure_texts()
    assert texts.count("相同故障") == 1


def test_collect_kb_failure_fails_open(client, monkeypatch):
    """failure_kb 源异常 → 仍返回事件流文本（单源 fail-open）。"""
    from api import main as m

    def _boom(limit=20):
        raise RuntimeError("kb corrupted")

    monkeypatch.setattr(m, "_recent_failure_texts", _boom)
    sid = _new_session(client)
    _emit_error(sid, "事件流故障X")
    texts = m._collect_failure_texts()
    assert texts == ["事件流故障X"]


def test_collect_event_scan_failure_fails_open(client, monkeypatch):
    """事件流扫描异常 → 仍返回 kb 文本（单源 fail-open）。"""
    from api import main as m
    monkeypatch.setattr(m, "_recent_failure_texts", lambda limit=20: ["kb故障Y"])

    class _BoomStore:
        def list(self):
            raise RuntimeError("store corrupted")

    monkeypatch.setattr(m, "store", _BoomStore())
    texts = m._collect_failure_texts()
    assert texts == ["kb故障Y"]


def test_collect_caps_at_limit_times_2(client, monkeypatch):
    """总量 cap limit*2。"""
    from api import main as m
    monkeypatch.setattr(m, "_recent_failure_texts",
                        lambda limit=20: [f"kb-{i}" for i in range(30)])
    sid = _new_session(client)
    for i in range(30):
        _emit_error(sid, f"ev-{i}")
    texts = m._collect_failure_texts(limit=20)
    assert len(texts) <= 40


# ====================================================================
# generate_auto_rules_llm：解析 / 去重 / 截断 / 开关 / fail-open
# ====================================================================

def _existing(texts):
    from driving.worker_rules import WorkerRule
    return [WorkerRule(id=f"r-{i}", text=t) for i, t in enumerate(texts)]


def test_llm_parses_json_array_with_fence(monkeypatch):
    """剥离 ```json 围栏后解析；返回规则文本。"""
    import driving.worker_rules as wr
    monkeypatch.delenv("FLIPPED_RULES_LLM", raising=False)
    monkeypatch.setattr(wr, "_llm_complete",
                        lambda prompt: '```json\n["规则甲", "规则乙"]\n```')
    out = wr.generate_auto_rules_llm(["某故障"], _existing([]))
    assert out == ["规则甲", "规则乙"]


def test_llm_parses_bare_json_array(monkeypatch):
    """无围栏纯 JSON 数组也可解析。"""
    import driving.worker_rules as wr
    monkeypatch.delenv("FLIPPED_RULES_LLM", raising=False)
    monkeypatch.setattr(wr, "_llm_complete", lambda prompt: '["规则丙"]')
    assert wr.generate_auto_rules_llm(["某故障"], _existing([])) == ["规则丙"]


def test_llm_dedup_against_existing_and_self(monkeypatch):
    """与 existing 重复、候选内重复均被去重。"""
    import driving.worker_rules as wr
    monkeypatch.delenv("FLIPPED_RULES_LLM", raising=False)
    monkeypatch.setattr(wr, "_llm_complete",
                        lambda prompt: '["已存在规则", "新规则", "新规则", " 已存在规则 "]')
    out = wr.generate_auto_rules_llm(["某故障"], _existing(["已存在规则"]))
    assert out == ["新规则"]


def test_llm_truncates_overlong_rules(monkeypatch):
    """每条 >200 字符截断到 200。"""
    import driving.worker_rules as wr
    monkeypatch.delenv("FLIPPED_RULES_LLM", raising=False)
    monkeypatch.setattr(wr, "_llm_complete", lambda prompt: '["' + "长" * 300 + '"]')
    out = wr.generate_auto_rules_llm(["某故障"], _existing([]))
    assert len(out) == 1 and len(out[0]) == 200


def test_llm_respects_max_rules(monkeypatch):
    """候选超过 max_rules 时截断条数。"""
    import driving.worker_rules as wr
    monkeypatch.delenv("FLIPPED_RULES_LLM", raising=False)
    monkeypatch.setattr(wr, "_llm_complete",
                        lambda prompt: '["r1", "r2", "r3", "r4", "r5"]')
    out = wr.generate_auto_rules_llm(["某故障"], _existing([]), max_rules=2)
    assert out == ["r1", "r2"]


def test_llm_disabled_by_env_switch(monkeypatch):
    """FLIPPED_RULES_LLM=0 → [] 且不发起 LLM 调用。"""
    import driving.worker_rules as wr
    monkeypatch.setenv("FLIPPED_RULES_LLM", "0")
    calls = {"n": 0}

    def _spy(prompt):
        calls["n"] += 1
        return '["x"]'

    monkeypatch.setattr(wr, "_llm_complete", _spy)
    assert wr.generate_auto_rules_llm(["某故障"], _existing([])) == []
    assert calls["n"] == 0


def test_llm_empty_failure_texts_returns_empty(monkeypatch):
    """无失败文本 → []（不浪费 LLM 调用）。"""
    import driving.worker_rules as wr
    monkeypatch.delenv("FLIPPED_RULES_LLM", raising=False)
    calls = {"n": 0}
    monkeypatch.setattr(wr, "_llm_complete",
                        lambda p: calls.__setitem__("n", calls["n"] + 1) or '["x"]')
    assert wr.generate_auto_rules_llm([], _existing([])) == []
    assert calls["n"] == 0


@pytest.mark.parametrize("bad", [
    "not json at all",
    '{"rules": ["x"]}',          # 非数组
    '["ok", 123, {"x": 1}]',     # 非字符串项被过滤 → ["ok"]
])
def test_llm_malformed_output_fails_open(monkeypatch, bad):
    """LLM 输出非法 → 非字符串项过滤；完全非法 → []。"""
    import driving.worker_rules as wr
    monkeypatch.delenv("FLIPPED_RULES_LLM", raising=False)
    monkeypatch.setattr(wr, "_llm_complete", lambda prompt: bad)
    out = wr.generate_auto_rules_llm(["某故障"], _existing([]))
    if bad == '["ok", 123, {"x": 1}]':
        assert out == ["ok"]
    else:
        assert out == []


def test_llm_http_exception_fails_open(monkeypatch):
    """LLM 调用抛异常 → []。"""
    import driving.worker_rules as wr
    monkeypatch.delenv("FLIPPED_RULES_LLM", raising=False)

    def _boom(prompt):
        raise ConnectionError("llm down")

    monkeypatch.setattr(wr, "_llm_complete", _boom)
    assert wr.generate_auto_rules_llm(["某故障"], _existing([])) == []


# ====================================================================
# 端点：LLM 兜底通路 + llm_used 字段
# ====================================================================

def test_endpoint_llm_fallback_when_no_template_hit(client, monkeypatch):
    """显式 failure_texts 无 regex 命中 → LLM 兜底产候选入库，llm_used=True。"""
    import driving.worker_rules as wr
    monkeypatch.delenv("FLIPPED_RULES_LLM", raising=False)
    monkeypatch.setattr(wr, "_llm_complete", lambda prompt: '["LLM生成的兜底规则"]')
    r = client.post("/api/v1/worker/rules/auto-generate",
                    json={"failure_texts": ["某种模板未覆盖的诡异失败"]})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["llm_used"] is True
    assert [a["text"] for a in data["added"]] == ["LLM生成的兜底规则"]
    assert data["candidates"] == 1


def test_endpoint_no_llm_when_template_hits(client, monkeypatch):
    """固定模板已命中 → 不调 LLM，llm_used=False。"""
    import driving.worker_rules as wr
    monkeypatch.delenv("FLIPPED_RULES_LLM", raising=False)
    calls = {"n": 0}
    monkeypatch.setattr(wr, "_llm_complete",
                        lambda p: calls.__setitem__("n", calls["n"] + 1) or '["x"]')
    r = client.post("/api/v1/worker/rules/auto-generate",
                    json={"failure_texts": ["test failed badly"]})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["llm_used"] is False
    assert data["candidates"] >= 1
    assert calls["n"] == 0


def test_endpoint_llm_disabled_returns_empty(client, monkeypatch):
    """FLIPPED_RULES_LLM=0 且模板未命中 → added=[] llm_used=False。"""
    monkeypatch.setenv("FLIPPED_RULES_LLM", "0")
    r = client.post("/api/v1/worker/rules/auto-generate",
                    json={"failure_texts": ["某种模板未覆盖的诡异失败"]})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["added"] == [] and data["llm_used"] is False


def test_endpoint_llm_empty_result_llm_used_false(client, monkeypatch):
    """LLM 兜底被触发但返回空 → llm_used=False，added=[]。"""
    import driving.worker_rules as wr
    monkeypatch.delenv("FLIPPED_RULES_LLM", raising=False)
    monkeypatch.setattr(wr, "_llm_complete", lambda prompt: "garbage")
    r = client.post("/api/v1/worker/rules/auto-generate",
                    json={"failure_texts": ["某种模板未覆盖的诡异失败"]})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["added"] == [] and data["llm_used"] is False
