"""M202 契约测试：GLM worker 长程可靠性三件套。

背景（M201 FAIL 证据链，TEST_LOG.md 2026-08-08）：
- 写后必追加独立验证命令 → 沙盒拒绝 "Cannot execute multiple commands
  at once" 30+ 次，agent 温度 0 下同会话永不自愈 → 0 次 finish 调用；
- 「活干完了但交不了卷」：utils.py 已正确写盘，迭代耗尽于验证拒绝循环；
- max_iterations=5 在单命令+&&链式下预算偏紧；
- 缺早停：同一沙盒错误空转到 3h task timeout。

M202 三件套：
- (a) SP 注入 <COMMAND_DISCIPLINE> 硬约束（单 tool call/&& 链式/过检即 finish）；
- (b) max_iterations 默认 5→8（FLIPPED_WORKER_MAX_ITERATIONS 仍可覆盖）；
- (c) 重复错误签名追踪：同一归一化错误 ≥N 次（默认 3，
  FLIPPED_WORKER_ERROR_ABORT_THRESHOLD 可配）→ 远程 pause() 早停，
  run() 收尾抛 RepeatedErrorAbort → orchestrator 归类任务级失败回灌 supervisor。
"""
from __future__ import annotations

import time
from types import SimpleNamespace

import pytest

from api.events import EventBus
from api.session import SessionStore
from executor.openhands_worker import OpenHandsWorker


def _worker(**kw):
    return OpenHandsWorker("s", "t", EventBus(SessionStore()),
                           manage_session_status=False, **kw)


def _obs_event(text: str = "", *, tool: str = "terminal", success: bool = True,
               exit_code: int = 0) -> SimpleNamespace:
    """伪造最小 ObservationEvent（duck-typing，不依赖 SDK 类）。"""
    obs = SimpleNamespace(success=success, exit_code=exit_code,
                          output=text, content=None, command="cmd")
    return SimpleNamespace(tool_name=tool, observation=obs)


# ---------- (a) SP 硬约束 ----------


def test_sp_contains_command_discipline(monkeypatch):
    """精简 SP 必须含 COMMAND_DISCIPLINE 段及三条硬约束要点，且不突破窗口预算。"""
    monkeypatch.delenv("FLIPPED_WORKER_SP_DEFAULT", raising=False)
    sp = _worker()._worker_system_prompt()
    assert sp is not None
    assert "<COMMAND_DISCIPLINE>" in sp
    # 要点 1：单 tool call（M201 根因 1——多命令被拒）
    assert "ONE tool call" in sp or "one tool call" in sp
    # 要点 2：&& 链式合并写+验证
    assert "&&" in sp
    # 要点 3：验证通过立即 finish，不再回读确认
    assert "finish" in sp.lower()
    # M149.16 窗口预算不破（SP+tools 固定开销必须 <<14500ch 稳定窗口）
    assert len(sp) < 5000


# ---------- (b) 迭代预算 ----------


def test_max_iterations_default_8(monkeypatch):
    """M202(b)：默认 5→8。单命令+&&链式让每轮做更多事，
    早停(c)兜底防空转，8 轮给复杂子任务留验证余量。"""
    monkeypatch.delenv("FLIPPED_WORKER_MAX_ITERATIONS", raising=False)
    assert _worker().max_iterations == 8


def test_max_iterations_env_still_overrides(monkeypatch):
    monkeypatch.setenv("FLIPPED_WORKER_MAX_ITERATIONS", "5")
    assert _worker().max_iterations == 5


# ---------- (c) 重复错误早停 ----------


def test_error_signature_sandbox_rejection():
    """沙盒多命令拒绝必须被识别为错误签名。"""
    w = _worker()
    ev = _obs_event("Cannot execute multiple commands at once")
    assert w._observation_error_signature(ev) is not None


def test_marker_signature_stable_across_varying_payloads():
    """回归（2026-08-10 E2E 实测 11 次拒绝 0 次早停）：沙盒拒绝文本附带
    每次不同的命令内容（Provided commands: ...），全文归一化会导致同形
    错误签名互不相同、早停永不触发。命中标记的签名必须只含标记本身。"""
    w = _worker()
    t1 = ("Cannot execute multiple commands at once.\nProvided commands:\n"
          "(1) cat > /tmp/a/calc.py <<'EOF'\ndef add(a,b): return a+b\nEOF\n"
          "(2) cat /tmp/a/calc.py")
    t2 = ("Cannot execute multiple commands at once.\nProvided commands:\n"
          "(1) cat > /tmp/b/utils.py <<'EOF'\ndef sub(a,b): return a-b\nEOF\n"
          "(2) pytest /tmp/b/tests/ -q")
    sig1 = w._observation_error_signature(_obs_event(t1))
    sig2 = w._observation_error_signature(_obs_event(t2))
    assert sig1 is not None and sig1 == sig2
    assert "marker" in sig1


def test_error_signature_digit_normalization():
    """数字归一：同形错误（不同行号/计数）归并到同一签名。"""
    w = _worker()
    sig1 = w._observation_error_signature(
        _obs_event("line 12: SyntaxError at col 3", exit_code=1))
    sig2 = w._observation_error_signature(
        _obs_event("line 99: SyntaxError at col 7", exit_code=1))
    assert sig1 is not None and sig1 == sig2


def test_error_signature_ignores_success_and_empty_failures():
    """成功观测不签名；exit!=0 但无输出的探测性命令（如 grep 空匹配）不签名——
    防止探索期误伤（M202 只打同形错误循环）。"""
    w = _worker()
    assert w._observation_error_signature(_obs_event("all ok", exit_code=0)) is None
    assert w._observation_error_signature(_obs_event("", exit_code=1)) is None
    assert w._observation_error_signature(
        _obs_event("", success=False)) is not None  # 显式失败无文本也要可追踪


def test_repeated_identical_errors_trigger_abort(monkeypatch):
    """同一错误签名累计 ≥3 次 → 置 abort_reason 并远程 pause() 早停。"""
    monkeypatch.delenv("FLIPPED_WORKER_ERROR_ABORT_THRESHOLD", raising=False)
    w = _worker()
    calls: list[str] = []

    class FakeConv:
        def pause(self):
            calls.append("pause")

    w._conversation = FakeConv()
    ev = _obs_event("Cannot execute multiple commands at once")
    for _ in range(2):
        w._track_and_maybe_abort(ev)
    assert w._abort_reason is None
    w._track_and_maybe_abort(ev)  # 第 3 次 → 触发
    assert w._abort_reason is not None
    assert "RepeatedErrorAbort" in w._abort_reason
    # pause 在 daemon 线程触发，短暂等待兑现
    for _ in range(50):
        if calls:
            break
        time.sleep(0.02)
    assert calls == ["pause"]


def test_distinct_errors_do_not_abort(monkeypatch):
    """不同签名各自计数，互不叠加：2+2 次不同错误不触停（默认阈值 3）。"""
    monkeypatch.delenv("FLIPPED_WORKER_ERROR_ABORT_THRESHOLD", raising=False)
    w = _worker()
    w._conversation = SimpleNamespace(pause=lambda: pytest.fail("不应 pause"))
    for _ in range(2):
        w._track_and_maybe_abort(_obs_event("Cannot execute multiple commands at once"))
        w._track_and_maybe_abort(
            _obs_event("pytest: 1 failed, 2 passed", exit_code=1))
    assert w._abort_reason is None


def test_abort_threshold_env_configurable(monkeypatch):
    monkeypatch.setenv("FLIPPED_WORKER_ERROR_ABORT_THRESHOLD", "5")
    w = _worker()
    assert w.error_abort_threshold == 5
    w._conversation = SimpleNamespace(pause=lambda: pytest.fail("未到阈值不应 pause"))
    ev = _obs_event("Cannot execute multiple commands at once")
    for _ in range(4):
        w._track_and_maybe_abort(ev)
    assert w._abort_reason is None


def test_abort_only_once(monkeypatch):
    """触停后不再重复 pause（幂等）。"""
    monkeypatch.delenv("FLIPPED_WORKER_ERROR_ABORT_THRESHOLD", raising=False)
    w = _worker()
    calls: list[str] = []
    w._conversation = SimpleNamespace(pause=lambda: calls.append("pause"))
    ev = _obs_event("Cannot execute multiple commands at once")
    for _ in range(5):
        w._track_and_maybe_abort(ev)
    for _ in range(50):
        if calls:
            break
        time.sleep(0.02)
    assert calls == ["pause"]
    assert w._abort_reason is not None


def test_raise_if_aborted_only_when_not_done():
    """run() 收尾：abort 且任务未自然完成 → 抛 RepeatedErrorAbort（orchestrator
    按 tool_calls>0 归任务级失败回灌 supervisor）；若 agent 已自行 finish
    （status_done=True）则不抛——活干完了就交卷。"""
    w = _worker()
    w._raise_if_aborted(status_done=True)   # 无 abort → 不抛
    w._abort_reason = "RepeatedErrorAbort: 同一错误 3 次"
    w._raise_if_aborted(status_done=True)   # 已 finish → 不抛
    with pytest.raises(RuntimeError, match="RepeatedErrorAbort"):
        w._raise_if_aborted(status_done=False)
