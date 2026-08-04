"""M169.1 · 后端 token 用量采集与折叠 TDD 测试（对标 opencode per-turn usage）。

覆盖：
1. _llm_chat 返回 (content, usage) tuple；响应无 usage → (content, None)
2. _llm_chat_stream 捕获 choices=[] 的 usage chunk 写进 usage_box（不 yield）；
   无 usage chunk → usage_box 保持空；payload 带 stream_options.include_usage
3. _run_chat 流式路径：message 后紧随 EventType.usage（prompt/completion/calls=1/
   source=mode），token transient 序列不被破坏
4. _run_chat 非流式路径（FLIPPED_CHAT_STREAM=0）：同样发射 usage
5. _run_chat 响应无 usage → 不发 usage 事件，message 照常
6. _run_chat 喂 COLLECTOR.record_usage（补全局计数漏 chat/plan 的缺口）
7. _events_to_turns：usage 合并进最近 assistant turn；连续两个累加；
   无前置 assistant turn → 丢弃不报错；user turn 不带 usage
8. openhands_worker 收尾发射 EventType.usage（与 COLLECTOR 同 try/except，绝不影响任务）
9. history 端点集成：message+usage 事件 → GET history → turn.usage 出现在响应 JSON

测试风格沿用既有套件（test_m166_token_stream.py）：同步测试函数 + asyncio.run。
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from types import SimpleNamespace

import httpx

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from api.events import EventBus  # noqa: E402
from api.schemas import Event, EventType, Role, SessionStatus  # noqa: E402
from api.session import SessionStore  # noqa: E402
from executor import openhands_worker as ohw_mod  # noqa: E402
from executor.openhands_worker import OpenHandsWorker  # noqa: E402


# ---------- 测试辅助（同 test_m166_token_stream.py 模式） ----------

def _run(coro):
    """asyncio.run 跑 coroutine，并 drain bus.emit 里 create_task 调度的 publish。"""
    async def _wrap():
        await coro
        await asyncio.sleep(0)
        await asyncio.sleep(0)
    return asyncio.run(_wrap())


def _patch_resolve(monkeypatch):
    """_run_chat 函数体内 lazy import resolve_worker_model_config → patch 源头模块即可。"""
    monkeypatch.setattr(
        "driving.model_router.resolve_worker_model_config",
        lambda alias="coder": ("http://fake.test/v1", "fake-model"),
    )


def _patch_publish(monkeypatch):
    """api.main.bus.publish → 记录全部广播（落盘事件与 transient 事件都过 publish）。"""
    import api.main as main
    published: list = []

    async def _rec(session_id, event):
        published.append(event)

    monkeypatch.setattr(main.bus, "publish", _rec)
    return published


def _patch_httpx_transport(monkeypatch, handler):
    """httpx.AsyncClient 注入 MockTransport（生产代码内部自建 client，经类替换注入）。"""
    transport = httpx.MockTransport(handler)
    real_client = httpx.AsyncClient

    def _factory(*args, **kwargs):
        kwargs["transport"] = transport
        return real_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", _factory)


# ---------- 1 · _llm_chat 返回 (content, usage) ----------

def test_llm_chat_returns_content_and_usage(monkeypatch):
    """响应含 usage{prompt_tokens,completion_tokens} → 返回 (content, usage_dict)。"""
    from api.main import _llm_chat

    def _handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/chat/completions"
        body = json.loads(request.content.decode())
        assert body["stream"] is False
        return httpx.Response(200, json={
            "choices": [{"message": {"content": "你好"}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 20},
        })

    _patch_httpx_transport(monkeypatch, _handler)

    content, usage = asyncio.run(_llm_chat("http://fake.test/v1", "m", "sys", "hi"))
    assert content == "你好"
    assert usage == {"prompt_tokens": 10, "completion_tokens": 20}


def test_llm_chat_returns_none_usage_when_missing(monkeypatch):
    """响应无 usage 字段 → (content, None)。"""
    from api.main import _llm_chat

    def _handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "choices": [{"message": {"content": "答"}}],
        })

    _patch_httpx_transport(monkeypatch, _handler)

    content, usage = asyncio.run(_llm_chat("http://fake.test/v1", "m", "sys", "hi"))
    assert content == "答"
    assert usage is None


# ---------- 2 · _llm_chat_stream 捕获 usage chunk ----------

def test_llm_chat_stream_captures_usage_chunk(monkeypatch):
    """SSE：2 个内容 chunk + choices=[] 带 usage 的 chunk + [DONE]
    → yield 2 段文本 + usage_box["usage"] 正确；payload 带 stream_options.include_usage。"""
    from api.main import _llm_chat_stream

    sse_body = (
        'data: {"choices":[{"delta":{"content":"你"}}]}\n\n'
        'data: {"choices":[{"delta":{"content":"好"}}]}\n\n'
        'data: {"choices":[],"usage":{"prompt_tokens":11,"completion_tokens":22}}\n\n'
        "data: [DONE]\n\n"
    )

    def _handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode())
        assert body["stream"] is True
        assert body["stream_options"] == {"include_usage": True}
        return httpx.Response(200, content=sse_body.encode())

    _patch_httpx_transport(monkeypatch, _handler)

    box: dict = {}

    async def _collect():
        return [c async for c in _llm_chat_stream(
            "http://fake.test/v1", "m", "sys", "hi", usage_box=box)]

    assert asyncio.run(_collect()) == ["你", "好"]
    assert box["usage"] == {"prompt_tokens": 11, "completion_tokens": 22}


def test_llm_chat_stream_without_usage_chunk_leaves_box_empty(monkeypatch):
    """SSE 无 usage chunk → usage_box 保持空，文本照常 yield。"""
    from api.main import _llm_chat_stream

    sse_body = (
        'data: {"choices":[{"delta":{"content":"你"}}]}\n\n'
        "data: [DONE]\n\n"
    )

    def _handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=sse_body.encode())

    _patch_httpx_transport(monkeypatch, _handler)

    box: dict = {}

    async def _collect():
        return [c async for c in _llm_chat_stream(
            "http://fake.test/v1", "m", "sys", "hi", usage_box=box)]

    assert asyncio.run(_collect()) == ["你"]
    assert box == {}


# ---------- 3 · _run_chat 流式路径发射 usage ----------

def test_run_chat_stream_emits_usage_after_message(monkeypatch):
    """流式成功：token seq1..2(done=false) + token(done=true) → message → usage → status done。"""
    import api.main as main

    monkeypatch.delenv("FLIPPED_CHAT_STREAM", raising=False)
    _patch_resolve(monkeypatch)
    published = _patch_publish(monkeypatch)

    def _fake_stream(base_url, model, system, user, timeout=120.0, usage_box=None):
        async def _gen():
            yield "你好"
            yield "世界"
            if usage_box is not None:
                usage_box["usage"] = {"prompt_tokens": 30, "completion_tokens": 40}
        return _gen()

    async def _no_fallback(*a, **kw):
        raise AssertionError("流式成功不应触碰非流式 _llm_chat")

    monkeypatch.setattr(main, "_llm_chat_stream", _fake_stream)
    monkeypatch.setattr(main, "_llm_chat", _no_fallback)

    sid = main.store.create("m169-stream", mode="chat").id
    _run(main._run_chat(sid, "task-1", "hello", "coder", "chat"))

    # 落盘序列：message 后紧随 usage，再 status done
    events = main.store.events(sid)
    mi = next(i for i, e in enumerate(events)
              if e.type == EventType.message and e.agent == Role.worker)
    assert events[mi].payload["text"] == "你好世界"
    assert events[mi + 1].type == EventType.usage
    assert events[mi + 1].agent == Role.worker
    assert events[mi + 1].payload == {
        "prompt": 30, "completion": 40, "calls": 1, "source": "chat"}
    assert events[mi + 2].type == EventType.status
    assert events[mi + 2].payload["status"] == "done"

    # token transient 序列不被破坏
    tokens = [e for e in published if e.type == EventType.token]
    assert [t.payload for t in tokens] == [
        {"text": "你好", "seq": 1, "done": False},
        {"text": "世界", "seq": 2, "done": False},
        {"text": "", "seq": 3, "done": True},
    ]
    assert main.store.get(sid).status == SessionStatus.done


# ---------- 4 · _run_chat 非流式路径发射 usage ----------

def test_run_chat_nonstream_emits_usage(monkeypatch):
    """FLIPPED_CHAT_STREAM=0 → 非流式 (reply, usage) → message + usage(source=plan) + done。"""
    import api.main as main

    monkeypatch.setenv("FLIPPED_CHAT_STREAM", "0")
    _patch_resolve(monkeypatch)
    _patch_publish(monkeypatch)

    async def _fake_chat(base_url, model, system, user, timeout=120.0):
        return "规划步骤", {"prompt_tokens": 5, "completion_tokens": 6}

    def _no_stream(*a, **kw):
        raise AssertionError("FLIPPED_CHAT_STREAM=0 不应走流式")

    monkeypatch.setattr(main, "_llm_chat", _fake_chat)
    monkeypatch.setattr(main, "_llm_chat_stream", _no_stream)

    sid = main.store.create("m169-nostream", mode="plan").id
    _run(main._run_chat(sid, "task-1", "goal", "coder", "plan"))

    events = main.store.events(sid)
    usages = [e for e in events if e.type == EventType.usage]
    assert len(usages) == 1
    assert usages[0].agent == Role.worker
    assert usages[0].payload == {"prompt": 5, "completion": 6, "calls": 1, "source": "plan"}
    msgs = [e for e in events if e.type == EventType.message and e.agent == Role.worker]
    assert [m.payload["text"] for m in msgs] == ["规划步骤"]
    assert main.store.get(sid).status == SessionStatus.done


# ---------- 5 · 响应无 usage → 不发 usage 事件 ----------

def test_run_chat_without_usage_emits_no_usage_event(monkeypatch):
    """非流式返回 (reply, None) → 无 usage 事件，message 照常 + status done。"""
    import api.main as main

    monkeypatch.setenv("FLIPPED_CHAT_STREAM", "0")
    _patch_resolve(monkeypatch)
    _patch_publish(monkeypatch)

    async def _fake_chat(base_url, model, system, user, timeout=120.0):
        return "回复", None

    monkeypatch.setattr(main, "_llm_chat", _fake_chat)

    sid = main.store.create("m169-nousage", mode="chat").id
    _run(main._run_chat(sid, "task-1", "hello", "coder", "chat"))

    events = main.store.events(sid)
    assert not any(e.type == EventType.usage for e in events)
    msgs = [e for e in events if e.type == EventType.message and e.agent == Role.worker]
    assert [m.payload["text"] for m in msgs] == ["回复"]
    assert main.store.get(sid).status == SessionStatus.done


# ---------- 6 · _run_chat 喂 COLLECTOR ----------

def test_run_chat_feeds_collector(monkeypatch):
    """有 usage → COLLECTOR.record_usage(prompt_tokens, completion_tokens, calls=1) 被调到。"""
    import api.main as main

    monkeypatch.setenv("FLIPPED_CHAT_STREAM", "0")
    _patch_resolve(monkeypatch)
    _patch_publish(monkeypatch)

    recorded: list = []
    monkeypatch.setattr(main.COLLECTOR, "record_usage", lambda **kw: recorded.append(kw))

    async def _fake_chat(base_url, model, system, user, timeout=120.0):
        return "回复", {"prompt_tokens": 7, "completion_tokens": 8}

    monkeypatch.setattr(main, "_llm_chat", _fake_chat)

    sid = main.store.create("m169-collector", mode="chat").id
    _run(main._run_chat(sid, "task-1", "hello", "coder", "chat"))

    assert recorded == [{"prompt_tokens": 7, "completion_tokens": 8, "calls": 1}]


# ---------- 7 · _events_to_turns 折叠 usage ----------

def _msg_ev(eid, agent, text):
    return Event(id=eid, session_id="s", type=EventType.message,
                 agent=agent, payload={"text": text})


def _usage_ev(eid, prompt, completion, calls):
    return Event(id=eid, session_id="s", type=EventType.usage,
                 agent=Role.worker,
                 payload={"prompt": prompt, "completion": completion,
                          "calls": calls, "source": "chat"})


def test_events_to_turns_merges_usage_into_last_assistant_turn():
    """message(assistant) + usage → 最近 assistant turn.usage 正确；不成独立 turn。"""
    from api.assistant import _events_to_turns

    evs = [
        _msg_ev("s-1", Role.user, "问"),
        _msg_ev("s-2", Role.worker, "答"),
        _usage_ev("s-3", 10, 20, 1),
    ]
    turns = _events_to_turns(evs)
    assert [t.role for t in turns] == ["user", "assistant"]
    assert turns[0].usage is None, "user turn 不带 usage"
    assert turns[1].usage == {"prompt": 10, "completion": 20, "calls": 1}


def test_events_to_turns_accumulates_multiple_usage_events():
    """同 turn 连续两个 usage 事件 → 累加（orchestrator 多子任务兜底）。"""
    from api.assistant import _events_to_turns

    evs = [
        _msg_ev("s-1", Role.worker, "答"),
        _usage_ev("s-2", 10, 20, 1),
        _usage_ev("s-3", 5, 5, 2),
    ]
    turns = _events_to_turns(evs)
    assert len(turns) == 1
    assert turns[0].usage == {"prompt": 15, "completion": 25, "calls": 3}


def test_events_to_turns_drops_usage_without_prior_assistant():
    """usage 前无 assistant turn（只有 user turn）→ 丢弃不报错。"""
    from api.assistant import _events_to_turns

    evs = [
        _msg_ev("s-1", Role.user, "问"),
        _usage_ev("s-2", 1, 2, 1),
    ]
    turns = _events_to_turns(evs)
    assert len(turns) == 1
    assert turns[0].role == "user"
    assert turns[0].usage is None


# ---------- 8 · openhands_worker 收尾发射 usage ----------

def test_worker_run_emits_usage_event(monkeypatch, tmp_path):
    """worker 收尾：_sum_conversation_usage=(100,40,2) → _emit EventType.usage
    {prompt,completion,calls,source=worker}（与 COLLECTOR 同 try/except）。"""
    monkeypatch.delenv("OPENHANDS_API_KEY", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("LITELLM_MASTER_KEY", "lm-key")
    monkeypatch.delenv("FLIPPED_WORKER_CONDENSER_ENABLED", raising=False)

    from openhands.sdk.conversation.state import ConversationExecutionStatus

    monkeypatch.setattr(ohw_mod, "LLM", lambda **kw: SimpleNamespace(**kw))
    monkeypatch.setattr(ohw_mod, "Agent", lambda **kw: SimpleNamespace(**kw))

    class _FakeWS:
        def __init__(self, **kw):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(ohw_mod, "RemoteWorkspace", _FakeWS)

    fake_state = SimpleNamespace(
        execution_status=ConversationExecutionStatus.FINISHED,
        events=[],
        stats=SimpleNamespace(usage_to_metrics={
            "kimi": SimpleNamespace(
                accumulated_token_usage=SimpleNamespace(
                    prompt_tokens=100, completion_tokens=40),
                token_usages=[SimpleNamespace(), SimpleNamespace()],
            ),
        }),
    )

    class _FakeConv:
        id = "conv-usage"

        def __init__(self, **kw):
            pass

        def send_message(self, desc, sender=None):
            pass

        def run(self, blocking=True, poll_interval=1.0, timeout=None):
            pass

        @property
        def state(self):
            return fake_state

    monkeypatch.setattr(ohw_mod, "RemoteConversation", _FakeConv)
    monkeypatch.setattr(ohw_mod, "audit_openhands_events", lambda events: [])
    monkeypatch.setattr(ohw_mod, "COLLECTOR", SimpleNamespace(record_usage=lambda **kw: None))

    bus = EventBus(SessionStore())
    sess_id = bus.store.create("usage task").id
    w = OpenHandsWorker(sess_id, "task-usage", bus, manage_session_status=True)
    result = w.run("干活")
    assert result["status"] == "ConversationExecutionStatus.FINISHED"

    usages = [e for e in bus.store.events(sess_id) if e.type == EventType.usage]
    assert len(usages) == 1
    assert usages[0].agent == Role.worker
    assert usages[0].payload == {
        "prompt": 100, "completion": 40, "calls": 2, "source": "worker"}


# ---------- 9 · history 端点集成 ----------

def test_history_endpoint_returns_turn_usage(monkeypatch, tmp_path):
    """造 session + message/usage 事件 → GET history → assistant turn 带 usage dict。"""
    monkeypatch.setenv("FLIPPED_MOCK_ORCHESTRATOR", "1")
    monkeypatch.setattr("api.main.FLIPPED_CHECKPOINT_DB", str(tmp_path / "cp.db"))
    from fastapi.testclient import TestClient

    from api.main import app, bus

    client = TestClient(app)
    sid = client.post("/api/v1/assistant/sessions",
                      json={"title": "t", "mode": "chat"}).json()["id"]
    bus.emit(sid, EventType.message, Role.user, {"text": "问"})
    bus.emit(sid, EventType.message, Role.worker, {"text": "答", "source": "agent"})
    bus.emit(sid, EventType.usage, Role.worker,
             {"prompt": 12, "completion": 34, "calls": 1, "source": "chat"})

    r = client.get(f"/api/v1/assistant/sessions/{sid}/history")
    assert r.status_code == 200, r.text
    turns = r.json()
    assert [t["role"] for t in turns] == ["user", "assistant"]
    assert turns[0]["usage"] is None
    assert turns[1]["usage"] == {"prompt": 12, "completion": 34, "calls": 1}
