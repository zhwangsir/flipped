"""M176.1 · Goal 模式纯状态机（api/goal.py）。

契约（PLAN.md M176）：
- build_iter_prompt：第 1 轮 objective 原文；第 ≥2 轮续跑提示含 objective + gap + 第 i/n 轮。
- build_judge_messages：[system, user] 两条；system 首行 JUDGE_MARKER；user 截断 800/400。
- parse_judge_reply：宽松解析（fence/噪音容忍），缺字段缺省，非 JSON 抛 JudgeParseError。
- record_verdict：achieved / continue（记签名）/ exhausted_no_progress（归一化同 gap 连续 2 次）
  / exhausted_judge_errors（连续 2 次 None）。
- goal_payload：公共字段 + extra 透传。
- summarize_goal_events：事件流重建最新 goal 状态，供 GET 端点。
"""
from __future__ import annotations

import os
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from api.goal import (  # noqa: E402
    JUDGE_MARKER,
    GoalState,
    JudgeParseError,
    build_iter_prompt,
    build_judge_messages,
    goal_payload,
    parse_judge_reply,
    record_verdict,
    summarize_goal_events,
)


# ---------- build_iter_prompt ----------

def test_iter_prompt_first_round_returns_objective_verbatim():
    state = GoalState(objective="修复所有 TS 错误", iteration=1)
    assert build_iter_prompt(state) == "修复所有 TS 错误"


def test_iter_prompt_second_round_contains_objective_gap_and_counter():
    state = GoalState(objective="让 pnpm test 全过", max_iterations=5, iteration=2, last_gap="还剩 3 处断言失败")
    prompt = build_iter_prompt(state)
    assert prompt == (
        "【目标】让 pnpm test 全过\n"
        "【第 2/5 轮】上一轮未达成，差距：还剩 3 处断言失败\n"
        "请继续推进，直到目标达成。"
    )


# ---------- build_judge_messages ----------

def test_judge_messages_exactly_two_and_marker_on_system_first_line():
    state = GoalState(objective="目标X")
    msgs = build_judge_messages(state, "assistant 回复", "tool 结果")
    assert len(msgs) == 2
    assert msgs[0]["role"] == "system"
    assert msgs[1]["role"] == "user"
    assert msgs[0]["content"].split("\n", 1)[0] == JUDGE_MARKER
    assert "目标X" in msgs[1]["content"]
    assert "assistant 回复" in msgs[1]["content"]
    assert "tool 结果" in msgs[1]["content"]


def test_judge_messages_truncates_assistant_800_and_tool_400():
    state = GoalState(objective="obj")
    msgs = build_judge_messages(state, "a" * 1000, "b" * 600)
    user = msgs[1]["content"]
    assert "a" * 800 in user
    assert "a" * 801 not in user
    assert "b" * 400 in user
    assert "b" * 401 not in user


def test_judge_messages_notes_absent_tool_result():
    state = GoalState(objective="obj")
    msgs = build_judge_messages(state, "回复", "")
    assert "无" in msgs[1]["content"]


# ---------- parse_judge_reply ----------

def test_parse_bare_json():
    assert parse_judge_reply('{"achieved": true, "gap": ""}') == {"achieved": True, "gap": ""}


def test_parse_fenced_json():
    text = '```json\n{"achieved": false, "gap": "还差一步"}\n```'
    assert parse_judge_reply(text) == {"achieved": False, "gap": "还差一步"}


def test_parse_json_with_noise_around():
    text = '好的，判定如下：{"achieved": false, "gap": "测试未跑"} 以上。'
    assert parse_judge_reply(text) == {"achieved": False, "gap": "测试未跑"}


def test_parse_missing_fields_default():
    assert parse_judge_reply('{"gap": "只有gap"}') == {"achieved": False, "gap": "只有gap"}
    assert parse_judge_reply('{"achieved": true}') == {"achieved": True, "gap": ""}


def test_parse_non_json_raises():
    with pytest.raises(JudgeParseError):
        parse_judge_reply("目标没有达成，因为测试还在失败。")
    with pytest.raises(JudgeParseError):
        parse_judge_reply("{broken json")


# ---------- record_verdict ----------

def test_record_achieved_sets_status():
    state = GoalState(objective="x")
    assert record_verdict(state, {"achieved": True, "gap": ""}) == "achieved"
    assert state.status == "achieved"


def test_record_continue_records_sig_and_last_gap():
    state = GoalState(objective="x")
    assert record_verdict(state, {"achieved": False, "gap": "缺测试"}) == "continue"
    assert state.status == "running"
    assert state.last_gap == "缺测试"
    assert state._gap_sigs == ["缺测试"]
    assert state._judge_errors == 0


def test_record_no_progress_normalized_digits_same_gap():
    """"还剩3处错误" vs "还剩2处错误"：归一化（去数字/空白）后判同 → 无进展熔断。"""
    state = GoalState(objective="修复所有错误")
    assert record_verdict(state, {"achieved": False, "gap": "还剩3处错误"}) == "continue"
    assert record_verdict(state, {"achieved": False, "gap": "还剩 2 处错误"}) == "exhausted_no_progress"
    assert state.status == "exhausted"


def test_record_judge_errors_two_consecutive_none_with_reset():
    state = GoalState(objective="x")
    assert record_verdict(state, None) == "continue"
    assert state.last_gap == "judge 失败"
    # 中间一次成功判定 → 错误计数清零
    assert record_verdict(state, {"achieved": False, "gap": "g1"}) == "continue"
    assert record_verdict(state, None) == "continue"  # 重新计 1
    assert record_verdict(state, None) == "exhausted_judge_errors"
    assert state.status == "exhausted"


# ---------- goal_payload ----------

def test_goal_payload_common_fields_and_extra_passthrough():
    state = GoalState(objective="obj", max_iterations=3, iteration=2)
    p = goal_payload("iter", state, prompt="P", gap="G")
    assert p == {"phase": "iter", "objective": "obj", "iteration": 2,
                 "max_iterations": 3, "prompt": "P", "gap": "G"}
    pj = goal_payload("judge", state, achieved=False, gap="g")
    assert pj["phase"] == "judge" and pj["achieved"] is False and pj["gap"] == "g"
    pe = goal_payload("exhausted", state, reason="max_iter", gap="")
    assert pe["reason"] == "max_iter" and pe["phase"] == "exhausted"
    for phase in ("set", "stopped"):
        pp = goal_payload(phase, state)
        assert pp["phase"] == phase
        assert pp["objective"] == "obj"
        assert pp["iteration"] == 2
        assert pp["max_iterations"] == 3


# ---------- summarize_goal_events ----------

class _FakeEnum:
    def __init__(self, value):
        self.value = value


def _ev(etype, payload):
    return SimpleNamespace(type=etype, payload=payload)


def test_summarize_empty_list_returns_none():
    assert summarize_goal_events([]) is None


def test_summarize_no_goal_events_returns_none():
    events = [_ev("message", {"text": "hi"}), _ev("status", {"phase": "done"})]
    assert summarize_goal_events(events) is None


def test_summarize_set_and_iter_rebuilds_running_state():
    events = [
        _ev("goal", {"phase": "set", "objective": "obj", "max_iterations": 4}),
        _ev("goal", {"phase": "iter", "iteration": 2, "prompt": "p", "gap": "还差"}),
    ]
    got = summarize_goal_events(events)
    assert got == {"objective": "obj", "status": "running", "iteration": 2,
                   "max_iterations": 4, "gap": "还差"}


def test_summarize_terminal_phase_sets_status():
    events = [
        _ev("goal", {"phase": "set", "objective": "obj", "max_iterations": 5}),
        _ev("goal", {"phase": "iter", "iteration": 1, "prompt": "obj"}),
        _ev("goal", {"phase": "judge", "iteration": 1, "achieved": True, "gap": ""}),
        _ev("goal", {"phase": "achieved", "iteration": 1}),
    ]
    got = summarize_goal_events(events)
    assert got["status"] == "achieved"
    assert got["iteration"] == 1
    assert got["gap"] == ""

    events2 = [
        _ev("goal", {"phase": "set", "objective": "o2", "max_iterations": 2}),
        _ev("goal", {"phase": "exhausted", "iteration": 2, "reason": "no_progress", "gap": "g"}),
    ]
    got2 = summarize_goal_events(events2)
    assert got2["status"] == "exhausted"
    assert got2["gap"] == "g"

    events3 = [
        _ev("goal", {"phase": "set", "objective": "o3", "max_iterations": 3}),
        _ev("goal", {"phase": "stopped", "iteration": 1}),
    ]
    assert summarize_goal_events(events3)["status"] == "stopped"


def test_summarize_accepts_enum_event_type():
    events = [
        _ev(_FakeEnum("goal"), {"phase": "set", "objective": "obj", "max_iterations": 5}),
        _ev(_FakeEnum("goal"), {"phase": "iter", "iteration": 1}),
    ]
    got = summarize_goal_events(events)
    assert got["status"] == "running"
    assert got["iteration"] == 1
