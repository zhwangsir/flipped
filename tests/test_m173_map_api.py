"""M173 · 项目地图接线（B 队）：两个 /project/map 端点 + _run_chat 地图注入。

A 队契约（api/project_map.py，并行开发中，本测试一律经 sys.modules 预注入假模块钉死）：
- MAP_INJECT_HEADER = "以下是用户项目的结构地图（全局概览）："
- @dataclass ProjectMap(markdown, generated_at, source_mtime, stack, stale=False, from_cache=False)
- get_project_map(root, *, max_chars=4000, cache_dir=None) -> ProjectMap
- regenerate_project_map(root, *, max_chars=4000, cache_dir=None) -> ProjectMap

端点契约：
- GET  /api/v1/project/map            无项目 → {"map": None, "needs_project": True}
- POST /api/v1/project/map/regenerate 有项目 → {"map": {五字段}, "needs_project": False}；生成异常 → 500

_run_chat 注入规则（紧跟 M172 RAG 块之后，同款 fail-open）：
- mode ∈ {chat, plan} 且 map_auto 且 FLIPPED_MAP_AUTO != "0" 且有活动项目才注入；
- system += "\\n\\n" + MAP_INJECT_HEADER + "\\n" + m.markdown（get_project_map(root, max_chars=1600)）；
- 最终 message payload 仅在实际注入时附带 "map_injected": True；
- 地图任何故障（导入/生成/读项目根）绝不让对话失败。

测试风格沿用 test_m172_chat_rag.py：同步测试函数 + asyncio.run；绝不 import 真实现。
"""
from __future__ import annotations

import asyncio
import dataclasses
import os
import sys
import types

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from api.main import API_PREFIX, app  # noqa: E402
from api.schemas import EventType, Role, SessionStatus, TaskRequest  # noqa: E402

FAKE_MAP_HEADER = "以下是用户项目的结构地图（全局概览）："
FAKE_MAP_MD = "# 结构地图\n- src/\n- tests/"


# ---------- 测试辅助（沿用 test_m172_chat_rag 风格） ----------

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


def _install_fake_project_map(monkeypatch, *, get_fn=None, regen_fn=None):
    """sys.modules 预注入假 api.project_map 模块；返回 {"get": [...], "regen": [...]} 调用记录。

    get_fn/regen_fn: (root) -> ProjectMap，或直接抛异常测 500/fail-open；缺省返回固定地图。
    """
    calls: dict[str, list] = {"get": [], "regen": []}

    @dataclasses.dataclass
    class ProjectMap:
        markdown: str
        generated_at: str
        source_mtime: float
        stack: list
        stale: bool = False
        from_cache: bool = False

    def _default_map(root, *, from_cache):
        return ProjectMap(
            markdown=FAKE_MAP_MD,
            generated_at="2026-08-04T00:00:00Z",
            source_mtime=1.0,
            stack=["python"],
            stale=False,
            from_cache=from_cache,
        )

    def get_project_map(root, *, max_chars=4000, cache_dir=None):
        calls["get"].append({"root": root, "max_chars": max_chars, "cache_dir": cache_dir})
        if get_fn is not None:
            return get_fn(root)
        return _default_map(root, from_cache=True)

    def regenerate_project_map(root, *, max_chars=4000, cache_dir=None):
        calls["regen"].append({"root": root, "max_chars": max_chars, "cache_dir": cache_dir})
        if regen_fn is not None:
            return regen_fn(root)
        return _default_map(root, from_cache=False)

    fake = types.ModuleType("api.project_map")
    fake.MAP_INJECT_HEADER = FAKE_MAP_HEADER
    fake.ProjectMap = ProjectMap
    fake.get_project_map = get_project_map
    fake.regenerate_project_map = regenerate_project_map
    monkeypatch.setitem(sys.modules, "api.project_map", fake)
    return calls


def _set_active_project(monkeypatch, host):
    """把活动项目钉为 host 目录（monkeypatch 自动还原，不污染其它测试）。"""
    from api import project_state as ps

    monkeypatch.setitem(
        ps._ACTIVE, "project",
        {"name": host.name, "host": str(host), "sandbox": f"/projects/{host.name}"},
    )


def _clear_active_project(monkeypatch):
    from api import project_state as ps

    monkeypatch.setitem(ps._ACTIVE, "project", None)


def _drive_chat(monkeypatch, tmp_path, *, map_fn=None, with_project=True,
                map_auto=True, mode="chat", description="hello", env_map_auto=None):
    """跑一次非流式 _run_chat（rag_auto=False 隔离 M172 块），返回 (main, sid, llm_calls, map_calls)。

    env_map_auto=None → 删除 FLIPPED_MAP_AUTO（走默认开）；传字符串 → 设为该值。
    """
    import api.main as main

    monkeypatch.setenv("FLIPPED_CHAT_STREAM", "0")  # 非流式：直断言 _llm_chat 收到的 system
    if env_map_auto is None:
        monkeypatch.delenv("FLIPPED_MAP_AUTO", raising=False)
    else:
        monkeypatch.setenv("FLIPPED_MAP_AUTO", env_map_auto)
    _patch_resolve(monkeypatch)

    llm_calls: list[dict] = []

    async def _fake_chat(base_url, model, system, user, timeout=120.0):
        llm_calls.append({"system": system, "user": user})
        return "回复", None

    monkeypatch.setattr(main, "_llm_chat", _fake_chat)
    map_calls = _install_fake_project_map(monkeypatch, get_fn=map_fn)

    if with_project:
        proj = tmp_path / "demo"
        proj.mkdir(exist_ok=True)
        _set_active_project(monkeypatch, proj)
    else:
        _clear_active_project(monkeypatch)

    sid = main.store.create("m173", mode=mode).id

    run_kw = {"rag_auto": False}  # 隔离 M172 RAG 块，本套件只断言地图行为
    if map_auto is not True:
        run_kw["map_auto"] = map_auto
    _run(main._run_chat(sid, "task-1", description, "coder", mode, **run_kw))
    return main, sid, llm_calls, map_calls


def _worker_messages(main, sid):
    return [e for e in main.store.events(sid)
            if e.type == EventType.message and e.agent == Role.worker]


# ---------- 1 · GET /project/map ----------

def test_get_project_map_needs_project(monkeypatch):
    """无活动项目 → 200 + map=None + needs_project=True，且不调假 get_project_map。"""
    _clear_active_project(monkeypatch)
    calls = _install_fake_project_map(monkeypatch)
    with TestClient(app) as c:
        r = c.get(f"{API_PREFIX}/project/map")
    assert r.status_code == 200
    assert r.json() == {"map": None, "needs_project": True}
    assert calls["get"] == [] and calls["regen"] == []


def test_get_project_map_returns_five_fields(monkeypatch, tmp_path):
    """有项目 → 调 get_project_map(root)，返回 map 五字段齐全 + needs_project=False。"""
    proj = tmp_path / "demo"
    proj.mkdir()
    _set_active_project(monkeypatch, proj)
    calls = _install_fake_project_map(monkeypatch)
    with TestClient(app) as c:
        r = c.get(f"{API_PREFIX}/project/map")
    assert r.status_code == 200
    data = r.json()
    assert data["needs_project"] is False
    assert data["map"] == {
        "markdown": FAKE_MAP_MD,
        "generated_at": "2026-08-04T00:00:00Z",
        "stale": False,
        "from_cache": True,
        "stack": ["python"],
    }
    assert len(calls["get"]) == 1
    assert calls["get"][0]["root"] == proj


def test_get_project_map_generation_error_returns_500(monkeypatch, tmp_path):
    """生成过程抛异常 → 500 明示（与 /mcp/tools 内省失败同款风格）。"""
    def _boom(root):
        raise RuntimeError("map boom")

    proj = tmp_path / "demo"
    proj.mkdir()
    _set_active_project(monkeypatch, proj)
    _install_fake_project_map(monkeypatch, get_fn=_boom)
    with TestClient(app) as c:
        r = c.get(f"{API_PREFIX}/project/map")
    assert r.status_code == 500
    assert "map boom" in r.json()["detail"]


# ---------- 2 · POST /project/map/regenerate ----------

def test_post_project_map_regenerate_calls_regen(monkeypatch, tmp_path):
    """regenerate → 调 regenerate_project_map（而非 get），返回同形状五字段。"""
    proj = tmp_path / "demo"
    proj.mkdir()
    _set_active_project(monkeypatch, proj)
    calls = _install_fake_project_map(monkeypatch)
    with TestClient(app) as c:
        r = c.post(f"{API_PREFIX}/project/map/regenerate")
    assert r.status_code == 200
    data = r.json()
    assert data["needs_project"] is False
    assert data["map"]["markdown"] == FAKE_MAP_MD
    assert data["map"]["from_cache"] is False  # 强制重建，不走缓存
    assert set(data["map"]) == {"markdown", "generated_at", "stale", "from_cache", "stack"}
    assert len(calls["regen"]) == 1 and calls["get"] == []
    assert calls["regen"][0]["root"] == proj


def test_post_project_map_regenerate_needs_project(monkeypatch):
    """regenerate 无活动项目 → 200 + map=None + needs_project=True。"""
    _clear_active_project(monkeypatch)
    calls = _install_fake_project_map(monkeypatch)
    with TestClient(app) as c:
        r = c.post(f"{API_PREFIX}/project/map/regenerate")
    assert r.status_code == 200
    assert r.json() == {"map": None, "needs_project": True}
    assert calls["regen"] == []


# ---------- 3 · _run_chat 注入主路径 ----------

def test_run_chat_injects_project_map(monkeypatch, tmp_path):
    """mode=chat + 有项目 → system 含 HEADER+markdown（max_chars=1600），payload 带 map_injected=True。"""
    main, sid, llm_calls, map_calls = _drive_chat(monkeypatch, tmp_path)

    assert len(llm_calls) == 1
    assert llm_calls[0]["system"] == main.CHAT_SYSTEM + "\n\n" + FAKE_MAP_HEADER + "\n" + FAKE_MAP_MD
    assert llm_calls[0]["user"] == "hello"
    assert len(map_calls["get"]) == 1
    assert map_calls["get"][0]["max_chars"] == 1600

    msgs = _worker_messages(main, sid)
    assert len(msgs) == 1
    assert msgs[0].payload["text"] == "回复"
    assert msgs[0].payload["source"] == "agent"
    assert msgs[0].payload["map_injected"] is True
    assert "rag_chunks" not in msgs[0].payload  # rag_auto=False 隔离，形状不受 M172 影响
    assert main.store.get(sid).status == SessionStatus.done


def test_run_chat_plan_mode_also_injects(monkeypatch, tmp_path):
    """plan 模式同样注入：system=PLAN_SYSTEM+HEADER+markdown。"""
    main, sid, llm_calls, _ = _drive_chat(monkeypatch, tmp_path, mode="plan")

    assert llm_calls[0]["system"] == main.PLAN_SYSTEM + "\n\n" + FAKE_MAP_HEADER + "\n" + FAKE_MAP_MD
    assert _worker_messages(main, sid)[0].payload["map_injected"] is True


# ---------- 4 · 关闭开关 ----------

def test_run_chat_map_disabled_by_env(monkeypatch, tmp_path):
    """FLIPPED_MAP_AUTO=0 → 不调 get_project_map，system 原样，payload 无 map_injected。"""
    main, sid, llm_calls, map_calls = _drive_chat(monkeypatch, tmp_path, env_map_auto="0")

    assert map_calls["get"] == []
    assert llm_calls[0]["system"] == main.CHAT_SYSTEM
    assert "map_injected" not in _worker_messages(main, sid)[0].payload


def test_run_chat_map_auto_false_skips_injection(monkeypatch, tmp_path):
    """请求级 map_auto=False → 不调 get_project_map，system 原样，payload 无 map_injected。"""
    main, sid, llm_calls, map_calls = _drive_chat(monkeypatch, tmp_path, map_auto=False)

    assert map_calls["get"] == []
    assert llm_calls[0]["system"] == main.CHAT_SYSTEM
    assert "map_injected" not in _worker_messages(main, sid)[0].payload


# ---------- 5 · 无项目 / 空地图 / fail-open ----------

def test_run_chat_no_project_skips_map(monkeypatch, tmp_path):
    """ps.project_root() 为 None → 不调假 get_project_map，不注入，对话照常完成。"""
    main, sid, llm_calls, map_calls = _drive_chat(monkeypatch, tmp_path, with_project=False)

    assert map_calls["get"] == []
    assert llm_calls[0]["system"] == main.CHAT_SYSTEM
    assert "map_injected" not in _worker_messages(main, sid)[0].payload
    assert main.store.get(sid).status == SessionStatus.done


def test_run_chat_empty_markdown_keeps_payload_shape(monkeypatch, tmp_path):
    """m.markdown 为空 → 不注入：system 原样，payload 保持现状形状（无 map_injected）。"""
    @dataclasses.dataclass
    class _EmptyMap:
        markdown: str
        generated_at: str = "2026-08-04T00:00:00Z"
        source_mtime: float = 0.0
        stack: list = dataclasses.field(default_factory=list)
        stale: bool = False
        from_cache: bool = False

    main, sid, llm_calls, map_calls = _drive_chat(
        monkeypatch, tmp_path, map_fn=lambda root: _EmptyMap(markdown=""))

    assert len(map_calls["get"]) == 1
    assert llm_calls[0]["system"] == main.CHAT_SYSTEM
    assert _worker_messages(main, sid)[0].payload == {"text": "回复", "source": "agent"}


def test_run_chat_map_failure_fails_open(monkeypatch, tmp_path):
    """get_project_map 抛异常 → 对话照常完成：message 正常 emit、system 无注入、status done。"""
    def _boom(root):
        raise RuntimeError("map down")

    main, sid, llm_calls, map_calls = _drive_chat(monkeypatch, tmp_path, map_fn=_boom)

    assert len(map_calls["get"]) == 1  # 确实尝试了注入
    assert llm_calls[0]["system"] == main.CHAT_SYSTEM
    msgs = _worker_messages(main, sid)
    assert len(msgs) == 1
    assert msgs[0].payload["text"] == "回复"
    assert "map_injected" not in msgs[0].payload
    assert not any(e.type == EventType.error for e in main.store.events(sid))
    assert main.store.get(sid).status == SessionStatus.done


# ---------- 6 · 调用点传参 ----------

def test_create_task_passes_map_auto_from_context(monkeypatch):
    """路由调用点：req.context["map_auto"]=False 传到 _run_chat；context 不含 → 收不到该 kwarg。"""
    import api.main as main

    recorded: list[dict] = []

    async def _fake_run_chat(session_id, task_id, description, model_alias, mode, **kwargs):
        recorded.append({"model_alias": model_alias, "mode": mode, "kwargs": kwargs})

    monkeypatch.setattr(main, "_run_chat", _fake_run_chat)

    sid_off = main.store.create("m173-route-off", mode="chat").id
    sid_def = main.store.create("m173-route-def", mode="chat").id

    async def _drive():
        await main.create_task(
            sid_off, TaskRequest(description="hi", context={"mode": "chat", "map_auto": False}))
        await main.create_task(
            sid_def, TaskRequest(description="hi", context={"mode": "chat"}))
        for sid in (sid_off, sid_def):
            t = main.RUNNING_TASKS.get(sid)
            if t is not None:
                await t

    asyncio.run(_drive())

    # 显式携带 → 传 map_auto=False；缺省 → kwargs 为空（_run_chat 缺省 map_auto=True）
    assert recorded == [
        {"model_alias": "coder", "mode": "chat", "kwargs": {"map_auto": False}},
        {"model_alias": "coder", "mode": "chat", "kwargs": {}},
    ]


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
