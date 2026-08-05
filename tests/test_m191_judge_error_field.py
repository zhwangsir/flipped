"""M191.1 · judge 熔断计数结构化恢复（消化 L-M188-4）。

痛点：rebuild_running 重放 judge 事件时靠 gap=="judge 失败" 哨兵串识别 judge 失败，
真实 judge verdict 的 gap 若恰为该串，重启后会被误计为 judge 错误，熔断计数被污染。
修复：judge emit 增 error=verdict is None 结构化字段；重放结构化优先、哨兵兜底。

纯 goal.py 层测试（零 FastAPI）。构造方式沿用 test_m188_goal_resume.py 的 Event 风格。
"""
from __future__ import annotations

from api.goal import _gap_sig, rebuild_running
from api.schemas import Event, EventType, Role


def _ev(phase: str, **payload) -> Event:
    return Event(id="e", session_id="s", type=EventType.goal, agent=Role.system,
                 payload={"phase": phase, **payload})


def _one_judged_round(**judge_kw) -> list:
    return [_ev("set", objective="G", max_iterations=9),
            _ev("iter", iteration=1),
            _ev("judge", iteration=1, **judge_kw)]


def test_old_format_sentinel_fallback_counts_error():
    """旧格式（无 error 键、gap=="judge 失败"）→ 哨兵兜底仍计 1 次 judge 错误（兼容）。"""
    evs = _one_judged_round(achieved=False, gap="judge 失败")
    state, start = rebuild_running(evs)
    assert start == 2
    assert state._judge_errors == 1
    assert state.last_gap == "judge 失败"
    assert state._gap_sigs == []


def test_new_format_error_true_counts_error():
    """新格式 error=True（gap 任意，哪怕不是哨兵串）→ 计 1 次 judge 错误。"""
    evs = _one_judged_round(achieved=False, gap="真实差距描述", error=True)
    state, start = rebuild_running(evs)
    assert start == 2
    assert state._judge_errors == 1
    assert state.last_gap == "judge 失败"
    assert state._gap_sigs == [], "judge 错误的 gap 不得入签名序列"


def test_new_format_error_false_sentinel_gap_not_counted():
    """核心修复：真实 judge verdict 的 gap 恰好撞哨兵串「judge 失败」，
    有 error=False 结构化字段 → 不误计为 judge 错误，gap 正常入签名序列。"""
    evs = _one_judged_round(achieved=False, gap="judge 失败", error=False)
    state, start = rebuild_running(evs)
    assert start == 2
    assert state._judge_errors == 0, "撞串不得污染熔断计数"
    assert state.last_gap == "judge 失败"
    assert state._gap_sigs == [_gap_sig("judge 失败")], "真实 gap 须入签名序列"


def test_new_format_error_false_normal_gap_no_regression():
    """error=False 正常未达成 gap → errors 清零 + 入签名序列（既有语义不回归）。"""
    evs = _one_judged_round(achieved=False, gap="还差A", error=False)
    state, start = rebuild_running(evs)
    assert start == 2
    assert state._judge_errors == 0
    assert state.last_gap == "还差A"
    assert state._gap_sigs == [_gap_sig("还差A")]


def test_new_format_achieved_clears_errors():
    """error=False 且 achieved=True → errors 清零、不入签名序列。"""
    evs = [_ev("set", objective="G", max_iterations=9),
           _ev("iter", iteration=1),
           _ev("judge", iteration=1, achieved=False, gap="g1", error=False),
           _ev("iter", iteration=2),
           _ev("judge", iteration=2, achieved=True, gap="", error=False)]
    # achieved 轮之后必落 achieved 终态事件（同协程顺序），这里只验证重放字段语义：
    # 手动不放终态事件以观察重放结果
    state, start = rebuild_running(evs)
    assert start == 3
    assert state._judge_errors == 0
    assert state._gap_sigs == [_gap_sig("g1")]
