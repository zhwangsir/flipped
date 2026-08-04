"""M172 · chat/plan 通路 RAG 上下文自动注入（B 队：_run_chat 接线）。

契约（与 A 队 api/rag_context.py 钉死）：
- build_rag_context(query, *, project=None, n_results=4, max_chars=2400, store=None)
  -> (context_text, chunk_count)；任何异常/无结果 → ("", 0)

注入规则：
- mode ∈ {chat, plan} 且 FLIPPED_RAG_AUTO != "0" 且请求级 rag_auto=True 才注入；
- rag_ctx 非空 → system = 原 system + "\\n\\n" + rag_ctx；
- 最终 message payload 仅在 rag_k > 0 时附带 "rag_chunks"（k==0 保持现状形状）；
- 全程 fail-open：RAG 故障绝不让对话失败。

A 队 api/rag_context.py 并行开发中：本测试一律经 sys.modules 预注入假模块，
绝不 import 真实现。测试风格沿用既有套件：同步测试函数 + asyncio.run。
"""
from __future__ import annotations

import asyncio
import os
import sys
import types

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from api.schemas import EventType, Role, SessionStatus, TaskRequest  # noqa: E402


# ---------- 测试辅助（沿用 test_m166_token_stream 风格） ----------

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


def _install_fake_rag(monkeypatch, fn):
    """sys.modules 预注入假 api.rag_context 模块；返回记录调用参数的列表。

    fn 签名: (query, project) -> (context_text, chunk_count)，或直接抛异常测 fail-open。
    """
    calls: list[dict] = []

    def _recording(query, *, project=None, n_results=4, max_chars=2400, store=None):
        calls.append({"query": query, "project": project})
        return fn(query, project)

    fake = types.ModuleType("api.rag_context")
    fake.build_rag_context = _recording
    monkeypatch.setitem(sys.modules, "api.rag_context", fake)
    return calls


def _drive_chat(monkeypatch, *, rag_fn, rag_auto=True, project_name=None,
                mode="chat", description="hello", env_rag_auto=None):
    """跑一次非流式 _run_chat，返回 (main, sid, llm_calls, rag_calls)。

    env_rag_auto=None → 删除 FLIPPED_RAG_AUTO（走默认开）；传字符串 → 设为该值。
    """
    import api.main as main

    monkeypatch.setenv("FLIPPED_CHAT_STREAM", "0")  # 非流式：直断言 _llm_chat 收到的 system
    if env_rag_auto is None:
        monkeypatch.delenv("FLIPPED_RAG_AUTO", raising=False)
    else:
        monkeypatch.setenv("FLIPPED_RAG_AUTO", env_rag_auto)
    _patch_resolve(monkeypatch)

    llm_calls: list[dict] = []

    async def _fake_chat(base_url, model, system, user, timeout=120.0):
        llm_calls.append({"system": system, "user": user})
        return "回复", None

    monkeypatch.setattr(main, "_llm_chat", _fake_chat)
    rag_calls = _install_fake_rag(monkeypatch, rag_fn)

    create_kw = {"mode": mode}
    if project_name is not None:
        create_kw["project_name"] = project_name
    sid = main.store.create("m172", **create_kw).id

    run_kw = {"rag_auto": rag_auto} if rag_auto is not True else {}
    _run(main._run_chat(sid, "task-1", description, "coder", mode, **run_kw))
    return main, sid, llm_calls, rag_calls


def _worker_messages(main, sid):
    return [e for e in main.store.events(sid)
            if e.type == EventType.message and e.agent == Role.worker]


# ---------- 1 · 注入主路径 ----------

def test_run_chat_injects_rag_context_and_emits_rag_chunks(monkeypatch):
    """("RAGCTX", 3) → system=CHAT_SYSTEM+"\\n\\n"+RAGCTX；message payload 带 rag_chunks=3。"""
    main, sid, llm_calls, rag_calls = _drive_chat(
        monkeypatch, rag_fn=lambda q, project: ("RAGCTX", 3))

    assert len(llm_calls) == 1
    assert llm_calls[0]["system"] == main.CHAT_SYSTEM + "\n\nRAGCTX"
    assert llm_calls[0]["user"] == "hello"
    assert rag_calls == [{"query": "hello", "project": None}]

    msgs = _worker_messages(main, sid)
    assert len(msgs) == 1
    assert msgs[0].payload["text"] == "回复"
    assert msgs[0].payload["source"] == "agent"
    assert msgs[0].payload["rag_chunks"] == 3
    assert main.store.get(sid).status == SessionStatus.done


def test_run_chat_plan_mode_also_injects(monkeypatch):
    """plan 模式同样注入：system=PLAN_SYSTEM+"\\n\\n"+RAGCTX。"""
    main, sid, llm_calls, _ = _drive_chat(
        monkeypatch, rag_fn=lambda q, project: ("RAGCTX", 2), mode="plan")

    assert llm_calls[0]["system"] == main.PLAN_SYSTEM + "\n\nRAGCTX"
    assert _worker_messages(main, sid)[0].payload["rag_chunks"] == 2


# ---------- 2 · 关闭开关 ----------

def test_run_chat_rag_disabled_by_env(monkeypatch):
    """FLIPPED_RAG_AUTO=0 → 不调用 build_rag_context，system 原样，payload 无 rag_chunks。"""
    import api.main as main  # noqa: F401  (经 _drive_chat 使用同一模块)

    _, sid, llm_calls, rag_calls = _drive_chat(
        monkeypatch, rag_fn=lambda q, project: ("RAGCTX", 3), env_rag_auto="0")

    assert rag_calls == []
    assert llm_calls[0]["system"] == main.CHAT_SYSTEM
    assert "rag_chunks" not in _worker_messages(main, sid)[0].payload


def test_run_chat_rag_auto_false_skips_injection(monkeypatch):
    """请求级 rag_auto=False → 不调用 build_rag_context，system 原样，payload 无 rag_chunks。"""
    _, sid, llm_calls, rag_calls = _drive_chat(
        monkeypatch, rag_fn=lambda q, project: ("RAGCTX", 3), rag_auto=False)

    import api.main as main
    assert rag_calls == []
    assert llm_calls[0]["system"] == main.CHAT_SYSTEM
    assert "rag_chunks" not in _worker_messages(main, sid)[0].payload


# ---------- 3 · project 透传 ----------

def test_run_chat_passes_session_project_name(monkeypatch):
    """会话带 project_name="flipped" → build_rag_context 收到 project="flipped"。"""
    _, _, _, rag_calls = _drive_chat(
        monkeypatch, rag_fn=lambda q, project: ("RAGCTX", 1), project_name="flipped")

    assert rag_calls == [{"query": "hello", "project": "flipped"}]


def test_run_chat_project_name_none_passed_through(monkeypatch):
    """会话无 project_name → project=None 透传。"""
    _, _, _, rag_calls = _drive_chat(
        monkeypatch, rag_fn=lambda q, project: ("RAGCTX", 1))

    assert rag_calls[0]["project"] is None


# ---------- 4 · fail-open 与空结果 ----------

def test_run_chat_rag_failure_fails_open(monkeypatch):
    """build_rag_context 抛异常 → 对话照常完成：message 正常 emit、system 无注入、status done。"""
    def _boom(q, project):
        raise RuntimeError("rag down")

    main, sid, llm_calls, _ = _drive_chat(monkeypatch, rag_fn=_boom)

    assert llm_calls[0]["system"] == main.CHAT_SYSTEM
    msgs = _worker_messages(main, sid)
    assert len(msgs) == 1
    assert msgs[0].payload["text"] == "回复"
    assert "rag_chunks" not in msgs[0].payload
    assert not any(e.type == EventType.error for e in main.store.events(sid))
    assert main.store.get(sid).status == SessionStatus.done


def test_run_chat_empty_rag_result_keeps_system_and_payload(monkeypatch):
    """("", 0) → system 原样不变，payload 无 rag_chunks（保持现状形状）。"""
    main, sid, llm_calls, _ = _drive_chat(
        monkeypatch, rag_fn=lambda q, project: ("", 0))

    assert llm_calls[0]["system"] == main.CHAT_SYSTEM
    msgs = _worker_messages(main, sid)
    assert msgs[0].payload == {"text": "回复", "source": "agent"}


# ---------- 5 · 调用点传参 ----------

def test_create_task_passes_rag_auto_from_context(monkeypatch):
    """路由调用点：req.context["rag_auto"]=False 传到 _run_chat；缺省 → True。"""
    import api.main as main

    recorded: list[dict] = []

    async def _fake_run_chat(session_id, task_id, description, model_alias, mode,
                             *, rag_auto=True):
        recorded.append({"model_alias": model_alias, "mode": mode, "rag_auto": rag_auto})

    monkeypatch.setattr(main, "_run_chat", _fake_run_chat)

    sid_off = main.store.create("m172-route-off", mode="chat").id
    sid_def = main.store.create("m172-route-def", mode="chat").id

    async def _drive():
        await main.create_task(
            sid_off, TaskRequest(description="hi", context={"mode": "chat", "rag_auto": False}))
        await main.create_task(
            sid_def, TaskRequest(description="hi", context={"mode": "chat"}))
        for sid in (sid_off, sid_def):
            t = main.RUNNING_TASKS.get(sid)
            if t is not None:
                await t

    asyncio.run(_drive())

    assert recorded == [
        {"model_alias": "coder", "mode": "chat", "rag_auto": False},
        {"model_alias": "coder", "mode": "chat", "rag_auto": True},
    ]
