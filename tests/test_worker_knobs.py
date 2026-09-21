"""F8 经验 — Worker 迭代上限/超时旋钮环境变量化(默认与原值一致)。"""
from api.events import EventBus
from api.session import SessionStore
from executor.openhands_worker import OpenHandsWorker


def _worker(**kw):
    return OpenHandsWorker("s", "t", EventBus(SessionStore()), **kw)


def test_defaults_unchanged(monkeypatch):
    """M131 质量优先：默认 timeout=3600s（1小时）；
    M149.20：max_iterations=15（非 200，GLM-5.2-fp8 稳定窗口约束）；
    M3.1：max_iterations=5（非 15，进一步匹配 2-3 轮窗口极限）；
    M202(b)：max_iterations=8（COMMAND_DISCIPLINE 单轮做更多事 +
    重复错误早停兜底，契约见 test_m202_worker_discipline.py）。"""
    monkeypatch.delenv("FLIPPED_WORKER_TIMEOUT", raising=False)
    monkeypatch.delenv("FLIPPED_WORKER_MAX_ITERATIONS", raising=False)
    w = _worker()
    assert w.timeout == 3600.0
    assert w.max_iterations == 8


def test_env_overrides(monkeypatch):
    monkeypatch.setenv("FLIPPED_WORKER_TIMEOUT", "300")
    monkeypatch.setenv("FLIPPED_WORKER_MAX_ITERATIONS", "25")
    w = _worker()
    assert w.timeout == 300.0
    assert w.max_iterations == 25


def test_explicit_timeout_beats_env(monkeypatch):
    monkeypatch.setenv("FLIPPED_WORKER_TIMEOUT", "300")
    assert _worker(timeout=120.0).timeout == 120.0


# --- M147/M148 · FLIPPED_WORKER_ENABLE_THINKING 熔断开关 ---


def test_thinking_default_disabled(monkeypatch):
    """M149.6 起默认 false：GLM-5.2-fp8 经 exo 时 thinking on 必乱码
    （debug_glm_replay_oh.py 变体 C/F 实测，与 stream 无关），唯一稳定路径是
    thinking off + 非 stream（OH SDK LLM 默认 stream=False）。env 未设时
    enable_thinking=False，且两入口（顶层 + chat_template_kwargs）一致。"""
    monkeypatch.delenv("FLIPPED_WORKER_ENABLE_THINKING", raising=False)
    body = OpenHandsWorker._thinking_extra_body()
    assert body == {
        "enable_thinking": False,
        "chat_template_kwargs": {"enable_thinking": False},
        # EXO 1.0.71+ 唯一生效的关 thinking 开关（2026-08-10 真机实测）
        "reasoning_effort": "none",
    }


def test_thinking_explicit_enabled(monkeypatch):
    for raw in ("true", "1", "yes", "on", "TRUE"):
        monkeypatch.setenv("FLIPPED_WORKER_ENABLE_THINKING", raw)
        assert OpenHandsWorker._thinking_extra_body()["enable_thinking"] is True, raw


def test_thinking_disabled_values(monkeypatch):
    """0/false/off/no（大小写不敏感、首尾空白容忍）→ 关 thinking 换速度。

    背景：GLM-5.2-fp8 在 enable_thinking=true 时输出全进 reasoning_content
    （content 空白）且 5.5 tok/s → 单任务 2-3h 超 1h 超时，M147 据此熔断。
    """
    for raw in ("0", "false", "off", "no", "FALSE", " Off ", "NO"):
        monkeypatch.setenv("FLIPPED_WORKER_ENABLE_THINKING", raw)
        body = OpenHandsWorker._thinking_extra_body()
        assert body["enable_thinking"] is False, raw
        # 两入口必须一致——只关顶层而 chat_template 仍 true 会被模板层重新打开
        assert body["chat_template_kwargs"]["enable_thinking"] is False, raw
