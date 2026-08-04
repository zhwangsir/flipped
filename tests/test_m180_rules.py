"""M180.1 · 项目规则系统（B 队后端）：rules.py 纯逻辑 + GET/PUT /project/rules + _run_chat 注入。

契约（PLAN.md M180 钉死）：
- RULE_FILES = (".flipped/rules.md", "AGENTS.md", ".cursorrules")，全部命中全部收，按序拼接；
  每文件渲染为「## {relpath}\\n\\n{content}」节；超 max_chars 从末尾整节丢弃（首节尽量保留）
  并注记「…已截断 N 节」；total_chars = 未截断前总长。
- GET  /api/v1/project/rules：无项目 → needs_project=True 全空；否则 files/markdown/
  total_chars/rules_content（.flipped/rules.md 原文，编辑器初值）。
- PUT  /api/v1/project/rules：只写固定相对路径 .flipped/rules.md（原子写）；无项目 → 400；
  content 超 64KB → 422；写后重载返回 RulesResponse。
- _run_chat 注入（紧跟 M173 地图块之后，同款 fail-open）：mode ∈ {chat, plan} 且
  rules_auto 且 FLIPPED_RULES_AUTO != "0" → system += "\\n\\n" + RULES_INJECT_HEADER +
  "\\n" + rules.markdown；空规则零注入；装载任何异常绝不让对话失败。

测试风格沿用 test_m173_map_api.py / test_m179_review.py：TestClient + tmp 项目 +
monkeypatch fake LLM（FLIPPED_CHAT_STREAM=0 非流式直断言 system），绝不烧真模型。
"""
from __future__ import annotations

import asyncio
import os
import sys

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from api.main import API_PREFIX, app  # noqa: E402
from api.rules import (  # noqa: E402
    RULE_FILES,
    RULES_INJECT_HEADER,
    load_project_rules,
    rules_raw_content,
    write_project_rules,
)
from api.schemas import EventType, Role, SessionStatus, TaskRequest  # noqa: E402

RULES_TEXT = "规则：全部测试用 pytest"


# ---------- 测试辅助（沿用 test_m173_map_api.py 风格） ----------

def _run(coro):
    """asyncio.run 跑 coroutine，并 drain bus.emit 里 create_task 调度的 publish。"""
    async def _wrap():
        await coro
        await asyncio.sleep(0)
        await asyncio.sleep(0)
    return asyncio.run(_wrap())


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


@pytest.fixture()
def client(monkeypatch, tmp_path):
    """隔离 DB + mock orchestrator，返回 TestClient（同 test_m179_review.py）。"""
    monkeypatch.setenv("FLIPPED_MOCK_ORCHESTRATOR", "1")
    monkeypatch.setattr("api.main.FLIPPED_CHECKPOINT_DB", str(tmp_path / "cp.db"))
    return TestClient(app)


@pytest.fixture()
def project(monkeypatch, tmp_path):
    """tmp_path 下项目目录并设为活动项目（monkeypatch 自动还原）。"""
    proj = tmp_path / "demo"
    proj.mkdir()
    _set_active_project(monkeypatch, proj)
    return proj


def _drive_chat(monkeypatch, tmp_path, *, with_project=True, env_rules_auto=None,
                mode="chat", rules_text=RULES_TEXT):
    """跑一次非流式 _run_chat（rag_auto/map_auto=False 隔离 M172/M173 块），返回 (main, sid, llm_calls)。

    env_rules_auto=None → 删除 FLIPPED_RULES_AUTO（走默认开）；传字符串 → 设为该值。
    用真 api.rules + 真 tmp 项目（AGENTS.md 写入 rules_text）。
    """
    import api.main as main

    monkeypatch.setenv("FLIPPED_CHAT_STREAM", "0")  # 非流式：直断言 _llm_chat 收到的 system
    if env_rules_auto is None:
        monkeypatch.delenv("FLIPPED_RULES_AUTO", raising=False)
    else:
        monkeypatch.setenv("FLIPPED_RULES_AUTO", env_rules_auto)
    monkeypatch.setattr(
        "driving.model_router.resolve_worker_model_config",
        lambda alias="coder": ("http://fake.test/v1", "fake-model"),
    )

    llm_calls: list[dict] = []

    async def _fake_chat(base_url, model, system, user, timeout=120.0):
        llm_calls.append({"system": system, "user": user})
        return "回复", None

    monkeypatch.setattr(main, "_llm_chat", _fake_chat)

    if with_project:
        proj = tmp_path / "demo"
        proj.mkdir(exist_ok=True)
        (proj / "AGENTS.md").write_text(rules_text, encoding="utf-8")
        _set_active_project(monkeypatch, proj)
    else:
        _clear_active_project(monkeypatch)

    sid = main.store.create("m180", mode=mode).id
    _run(main._run_chat(sid, "task-1", "hello", "coder", mode,
                        rag_auto=False, map_auto=False))  # 隔离 M172/M173 块，只断言规则行为
    return main, sid, llm_calls


def _worker_messages(main, sid):
    return [e for e in main.store.events(sid)
            if e.type == EventType.message and e.agent == Role.worker]


# ====================================================================
# 1 · load_project_rules
# ====================================================================

def test_load_no_files_returns_empty(tmp_path):
    """无任何规则文件 → 空 ProjectRules（files==[] markdown=="" total_chars==0）。"""
    rules = load_project_rules(tmp_path)
    assert rules.files == []
    assert rules.markdown == ""
    assert rules.total_chars == 0


def test_load_root_none_returns_empty():
    """root None → 空 ProjectRules（无项目零注入）。"""
    rules = load_project_rules(None)
    assert rules.files == [] and rules.markdown == "" and rules.total_chars == 0


def test_load_single_flipped_rules(tmp_path):
    """单 .flipped/rules.md → files/markdown/total_chars 正确。"""
    (tmp_path / ".flipped").mkdir()
    (tmp_path / ".flipped" / "rules.md").write_text("用 tabs 缩进", encoding="utf-8")
    rules = load_project_rules(tmp_path)
    assert rules.files == [".flipped/rules.md"]
    assert rules.markdown == "## .flipped/rules.md\n\n用 tabs 缩进"
    assert rules.total_chars == len(rules.markdown)


def test_load_three_files_priority_order(tmp_path):
    """三文件齐备 → 按 RULE_FILES 顺序拼接，files 顺序正确，markdown 各节顺序正确。"""
    (tmp_path / ".flipped").mkdir()
    (tmp_path / ".flipped" / "rules.md").write_text("主规则", encoding="utf-8")
    (tmp_path / "AGENTS.md").write_text("代理约定", encoding="utf-8")
    (tmp_path / ".cursorrules").write_text("光标遗产", encoding="utf-8")
    rules = load_project_rules(tmp_path)
    assert rules.files == list(RULE_FILES)
    assert rules.markdown == (
        "## .flipped/rules.md\n\n主规则\n\n"
        "## AGENTS.md\n\n代理约定\n\n"
        "## .cursorrules\n\n光标遗产"
    )
    assert rules.total_chars == len(rules.markdown)


def test_load_non_utf8_file_skipped(tmp_path):
    """非 utf-8 文件 → 跳过该文件不炸，其余正常命中。"""
    (tmp_path / "AGENTS.md").write_bytes(b"\xff\xfe\x00\x01")  # 非法 utf-8
    (tmp_path / ".cursorrules").write_text("光标规则", encoding="utf-8")
    rules = load_project_rules(tmp_path)
    assert rules.files == [".cursorrules"]
    assert "光标规则" in rules.markdown
    assert "AGENTS.md" not in rules.markdown


def test_load_blank_file_not_hit(tmp_path):
    """内容全空白的文件不命中（空规则零注入）：files 不含、markdown 不受影响。"""
    (tmp_path / "AGENTS.md").write_text("  \n\n\t \n", encoding="utf-8")
    rules = load_project_rules(tmp_path)
    assert rules.files == []
    assert rules.markdown == ""
    assert rules.total_chars == 0


def test_load_truncation_drops_tail_sections(tmp_path):
    """超 max_chars → 从末尾整节丢弃 + 注记「…已截断 N 节」+ total_chars 为截断前总长。"""
    (tmp_path / ".flipped").mkdir()
    (tmp_path / ".flipped" / "rules.md").write_text("A" * 50, encoding="utf-8")
    (tmp_path / "AGENTS.md").write_text("B" * 50, encoding="utf-8")
    (tmp_path / ".cursorrules").write_text("C" * 50, encoding="utf-8")
    first_section = "## .flipped/rules.md\n\n" + "A" * 50
    full = load_project_rules(tmp_path, max_chars=10**9)
    # 预算只够首节 → 后两节整节丢弃
    rules = load_project_rules(tmp_path, max_chars=len(first_section) + 5)
    assert rules.files == list(RULE_FILES), "files 记录全部命中文件（含被截断的节）"
    assert rules.markdown == first_section + "\n\n…已截断 2 节"
    assert "B" * 50 not in rules.markdown and "C" * 50 not in rules.markdown
    assert rules.total_chars == len(full.markdown) > len(rules.markdown)


# ====================================================================
# 2 · rules_raw_content
# ====================================================================

def test_raw_content_missing_returns_empty(tmp_path):
    """.flipped/rules.md 不存在 → ""。"""
    assert rules_raw_content(tmp_path) == ""


def test_raw_content_returns_original_text(tmp_path):
    """存在 → 原文（含首尾空白，不 strip，编辑器初值保真）。"""
    (tmp_path / ".flipped").mkdir()
    raw = "\n# 规则\n\n- 条目\n"
    (tmp_path / ".flipped" / "rules.md").write_text(raw, encoding="utf-8")
    assert rules_raw_content(tmp_path) == raw


# ====================================================================
# 3 · write_project_rules
# ====================================================================

def test_write_creates_dir_and_returns_relpath(tmp_path):
    """自动建 .flipped 目录 + 返回固定相对路径 + 内容正确落盘。"""
    rel = write_project_rules(tmp_path, "第一条规则")
    assert rel == ".flipped/rules.md"
    target = tmp_path / ".flipped" / "rules.md"
    assert target.is_file()
    assert target.read_text(encoding="utf-8") == "第一条规则"


def test_write_unicode_roundtrip_and_overwrite(tmp_path):
    """unicode 往返 + 重复写覆盖旧内容（os.replace 原子替换）。"""
    content = "# 规则\n- 用「中文引号」与 emoji 🚀\n- 第二行"
    write_project_rules(tmp_path, "旧内容")
    rel = write_project_rules(tmp_path, content)
    assert rel == ".flipped/rules.md"
    assert rules_raw_content(tmp_path) == content
    assert not (tmp_path / ".flipped" / "rules.md.tmp").exists(), "tmp 文件必须已被 os.replace 收走"


# ====================================================================
# 4 · GET / PUT /api/v1/project/rules 端点
# ====================================================================

def test_get_rules_needs_project(client, monkeypatch):
    """GET 无活动项目 → 200 + needs_project=True + 全空。"""
    _clear_active_project(monkeypatch)
    r = client.get(f"{API_PREFIX}/project/rules")
    assert r.status_code == 200
    assert r.json() == {"files": [], "markdown": "", "total_chars": 0,
                        "rules_content": "", "needs_project": True}


def test_get_rules_with_files(client, project):
    """GET 有规则文件 → files/markdown/rules_content 正确，needs_project=False。"""
    (project / ".flipped").mkdir()
    (project / ".flipped" / "rules.md").write_text("主规则内容", encoding="utf-8")
    (project / "AGENTS.md").write_text("代理约定内容", encoding="utf-8")
    r = client.get(f"{API_PREFIX}/project/rules")
    assert r.status_code == 200
    data = r.json()
    assert data["needs_project"] is False
    assert data["files"] == [".flipped/rules.md", "AGENTS.md"]
    assert "## .flipped/rules.md\n\n主规则内容" in data["markdown"]
    assert "## AGENTS.md\n\n代理约定内容" in data["markdown"]
    assert data["total_chars"] == len(data["markdown"])
    assert data["rules_content"] == "主规则内容", "编辑源 = .flipped/rules.md 原文"


def test_get_rules_only_agents_md_has_empty_rules_content(client, project):
    """GET 仅 AGENTS.md → markdown 非空但 rules_content==""（拼接结果不能直接当编辑源）。"""
    (project / "AGENTS.md").write_text("只有代理约定", encoding="utf-8")
    r = client.get(f"{API_PREFIX}/project/rules")
    assert r.status_code == 200
    data = r.json()
    assert data["files"] == ["AGENTS.md"]
    assert "只有代理约定" in data["markdown"]
    assert data["rules_content"] == ""


def test_put_rules_no_project_400(client, monkeypatch):
    """PUT 无活动项目 → 400「未选择项目」。"""
    _clear_active_project(monkeypatch)
    r = client.put(f"{API_PREFIX}/project/rules", json={"content": "x"})
    assert r.status_code == 400
    assert "未选择项目" in r.json()["detail"]


def test_put_rules_then_get_reflects(client, project):
    """PUT 写规则 → 响应即重载结果；再 GET 反映同一份新内容。"""
    r = client.put(f"{API_PREFIX}/project/rules", json={"content": "新规则：先跑测试"})
    assert r.status_code == 200
    data = r.json()
    assert data["needs_project"] is False
    assert data["rules_content"] == "新规则：先跑测试"
    assert data["files"] == [".flipped/rules.md"]
    assert data["markdown"] == "## .flipped/rules.md\n\n新规则：先跑测试"
    # 真落盘
    assert (project / ".flipped" / "rules.md").read_text(encoding="utf-8") == "新规则：先跑测试"
    # GET 反映
    r2 = client.get(f"{API_PREFIX}/project/rules")
    assert r2.status_code == 200
    assert r2.json() == data


def test_put_rules_over_64kb_422(client, project):
    """PUT content 超 64KB → 422（pydantic max_length 校验）。"""
    r = client.put(f"{API_PREFIX}/project/rules", json={"content": "x" * 65537})
    assert r.status_code == 422
    assert not (project / ".flipped" / "rules.md").exists(), "校验失败绝不落盘"


# ====================================================================
# 5 · _run_chat 规则注入
# ====================================================================

def test_run_chat_injects_rules(monkeypatch, tmp_path):
    """mode=chat + 项目含 AGENTS.md → system 含 RULES_INJECT_HEADER + 规则文本。"""
    main, sid, llm_calls = _drive_chat(monkeypatch, tmp_path)

    assert len(llm_calls) == 1
    assert llm_calls[0]["system"] == (
        main.CHAT_SYSTEM + "\n\n" + RULES_INJECT_HEADER + "\n"
        "## AGENTS.md\n\n" + RULES_TEXT
    )
    msgs = _worker_messages(main, sid)
    assert len(msgs) == 1
    assert msgs[0].payload["text"] == "回复"
    assert main.store.get(sid).status == SessionStatus.done


def test_run_chat_plan_mode_also_injects(monkeypatch, tmp_path):
    """plan 模式同样注入：system=PLAN_SYSTEM+HEADER+规则 markdown。"""
    main, sid, llm_calls = _drive_chat(monkeypatch, tmp_path, mode="plan")

    assert llm_calls[0]["system"] == (
        main.PLAN_SYSTEM + "\n\n" + RULES_INJECT_HEADER + "\n"
        "## AGENTS.md\n\n" + RULES_TEXT
    )


def test_run_chat_rules_disabled_by_env(monkeypatch, tmp_path):
    """FLIPPED_RULES_AUTO=0 → system 原样（不含 HEADER 与规则文本），对话照常完成。"""
    main, sid, llm_calls = _drive_chat(monkeypatch, tmp_path, env_rules_auto="0")

    assert llm_calls[0]["system"] == main.CHAT_SYSTEM
    assert RULES_INJECT_HEADER not in llm_calls[0]["system"]
    assert main.store.get(sid).status == SessionStatus.done


def test_run_chat_no_project_skips_rules(monkeypatch, tmp_path):
    """无活动项目 → 不注入，对话照常完成。"""
    main, sid, llm_calls = _drive_chat(monkeypatch, tmp_path, with_project=False)

    assert llm_calls[0]["system"] == main.CHAT_SYSTEM
    assert main.store.get(sid).status == SessionStatus.done


def test_run_chat_empty_rules_zero_injection(monkeypatch, tmp_path):
    """规则文件内容空白 → 零注入：system 原样。"""
    main, sid, llm_calls = _drive_chat(monkeypatch, tmp_path, rules_text="  \n\n ")

    assert llm_calls[0]["system"] == main.CHAT_SYSTEM


def test_run_chat_rules_load_failure_fails_open(monkeypatch, tmp_path):
    """load_project_rules 抛异常 → 对话照常完成：message 正常、system 无注入、status done。"""
    def _boom(root, *, max_chars=4000):
        raise RuntimeError("rules down")

    monkeypatch.setattr("api.rules.load_project_rules", _boom)
    main, sid, llm_calls = _drive_chat(monkeypatch, tmp_path)

    assert llm_calls[0]["system"] == main.CHAT_SYSTEM
    msgs = _worker_messages(main, sid)
    assert len(msgs) == 1
    assert msgs[0].payload["text"] == "回复"
    assert not any(e.type == EventType.error for e in main.store.events(sid))
    assert main.store.get(sid).status == SessionStatus.done


# ====================================================================
# 6 · 调用点传参（main.py:801 区域 context 覆盖行）
# ====================================================================

def test_create_task_passes_rules_auto_from_context(monkeypatch):
    """路由调用点：req.context["rules_auto"]=False 传到 _run_chat；context 不含 → 收不到该 kwarg。"""
    import api.main as main

    recorded: list[dict] = []

    async def _fake_run_chat(session_id, task_id, description, model_alias, mode, **kwargs):
        recorded.append({"model_alias": model_alias, "mode": mode, "kwargs": kwargs})

    monkeypatch.setattr(main, "_run_chat", _fake_run_chat)

    sid_off = main.store.create("m180-route-off", mode="chat").id
    sid_def = main.store.create("m180-route-def", mode="chat").id

    async def _drive():
        await main.create_task(
            sid_off, TaskRequest(description="hi", context={"mode": "chat", "rules_auto": False}))
        await main.create_task(
            sid_def, TaskRequest(description="hi", context={"mode": "chat"}))
        for sid in (sid_off, sid_def):
            t = main.RUNNING_TASKS.get(sid)
            if t is not None:
                await t

    asyncio.run(_drive())

    # 显式携带 → 传 rules_auto=False；缺省 → kwargs 为空（_run_chat 缺省 rules_auto=True）
    assert recorded == [
        {"model_alias": "coder", "mode": "chat", "kwargs": {"rules_auto": False}},
        {"model_alias": "coder", "mode": "chat", "kwargs": {}},
    ]


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
