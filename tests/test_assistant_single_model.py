"""M156 · 双模型路由钉测试（前身 M151.3 单模型钉子）。

历史脉络：
- M149 决策：Kimi K2.7-Code 不稳定且能力不比 GLM 强 → 全角色默认切到 GLM-5.2-fp8
  （单模型模式）。此文件原钉住「全角色 → GLM」。
- M156 恢复：Kimi-K2.7-Code 在 exo 已就绪（实测 2.5s 响应），切回双模型分工：
    architect/supervisor/overseer/monitor = GLM-5.2-fp8（编排者，1M 上下文）
    coder                          = Kimi-K2.7-Code-4bit（执行者，编码强 + MCP 强）
  解除 M147-A 熔断（GLM 单模型 reasoning_content 抢占 content 路径不可代码修复）。
  逃生门：export FLIPPED_CODER_MODEL=mlx-community/GLM-5.2-fp8 回退单模型。

4 例（M156 更新）：
1. mode=agent 时 architect→GLM、coder→Kimi（双模型分工）
   - 直接钉 `_model_id_for_alias` 默认值（生产代码层契约）
   - monkeypatch `resolve_model_config` 走 best-effort 回退，验证 `_make_llm(alias)` 拿到的 model 符合双模型分工
2. mode=chat 时 `_llm_chat` 收到的 model 与 resolve_worker_model_config 返回值一致
   - monkeypatch `resolve_worker_model_config` 返回 GLM
   - 调 `_run_chat` → 断言 `_llm_chat` 收到的 model 参数 == GLM（行为钉：chat 路径正确转发 model）
3. approve 路径在默认 env 下可走通
   - FLIPPED_MOCK_ORCHESTRATOR=1 走 mock resume（不触真实 LLM）
   - 钉：默认 env 下 approve 端点能正常返回 200 且 status 流转到 done

无生产代码改动——M156 仅改 _model_id_for_alias 默认值与 LiteLLM 配置；本文件钉行为。
"""
from __future__ import annotations

import os
import sys
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


GLM = "mlx-community/GLM-5.2-fp8"
KIMI = "mlx-community/Kimi-K2.7-Code-4bit"


# ---------- 1) mode=agent：双模型分工（architect→GLM、coder→Kimi） ----------

def test_model_id_for_alias_dual_model_defaults():
    """`_model_id_for_alias` 默认值钉 M156 双模型分工：

    - architect/supervisor/overseer/monitor → GLM-5.2-fp8（编排者，1M 上下文）
    - coder → Kimi-K2.7-Code-4bit（执行者，编码强 + MCP 强）

    env 不覆盖时验证默认映射。未来若有人把 coder 默认改回 GLM（单模型），
    本例会先红，强制显式决策 + 同步更新 LiteLLM 配置。
    """
    # 清掉所有可覆盖 env，确保测到的是默认值（而非本机 .env 的覆盖）
    env_keys = [
        "FLIPPED_ARCHITECT_MODEL", "FLIPPED_CODER_MODEL",
        "FLIPPED_SUPERVISOR_MODEL", "FLIPPED_OVERSEER_MODEL", "FLIPPED_MONITOR_MODEL",
    ]
    saved = {k: os.environ.pop(k, None) for k in env_keys}
    try:
        from driving.model_router import _model_id_for_alias
        # 编排角色 → GLM
        for alias in ("architect", "supervisor", "overseer", "monitor"):
            assert _model_id_for_alias(alias) == GLM, (
                f"alias={alias} 应默认解析到 {GLM}（M156 编排者角色），"
                f"实际 {_model_id_for_alias(alias)!r}。"
            )
        # 执行者 → Kimi
        assert _model_id_for_alias("coder") == KIMI, (
            f"alias=coder 应默认解析到 {KIMI}（M156 执行者角色），"
            f"实际 {_model_id_for_alias('coder')!r}。"
            f"如需回退单模型：export FLIPPED_CODER_MODEL=mlx-community/GLM-5.2-fp8"
        )
        # 未知 alias 原样透传（不强制映射）
        assert _model_id_for_alias("custom-llm") == "custom-llm"
    finally:
        for k, v in saved.items():
            if v is not None:
                os.environ[k] = v


@patch("driving.model_router.httpx.get")
def test_make_llm_resolves_dual_model_architect_glm_coder_kimi(mock_get, monkeypatch):
    """orchestrator 的 `_make_llm(alias)` 经 `resolve_model_config` 拿到对应模型。

    场景：LiteLLM proxy 不健康（httpx 抛错）→ 回退直连 exo，返回 full_model。
    钉 M156 双模型分工：architect → GLM-5.2-fp8，coder → Kimi-K2.7-Code-4bit。
    """
    monkeypatch.setenv("LITELLM_BASE_URL", "http://proxy.test/v1")
    monkeypatch.setenv("FLIPPED_MODEL_BASE_URL", "http://direct.test/v1")
    # 清 alias 覆盖 env，确保默认值生效
    for k in ("FLIPPED_ARCHITECT_MODEL", "FLIPPED_CODER_MODEL"):
        monkeypatch.delenv(k, raising=False)
    # 所有端点都不可达 → 走 best-effort 直连回退，返回 (direct_url, full_model)
    mock_get.side_effect = TimeoutError("proxy down")

    from driving.orchestrator import _make_llm

    # architect → GLM
    llm_a = _make_llm("architect")
    model_a = getattr(llm_a, "model_name", "") or getattr(llm_a, "model", "")
    assert model_a == GLM, f"_make_llm('architect') 应解析到 {GLM}，实际 {model_a!r}"

    # coder → Kimi
    llm_c = _make_llm("coder")
    model_c = getattr(llm_c, "model_name", "") or getattr(llm_c, "model", "")
    assert model_c == KIMI, f"_make_llm('coder') 应解析到 {KIMI}，实际 {model_c!r}"


# ---------- 2) mode=chat：_llm_chat 收到 GLM-5.2-fp8 ----------

@pytest.fixture()
def chat_client(monkeypatch, tmp_path):
    """隔离 DB + mock orchestrator + GLM 单模型 env，返回 TestClient。"""
    monkeypatch.setenv("FLIPPED_MOCK_ORCHESTRATOR", "1")
    monkeypatch.setattr("api.main.FLIPPED_CHECKPOINT_DB", str(tmp_path / "cp.db"))
    # 清 alias 覆盖，钉默认 GLM
    for k in ("FLIPPED_CODER_MODEL", "FLIPPED_ARCHITECT_MODEL"):
        monkeypatch.delenv(k, raising=False)
    from api.main import app
    return TestClient(app)


def test_run_chat_passes_glm_to_llm_chat(chat_client, monkeypatch):
    """mode=chat → `_run_chat` 调 `resolve_worker_model_config(alias)` 拿到 GLM，
    再把 GLM 传给 `_llm_chat`。钉：传给 _llm_chat 的 model 参数 == GLM-5.2-fp8。
    """
    # 直接 patch 源头 resolve_worker_model_config 返回 GLM（避免真实网络探测）
    captured = {"model": None}

    def _fake_resolve(alias="coder"):
        captured["alias"] = alias
        return "http://direct.test/v1", GLM

    monkeypatch.setattr("driving.model_router.resolve_worker_model_config", _fake_resolve)
    # _run_chat 内 `from driving.model_router import resolve_worker_model_config`
    # 是模块级 import（已绑定原函数对象），需同步 patch api.main 看到的引用
    # —— 但 _run_chat 是 `from driving.model_router import resolve_worker_model_config`
    #     在函数体内执行，每次调用都重新取最新绑定 → patch driving.model_router 即可
    async def _fake_llm_chat(base_url, model, system, user, timeout=120.0):
        captured["model"] = model
        captured["base_url"] = base_url
        captured["system"] = system
        return "ok from glm", None

    monkeypatch.setattr("api.main._llm_chat", _fake_llm_chat)

    # 建一个 chat 会话 → 发消息 → _run_chat 异步跑
    sid = chat_client.post(
        "/api/v1/assistant/sessions",
        json={"title": "chat-glm", "mode": "chat"},
    ).json()["id"]
    r = chat_client.post(
        f"/api/v1/assistant/sessions/{sid}/messages",
        json={"text": "hello", "mode": "chat", "model": "coder"},
    )
    assert r.status_code == 200, r.text

    # _run_chat 异步跑，轮询 store.events 直到看到 worker 消息或超时
    import time
    deadline = time.time() + 5.0
    while time.time() < deadline:
        # captured 已在异步任务里被填充（_fake_llm_chat 同步段）
        if captured["model"] is not None:
            break
        time.sleep(0.05)

    assert captured["model"] == GLM, (
        f"_llm_chat 应收到 {GLM}（M149 单模型），实际 {captured['model']!r}"
    )
    assert captured["alias"] == "coder"


# ---------- 3) approve 路径在单模型下可走通 ----------

def test_approve_path_works_under_single_model_env(monkeypatch, tmp_path):
    """单模型 env（无 Kimi 覆盖）下，approve 端点能正常放行 + 发 approval_result 事件 +
    触发 _resume_with_decision('approve')。

    钉：单模型 env 不会让 approve 路径抛异常或被守卫误拒。
    完整 resume→worker 续跑已在 test_assistant_approval_resume.py 覆盖，本例只钉
    「env 层 + 端点层」在单模型下通路成立。
    """
    monkeypatch.setenv("FLIPPED_MOCK_ORCHESTRATOR", "1")
    monkeypatch.setattr("api.main.FLIPPED_CHECKPOINT_DB", str(tmp_path / "cp.db"))
    # 清 alias 覆盖，钉默认 GLM（M149 单模型策略）
    for k in ("FLIPPED_CODER_MODEL", "FLIPPED_ARCHITECT_MODEL",
              "FLIPPED_SUPERVISOR_MODEL", "FLIPPED_OVERSEER_MODEL",
              "FLIPPED_MONITOR_MODEL"):
        monkeypatch.delenv(k, raising=False)

    from api.main import app, bus, store
    from api.schemas import EventType, Role

    client = TestClient(app)

    # 建会话
    sid = client.post(
        "/api/v1/assistant/sessions",
        json={"title": "approve-glm", "mode": "agent"},
    ).json()["id"]

    # emit pending approval_request（让 approve 端点的 _has_pending_approval 守卫通过）
    bus.emit(sid, EventType.approval_request, Role.system,
             {"action": "git push origin main", "reason": "高风险子任务"})

    # patch _resume_with_decision 验证被正确调用（不跑真实 resume，避免异步时序问题）
    called = {"decision": None, "sid": None}

    async def _fake_resume(session_id, decision):
        called["decision"] = decision
        called["sid"] = session_id

    monkeypatch.setattr("api.assistant._resume_with_decision", _fake_resume)

    # 调 approve
    r = client.post(f"/api/v1/assistant/sessions/{sid}/approve")
    assert r.status_code == 200, r.text
    assert r.json()["decision"] == "approve"

    # approval_result 事件应落库
    events = store.events(sid)
    types = [e.type for e in events]
    assert "approval_result" in types, "approve 应发 approval_result 事件"

    # _resume_with_decision 应被异步调用；轮询一小段时间等 asyncio.create_task 跑完
    import time
    deadline = time.time() + 2.0
    while time.time() < deadline and called["decision"] is None:
        time.sleep(0.02)
    assert called["decision"] == "approve", (
        f"_resume_with_decision 应以 'approve' 被调用，实际 {called['decision']!r}"
    )
    assert called["sid"] == sid
