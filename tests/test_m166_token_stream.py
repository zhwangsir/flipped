"""M166 · chat/plan 直聊通路 token 级流式（后端 M166.1 + M166.2）。

契约（与前端钉死）：
- EventType.token，payload {text, seq, done}，agent=worker，transient 只广播不落盘。
- 流式序列：token{text, seq:1..N, done:false}* → token{text:"", done:true} → 既有 message 落盘。
- 建流失败（连不上/非 200/流式请求本身抛异常）→ 静默 fallback 非流式 _llm_chat（无 token 事件）。
- 中途断流（已产出 chunk 后异常）→ token{text:"", done:true} 清前端流式态 + 既有 error 分支。
- FLIPPED_CHAT_STREAM=0 全局关流式（走非流式）。

测试风格沿用既有套件：同步测试函数 + asyncio.run（pytest.ini 已禁用 anyio 插件）。
"""
from __future__ import annotations

import asyncio
import json
import os
import sys

import httpx
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from api.schemas import Event, EventType, Role, SessionStatus  # noqa: E402


# ---------- 测试辅助 ----------

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


def _token_events(published):
    return [e for e in published if e.type == EventType.token]


# ---------- 1 · EventBus.emit_transient ----------

def test_emit_transient_broadcasts_but_never_persists(monkeypatch):
    """transient 事件只广播：publish 收到、store 查不到（token 不落盘，防历史/回放污染）。"""
    from api.events import EventBus
    from api.session import SessionStore

    store = SessionStore()
    bus = EventBus(store)
    published: list = []

    async def _rec(session_id, event):
        published.append((session_id, event))

    monkeypatch.setattr(bus, "publish", _rec)

    async def _drive():
        ev = bus.emit_transient("sess-t1", EventType.token, Role.worker,
                                {"text": "你", "seq": 1, "done": False})
        await asyncio.sleep(0)  # 让 create_task 调度的 publish 跑完
        return ev

    ev = asyncio.run(_drive())

    assert len(published) == 1
    assert published[0][0] == "sess-t1"
    assert published[0][1] is ev
    # 不落盘：store 里查不到该事件
    assert store.events("sess-t1") == []


def test_emit_transient_event_has_empty_id():
    """transient 事件 id 置空串：前端以 truthy ev.id 记录断点续传位点，空串避免污染续传游标。"""
    from api.events import EventBus
    from api.session import SessionStore

    bus = EventBus(SessionStore())
    # 无运行中 loop 且未注册主 loop → 广播静默 no-op，直接检查返回的 Event
    ev = bus.emit_transient("sess-t2", EventType.token, Role.worker,
                            {"text": "", "seq": 2, "done": True})
    assert ev.id == ""
    assert ev.type == EventType.token
    assert ev.agent == Role.worker
    assert ev.payload == {"text": "", "seq": 2, "done": True}


# ---------- 2 · _events_to_turns 忽略 token ----------

def test_events_to_turns_ignores_token_events():
    """token 即使混入历史事件流也不出 turn（transient 设计上不落盘，此处双保险钉死）。"""
    from api.assistant import _events_to_turns

    evs = [
        Event(id="s-000001", session_id="s", type=EventType.message,
              agent=Role.user, payload={"text": "问"}),
        Event(id="", session_id="s", type=EventType.token,
              agent=Role.worker, payload={"text": "你", "seq": 1, "done": False}),
        Event(id="", session_id="s", type=EventType.token,
              agent=Role.worker, payload={"text": "好", "seq": 2, "done": False}),
        Event(id="s-000002", session_id="s", type=EventType.message,
              agent=Role.worker, payload={"text": "你好"}),
    ]
    turns = _events_to_turns(evs)
    assert [(t.role, t.text) for t in turns] == [("user", "问"), ("assistant", "你好")]


# ---------- 3 · _run_chat 流式 ----------

def test_run_chat_streams_tokens_then_final_message(monkeypatch):
    """流式成功：token seq1..3(done=false) + token(done=true) + message 完整文本 + status done；
    store 落盘侧无 token。"""
    import api.main as main

    monkeypatch.delenv("FLIPPED_CHAT_STREAM", raising=False)
    _patch_resolve(monkeypatch)
    published = _patch_publish(monkeypatch)

    chunks = ["你好", "，世", "界"]

    def _fake_stream(base_url, model, system, user, timeout=120.0, usage_box=None):
        async def _gen():
            for c in chunks:
                yield c
        return _gen()

    async def _no_fallback(*a, **kw):
        raise AssertionError("流式成功不应触碰非流式 _llm_chat")

    monkeypatch.setattr(main, "_llm_chat_stream", _fake_stream)
    monkeypatch.setattr(main, "_llm_chat", _no_fallback)

    sid = main.store.create("m166-stream", mode="chat").id
    _run(main._run_chat(sid, "task-1", "hello", "coder", "chat"))

    tokens = _token_events(published)
    assert [t.payload for t in tokens] == [
        {"text": "你好", "seq": 1, "done": False},
        {"text": "，世", "seq": 2, "done": False},
        {"text": "界", "seq": 3, "done": False},
        {"text": "", "seq": 4, "done": True},
    ]
    assert all(t.agent == Role.worker for t in tokens)
    assert all(t.id == "" for t in tokens)

    # 落盘侧：message 完整文本 + status done；无 token、无 error
    events = main.store.events(sid)
    assert not any(e.type == EventType.token for e in events)
    assert not any(e.type == EventType.error for e in events)
    msgs = [e for e in events if e.type == EventType.message and e.agent == Role.worker]
    assert [m.payload["text"] for m in msgs] == ["你好，世界"]
    assert msgs[0].payload["source"] == "agent"
    assert main.store.get(sid).status == SessionStatus.done


def test_run_chat_stream_build_failure_falls_back_silently(monkeypatch):
    """建流失败（generator 首次拉取即抛）→ 静默 fallback 非流式：无 token、message=兜底、status done。"""
    import api.main as main

    monkeypatch.delenv("FLIPPED_CHAT_STREAM", raising=False)
    _patch_resolve(monkeypatch)
    published = _patch_publish(monkeypatch)

    def _failing_stream(*a, **kw):
        async def _gen():
            raise ConnectionError("connect refused")
            yield  # pragma: no cover — 使其成为 async generator
        return _gen()

    async def _fake_chat(base_url, model, system, user, timeout=120.0):
        return "兜底回复", None

    monkeypatch.setattr(main, "_llm_chat_stream", _failing_stream)
    monkeypatch.setattr(main, "_llm_chat", _fake_chat)

    sid = main.store.create("m166-fallback", mode="chat").id
    _run(main._run_chat(sid, "task-1", "hello", "coder", "chat"))

    assert _token_events(published) == []
    events = main.store.events(sid)
    assert not any(e.type == EventType.error for e in events)
    msgs = [e for e in events if e.type == EventType.message and e.agent == Role.worker]
    assert [m.payload["text"] for m in msgs] == ["兜底回复"]
    assert main.store.get(sid).status == SessionStatus.done


def test_run_chat_midstream_break_clears_stream_state_and_errors(monkeypatch):
    """中途断流：token seq1 + token(done=true) 清前端流式态 + error + status error，无 message。"""
    import api.main as main

    monkeypatch.delenv("FLIPPED_CHAT_STREAM", raising=False)
    _patch_resolve(monkeypatch)
    published = _patch_publish(monkeypatch)

    def _broken_stream(*a, **kw):
        async def _gen():
            yield "半句"
            raise RuntimeError("connection reset")
        return _gen()

    async def _no_fallback(*a, **kw):
        raise AssertionError("已建流，不应 fallback 非流式 _llm_chat")

    monkeypatch.setattr(main, "_llm_chat_stream", _broken_stream)
    monkeypatch.setattr(main, "_llm_chat", _no_fallback)

    sid = main.store.create("m166-broken", mode="chat").id
    _run(main._run_chat(sid, "task-1", "hello", "coder", "chat"))

    tokens = _token_events(published)
    assert [t.payload["done"] for t in tokens] == [False, True]
    assert tokens[0].payload["text"] == "半句"
    assert tokens[0].payload["seq"] == 1
    assert tokens[1].payload["text"] == ""

    events = main.store.events(sid)
    assert any(e.type == EventType.error for e in events)
    assert not any(e.type == EventType.message and e.agent == Role.worker for e in events)
    assert main.store.get(sid).status == SessionStatus.error


def test_run_chat_stream_disabled_by_env(monkeypatch):
    """FLIPPED_CHAT_STREAM=0 → 直接走非流式：_llm_chat_stream 0 次调用，无 token 事件。"""
    import api.main as main

    monkeypatch.setenv("FLIPPED_CHAT_STREAM", "0")
    _patch_resolve(monkeypatch)
    published = _patch_publish(monkeypatch)

    calls = {"stream": 0}

    def _counting_stream(*a, **kw):
        calls["stream"] += 1
        async def _gen():
            yield "x"
        return _gen()

    async def _fake_chat(base_url, model, system, user, timeout=120.0):
        return "非流式回复", None

    monkeypatch.setattr(main, "_llm_chat_stream", _counting_stream)
    monkeypatch.setattr(main, "_llm_chat", _fake_chat)

    sid = main.store.create("m166-nostream", mode="chat").id
    _run(main._run_chat(sid, "task-1", "hello", "coder", "chat"))

    assert calls["stream"] == 0
    assert _token_events(published) == []
    msgs = [e for e in main.store.events(sid)
            if e.type == EventType.message and e.agent == Role.worker]
    assert [m.payload["text"] for m in msgs] == ["非流式回复"]
    assert main.store.get(sid).status == SessionStatus.done


# ---------- 4 · _llm_chat_stream SSE 解析 ----------

def _patch_httpx_transport(monkeypatch, handler):
    """httpx.AsyncClient 注入 MockTransport（生产代码内部自建 client，经类替换注入）。"""
    transport = httpx.MockTransport(handler)
    real_client = httpx.AsyncClient

    def _factory(*args, **kwargs):
        kwargs["transport"] = transport
        return real_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", _factory)


def test_llm_chat_stream_parses_sse_and_stops_at_done(monkeypatch):
    """SSE 解析：data: 行 → delta.content 增量序列；[DONE] 即止；缺 content/坏 JSON 行跳过。"""
    from api.main import _llm_chat_stream

    sse_body = (
        'data: {"choices":[{"delta":{"role":"assistant"}}]}\n\n'
        'data: {"choices":[{"delta":{"content":"你"}}]}\n\n'
        "data: not-json-garbage\n\n"
        'data: {"choices":[{"delta":{}}]}\n\n'
        'data: {"choices":[{"delta":{"content":"好"}}]}\n\n'
        ": keep-alive comment\n\n"
        "\n"
        'data: {"choices":[{"delta":{"content":"，世界"}}]}\n\n'
        "data: [DONE]\n\n"
        'data: {"choices":[{"delta":{"content":"不应出现"}}]}\n\n'
    )

    def _handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/chat/completions"
        body = json.loads(request.content.decode())
        assert body["stream"] is True
        return httpx.Response(200, content=sse_body.encode())

    _patch_httpx_transport(monkeypatch, _handler)

    async def _collect():
        return [c async for c in _llm_chat_stream("http://fake.test/v1", "m", "sys", "hi")]

    assert asyncio.run(_collect()) == ["你", "好", "，世界"]


def test_llm_chat_stream_non_200_raises_to_caller(monkeypatch):
    """非 200 → raise_for_status 异常抛给调用方（_run_chat 据此判定建流失败走 fallback）。"""
    from api.main import _llm_chat_stream

    def _handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, content=b"model busy")

    _patch_httpx_transport(monkeypatch, _handler)

    async def _collect():
        return [c async for c in _llm_chat_stream("http://fake.test/v1", "m", "sys", "hi")]

    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(_collect())
