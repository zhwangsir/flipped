"""M170.1 · 编辑器直调 MCP 工具端点 TDD 测试。

覆盖：
1.  GET  /mcp/tools → 200，内省五项工具（每项含 name/description/inputSchema）
2.  快工具调用成功 → 200 {"ok": true, "tool", "result"}，run_tool 以正确 name/arguments 被调
3.  快工具异常 → 200 {"ok": false, "error"}（绝不 500）
4.  未知工具 → 404
5.  长工具缺 session_id → 400
6.  长工具会话不存在 → 404
7.  长工具 202 accepted → 完成后会话事件流出现 worker message（text 含 verified）
8.  长工具失败 → 会话事件流出现 error 事件（payload.message = str(e)）
9.  长工具注册进 RUNNING_TASKS（复用既有 /cancel 通路），结束后自动清理
10. GET /mcp/tools 内省失败 → 500 明示

mock 注入点：monkeypatch api.mcp_call.run_tool / list_tool_specs
（不 patch mcp_server.tools 本体——验证本模块自己的注入点）。

异步后台任务可测性方案：TestClient 必须 with 管理（portal 事件循环常驻，
端点里 asyncio.create_task 的后台任务跨请求存活，与 test_api_mode_mcp.py 既有
模式一致）；事件断言用 REST 轮询 /sessions/{id}/events，上限 2s；
test 9 用 threading.Event 门闩 + asyncio.to_thread 等待，跨线程安全无竞态。
"""
from __future__ import annotations

import asyncio
import threading
import time

import pytest
from fastapi.testclient import TestClient

API = "/api/v1"


@pytest.fixture()
def client(monkeypatch, tmp_path):
    """隔离 DB + mock orchestrator；with 管理 TestClient 保后台任务 portal 常驻。"""
    monkeypatch.setenv("FLIPPED_MOCK_ORCHESTRATOR", "1")
    monkeypatch.setattr("api.main.FLIPPED_CHECKPOINT_DB", str(tmp_path / "cp.db"))
    from api.main import app
    with TestClient(app) as c:
        yield c


def _new_session(client: TestClient) -> str:
    """走既有 assistant 端点造真实会话。"""
    r = client.post(f"{API}/assistant/sessions", json={"title": "mcp-test"})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _wait_event(client: TestClient, sid: str, predicate, timeout: float = 2.0) -> dict:
    """轮询会话事件流（REST 端点），直到 predicate 命中或超时。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = client.get(f"{API}/sessions/{sid}/events")
        assert r.status_code == 200, r.text
        for ev in r.json():
            if predicate(ev):
                return ev
        time.sleep(0.05)
    raise AssertionError("2s 内未等到目标事件")


# ---------- 1 · GET /mcp/tools ----------

def test_list_mcp_tools_returns_introspected_five(client):
    r = client.get(f"{API}/mcp/tools")
    assert r.status_code == 200, r.text
    tools = r.json()["tools"]
    assert isinstance(tools, list)
    names = {t["name"] for t in tools}
    assert {"web_search", "rag_query", "rag_ingest",
            "run_coding_task", "research_and_code"} <= names
    for t in tools:
        assert t["name"]
        assert isinstance(t["description"], str) and t["description"]
        assert isinstance(t["inputSchema"], dict)


# ---------- 2 · 快工具成功 ----------

def test_call_fast_tool_success_returns_result(client, monkeypatch):
    calls: dict = {}

    async def _fake_run_tool(name, arguments):
        calls["name"] = name
        calls["arguments"] = arguments
        return {"results": [{"title": "t", "url": "http://x"}], "formatted": "..."}

    monkeypatch.setattr("api.mcp_call.run_tool", _fake_run_tool)
    r = client.post(f"{API}/mcp/tools/web_search/call",
                    json={"arguments": {"query": "flipped", "max_results": 3}})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["ok"] is True
    assert data["tool"] == "web_search"
    assert data["result"] == {"results": [{"title": "t", "url": "http://x"}], "formatted": "..."}
    assert calls == {"name": "web_search", "arguments": {"query": "flipped", "max_results": 3}}


# ---------- 3 · 快工具异常 → 200 ok:false ----------

def test_call_fast_tool_error_returns_ok_false_not_500(client, monkeypatch):
    async def _boom(name, arguments):
        raise RuntimeError("searxng down")

    monkeypatch.setattr("api.mcp_call.run_tool", _boom)
    r = client.post(f"{API}/mcp/tools/rag_query/call", json={"arguments": {"query": "x"}})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["ok"] is False
    assert data["tool"] == "rag_query"
    assert "searxng down" in data["error"]


# ---------- 4 · 未知工具 → 404 ----------

def test_call_unknown_tool_returns_404(client):
    r = client.post(f"{API}/mcp/tools/nope/call", json={"arguments": {}})
    assert r.status_code == 404
    assert "nope" in r.json()["detail"]


# ---------- 5 · 长工具缺 session_id → 400 ----------

def test_call_long_tool_without_session_id_returns_400(client):
    r = client.post(f"{API}/mcp/tools/run_coding_task/call",
                    json={"arguments": {"goal": "x"}})
    assert r.status_code == 400


# ---------- 6 · 长工具会话不存在 → 404 ----------

def test_call_long_tool_unknown_session_returns_404(client):
    r = client.post(f"{API}/mcp/tools/research_and_code/call",
                    json={"arguments": {"research_query": "q", "coding_task": "c"},
                          "session_id": "sess-nope"})
    assert r.status_code == 404


# ---------- 7 · 长工具 202 → 完成回灌 worker message ----------

def test_call_long_tool_accepted_then_emits_worker_message(client, monkeypatch):
    calls: dict = {}

    async def _fake_run_tool(name, arguments):
        calls["name"] = name
        calls["arguments"] = arguments
        return {"verified": True, "stop_reason": "verified", "history": []}

    monkeypatch.setattr("api.mcp_call.run_tool", _fake_run_tool)
    sid = _new_session(client)
    r = client.post(f"{API}/mcp/tools/run_coding_task/call",
                    json={"arguments": {"goal": "写一个函数"}, "session_id": sid})
    assert r.status_code == 202, r.text
    data = r.json()
    assert data["ok"] is True
    assert data["accepted"] is True
    assert data["tool"] == "run_coding_task"
    assert data["session_id"] == sid

    ev = _wait_event(client, sid,
                     lambda e: e["type"] == "message" and e.get("agent") == "worker")
    assert "verified" in ev["payload"]["text"]
    # message 事件出现 ⇒ 后台任务已调过 run_tool（此前断言有竞态）
    assert calls == {"name": "run_coding_task", "arguments": {"goal": "写一个函数"}}


# ---------- 8 · 长工具失败 → error 事件 ----------

def test_call_long_tool_failure_emits_error_event(client, monkeypatch):
    async def _boom(name, arguments):
        raise RuntimeError("orchestrator blew up")

    monkeypatch.setattr("api.mcp_call.run_tool", _boom)
    sid = _new_session(client)
    r = client.post(f"{API}/mcp/tools/research_and_code/call",
                    json={"arguments": {"research_query": "q", "coding_task": "c"},
                          "session_id": sid})
    assert r.status_code == 202, r.text
    ev = _wait_event(client, sid, lambda e: e["type"] == "error")
    assert "orchestrator blew up" in ev["payload"]["message"]


# ---------- 9 · RUNNING_TASKS 注册 + 结束清理 ----------

def test_call_long_tool_registers_in_running_tasks_and_cleans_up(client, monkeypatch):
    gate = threading.Event()

    async def _gated_run_tool(name, arguments):
        # threading 门闩经 to_thread 等待：跨线程 set 安全，5s 兜底防泄漏
        await asyncio.to_thread(gate.wait, 5)
        return {"verified": True, "stop_reason": "verified"}

    monkeypatch.setattr("api.mcp_call.run_tool", _gated_run_tool)
    from api.main import RUNNING_TASKS

    sid = _new_session(client)
    r = client.post(f"{API}/mcp/tools/run_coding_task/call",
                    json={"arguments": {"goal": "x"}, "session_id": sid})
    assert r.status_code == 202, r.text
    # 注册发生在端点 return 之前 → 收到 202 时必然可见
    task = RUNNING_TASKS.get(sid)
    assert task is not None, "长工具任务应注册进 RUNNING_TASKS（供既有 /cancel 通路取消）"
    assert not task.done()

    gate.set()
    deadline = time.time() + 2
    while time.time() < deadline and sid in RUNNING_TASKS:
        time.sleep(0.05)
    assert sid not in RUNNING_TASKS, "任务结束后必须从 RUNNING_TASKS 清理"


# ---------- 10 · 内省失败 → 500 明示 ----------

def test_list_mcp_tools_introspection_failure_returns_500(client, monkeypatch):
    def _boom():
        raise RuntimeError("registry corrupted")

    monkeypatch.setattr("api.mcp_call.list_tool_specs", _boom)
    r = client.get(f"{API}/mcp/tools")
    assert r.status_code == 500
    assert "内省失败" in r.json()["detail"]
