"""M149.20 — Worker 上下文压缩（condenser）配置契约测试。

M149.20 决定性结论：LLM condenser 在当前栈上【数学不成立】。
GLM-5.2-fp8 经 exo 稳定窗口 ~3300 tok；固定开销(SP+tools)已 ~2200 tok。
LLMSummarizingCondenser 的 max_tokens 语义 = 含 SP+tools 的 view 总阈值，
压缩调用本身也占上下文（~2000+ tok），留给主循环余量几乎为零。
实测（verify_m149_condenser.py，M149.18）：72 次相同摘要请求，主循环零推进。

策略：默认 NoOp + 短会话（max_iterations=15）+ 编排层分解。
FLIPPED_WORKER_CONDENSER_ENABLED=1 可重新启用（不推荐）。
"""
from api.events import EventBus
from api.session import SessionStore
from executor.openhands_worker import OpenHandsWorker


def _worker(**kw):
    return OpenHandsWorker("s", "t", EventBus(SessionStore()), **kw)


def test_condenser_default_disabled(monkeypatch):
    """M149.20：默认 NoOp——LLM condenser 数学不成立（max_tokens 需 ≥4048 > 悬崖）。
    固定开销(SP2600+tools6300)~2200tok + 压缩调用~2000tok > 稳定窗口3300tok。"""
    monkeypatch.delenv("FLIPPED_WORKER_CONDENSER_ENABLED", raising=False)
    monkeypatch.delenv("FLIPPED_WORKER_CONDENSER_DISABLED", raising=False)
    assert _worker()._build_condenser("dummy-key") is None


def test_condenser_enabled_escape_hatch(monkeypatch):
    """逃生门：FLIPPED_WORKER_CONDENSER_ENABLED=1 可重新启用 LLM condenser。
    不推荐——实测死循环（72 次相同摘要请求），仅留作对照实验入口。"""
    monkeypatch.setenv("FLIPPED_WORKER_CONDENSER_ENABLED", "1")
    monkeypatch.delenv("FLIPPED_WORKER_CONDENSER_MAX_TOKENS", raising=False)
    monkeypatch.delenv("FLIPPED_WORKER_CONDENSER_MAX_SIZE", raising=False)
    from openhands.sdk.context.condenser import LLMSummarizingCondenser

    c = _worker()._build_condenser("dummy-key")
    assert isinstance(c, LLMSummarizingCondenser)
    assert c.max_tokens == 2800
    assert c.max_size == 12
    assert c.keep_first == 2


def test_condenser_llm_config(monkeypatch):
    """压缩用 LLM：temperature=0（fp8 数值稳定）、走同一 proxy、短超时——
    总结 prompt 在窗口内必须稳，不能因压缩调用本身再引入乱码。"""
    monkeypatch.setenv("FLIPPED_WORKER_CONDENSER_ENABLED", "1")
    monkeypatch.setenv("LITELLM_MASTER_KEY", "env-key")
    c = _worker()._build_condenser("dummy-key")
    assert c.llm.temperature == 0.0
    assert "4000" in (c.llm.base_url or "")
    # 压缩 LLM 超时应短于主 LLM（总结是短任务）
    assert c.llm.timeout <= 600


def test_condenser_env_overrides(monkeypatch):
    monkeypatch.setenv("FLIPPED_WORKER_CONDENSER_ENABLED", "1")
    monkeypatch.setenv("FLIPPED_WORKER_CONDENSER_MAX_TOKENS", "800")
    monkeypatch.setenv("FLIPPED_WORKER_CONDENSER_MAX_SIZE", "24")
    c = _worker()._build_condenser("k")
    assert c.max_tokens == 800
    assert c.max_size == 24


def test_max_iterations_default_reduced(monkeypatch):
    """M149.20：max_iterations 默认 15（非 200）——GLM-5.2-fp8 稳定窗口
    ~11-12k chars，固定开销~8.2k，留给多轮历史~3-4k chars ≈ 2-3 轮。
    15 轮已远超窗口极限，超过必然乱码。复杂任务由编排层拆短。"""
    monkeypatch.delenv("FLIPPED_WORKER_MAX_ITERATIONS", raising=False)
    assert _worker().max_iterations == 15


def test_max_iterations_env_override(monkeypatch):
    monkeypatch.setenv("FLIPPED_WORKER_MAX_ITERATIONS", "50")
    assert _worker().max_iterations == 50
