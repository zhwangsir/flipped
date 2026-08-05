"""M176 · Goal 模式纯状态机（/goal 目标驱动自循环 + 逐轮 LLM judge 验证）。

零 FastAPI / 零 LLM / 零 subprocess / 零网络，纯确定性。
B 队（assistant.py/main.py）消费本模块：_goal_loop 逐轮 build_iter_prompt 派发、
_judge 用 build_judge_messages + parse_judge_reply 校验、record_verdict 决策、
goal_payload 构造事件 payload、GET 端点用 summarize_goal_events 重建状态。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

JUDGE_MARKER = "GOAL_JUDGE_V1"  # judge system prompt 首行标记，黑盒假 LLM server 据此分流

# judge 证据截断上限
_JUDGE_ASSISTANT_MAX = 800
_JUDGE_TOOL_MAX = 400

# 连续 judge 解析/调用失败熔断阈值
_JUDGE_ERROR_LIMIT = 2

_TERMINAL_PHASES = ("achieved", "exhausted", "stopped")

# M188.1 · verify_cmd 确定性校验：未通过时 gap 只留输出尾部 400 字符
_VERIFY_TAIL_MAX = 400


def verify_available(verify_cmd: list[str] | None) -> bool:
    """是否存在可用的确定性校验命令。

    None / [] / ["true"]（「无验收命令」哨兵）→ False（回落 LLM judge）；其余 → True。
    """
    if not verify_cmd or verify_cmd == ["true"]:
        return False
    return True


def verify_verdict(ok: bool, output: str) -> dict:
    """verify_cmd 执行结果 → judge verdict 形状（{"achieved": bool, "gap": str}）。"""
    if ok:
        return {"achieved": True, "gap": ""}
    tail = (output or "")[-_VERIFY_TAIL_MAX:] or "(无输出)"
    return {"achieved": False, "gap": f"verify_cmd 未通过(exit≠0): {tail}"}


class JudgeParseError(Exception):
    """judge 回复完全找不到可解析 JSON。"""


@dataclass
class GoalState:
    objective: str
    max_iterations: int = 5
    iteration: int = 0           # 已完成的轮数
    status: str = "running"      # running|achieved|exhausted|stopped
    last_gap: str = ""
    stop_requested: bool = False
    _gap_sigs: list[str] = field(default_factory=list)   # 归一化 gap 签名历史
    _judge_errors: int = 0                                # 连续 judge 错误计数


def build_iter_prompt(state: GoalState) -> str:
    """state.iteration 已由调用方设为当前轮号 i（1 起）。

    第 1 轮返回 objective 原文；第 ≥2 轮返回续跑提示。
    """
    if state.iteration <= 1:
        return state.objective
    return (
        f"【目标】{state.objective}\n"
        f"【第 {state.iteration}/{state.max_iterations} 轮】上一轮未达成，差距：{state.last_gap}\n"
        "请继续推进，直到目标达成。"
    )


def build_judge_messages(state: GoalState, last_assistant: str, last_tool: str) -> list[dict]:
    """返回 [system, user] 两条消息。system 首行必须是 JUDGE_MARKER。"""
    system = (
        f"{JUDGE_MARKER}\n"
        "你是目标达成校验器，只依据给定证据判断用户目标是否已达成，"
        '只输出 JSON {"achieved": true/false, "gap": "未达成时的差距说明"}，'
        "不输出任何其他文字。"
    )
    tool_summary = last_tool[:_JUDGE_TOOL_MAX] if last_tool else "无"
    user = (
        f"【目标】{state.objective}\n"
        f"【末轮助手回复】{last_assistant[:_JUDGE_ASSISTANT_MAX]}\n"
        f"【末轮工具结果】{tool_summary}"
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def parse_judge_reply(text: str) -> dict:
    """宽松解析 judge 回复 → {"achieved": bool, "gap": str}。

    先剥 ```json fence；再找首个 { 到配对最后一个 } 的子串 json.loads；
    achieved 缺省 False、gap 缺省 ""；完全找不到可解析 JSON → JudgeParseError。
    """
    s = (text or "").strip()
    if s.startswith("```"):
        s = "\n".join(
            line for line in s.splitlines() if not line.strip().startswith("```")
        ).strip()
    start = s.find("{")
    end = s.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise JudgeParseError(f"judge 回复中找不到 JSON 对象: {s[:80]!r}")
    try:
        data = json.loads(s[start:end + 1])
    except json.JSONDecodeError as exc:
        raise JudgeParseError(f"judge 回复 JSON 解析失败: {exc}") from exc
    if not isinstance(data, dict):
        raise JudgeParseError(f"judge 回复不是 JSON 对象: {s[:80]!r}")
    return {
        "achieved": bool(data.get("achieved", False)),
        "gap": str(data.get("gap") or ""),
    }


def _gap_sig(gap: str) -> str:
    """归一化 gap 签名：lower + 去所有空白 + 去所有数字。

    防"还剩3处" vs "还剩2处"被误判为有进展。
    """
    return re.sub(r"[\s\d]+", "", gap.lower())


def record_verdict(state: GoalState, verdict: dict | None) -> str:
    """记录 judge 判定并返回决策。

    verdict None = judge 解析/调用失败。返回：
    "achieved" | "continue" | "exhausted_no_progress" | "exhausted_judge_errors"。
    调用方在 iteration 已达 max_iterations 时不调本函数（直接 exhausted_max_iter）。
    """
    if verdict is None:
        state._judge_errors += 1
        if state._judge_errors >= _JUDGE_ERROR_LIMIT:
            state.status = "exhausted"
            return "exhausted_judge_errors"
        state.last_gap = "judge 失败"
        return "continue"
    if verdict.get("achieved"):
        state.status = "achieved"
        return "achieved"
    state._judge_errors = 0
    gap = str(verdict.get("gap") or "")
    state.last_gap = gap
    state._gap_sigs.append(_gap_sig(gap))
    if len(state._gap_sigs) >= 2 and state._gap_sigs[-1] == state._gap_sigs[-2]:
        state.status = "exhausted"
        return "exhausted_no_progress"
    return "continue"


def has_pending_approval(events: list) -> bool:
    """M191.2 · 事件流中是否存在「未被 approval_result 回答的 approval_request」。

    逆序扫：先遇 approval_request → True；先遇 approval_result / 都没有 → False。
    events 元素的 type 可能是 enum（取 .value）或字符串。
    （与 assistant._has_pending_approval 同语义；goal.py 零 import 红线不破。）
    """
    for ev in reversed(events):
        etype = getattr(ev.type, "value", ev.type)
        if etype == "approval_request":
            return True
        if etype == "approval_result":
            return False
    return False


def rebuild_running(events: list) -> tuple[GoalState, int] | None:
    """M188.2 · 从事件流重建「进程死时仍在 running」的 goal 循环态（断点续跑）。

    只从最新一个 set 起重放：iter 记 last_iter；judge 按 verdict 语义重建
    last_gap / _gap_sigs / _judge_errors（gap=="judge 失败" → errors+1，
    否则入签名序列）；任一 terminal 相位（achieved/exhausted/stopped）→ None。

    返回 (state, start)：
    - last_iter 后有 judge（该轮已完成）→ start = last_iter + 1
    - last_iter 后无 judge（该轮半途）→ start = max(last_iter, 1)（整轮重跑；
      orchestrator 轮内 checkpoint 不复用，以轮为原子单位）
    无 set → None（调用方回落到既有 checkpoint/error 分支）。
    """
    state: GoalState | None = None
    last_iter = 0
    judged: dict[int, dict] = {}
    terminal = False
    for ev in events:
        etype = getattr(ev.type, "value", ev.type)
        if etype != "goal":
            continue
        payload = ev.payload or {}
        phase = payload.get("phase")
        if phase == "set":
            state = GoalState(objective=payload.get("objective", ""),
                              max_iterations=payload.get("max_iterations", 5))
            last_iter = 0
            judged = {}
            terminal = False
            continue
        if state is None:
            continue
        if phase == "iter":
            last_iter = payload.get("iteration", last_iter)
        elif phase == "judge":
            judged[payload.get("iteration", last_iter)] = payload
        elif phase in _TERMINAL_PHASES:
            terminal = True
    if state is None or terminal:
        return None
    # 重放已完成的轮（judge 事件即轮完成凭据），重建 gap 签名/失败计数。
    # 若某轮本应熔断/达成，终态事件必已落盘（同协程顺序 emit）→ 上面已 None，
    # 故此循环内 record_verdict 语义只会是 "continue"，直接重建字段即可。
    completed = 0
    for it in range(1, last_iter + 1):
        j = judged.get(it)
        if j is None:
            break  # 该轮半途（iter 已 emit、judge 未落盘）
        completed = it
        gap = str(j.get("gap") or "")
        # M191.1 · 结构化优先、哨兵兜底：新格式事件带 error 键（judge 调用/解析失败
        # 的显式标记）；旧格式无 error 键时回落 gap=="judge 失败" 哨兵串判定。
        # 修复 L-M188-4：真实 judge verdict 的 gap 撞哨兵串不再被误计为 judge 错误。
        err = j.get("error")
        if err is None:                      # 旧格式事件无 error 键（向后兼容）
            err = (not j.get("achieved")) and gap == "judge 失败"
        if err:
            state._judge_errors += 1
            state.last_gap = "judge 失败"
        else:
            state._judge_errors = 0
            state.last_gap = gap
            if not j.get("achieved"):
                state._gap_sigs.append(_gap_sig(gap))
    state.iteration = completed
    if last_iter in judged:
        start = last_iter + 1
    else:
        start = max(last_iter, 1)
    # M191.2 · 审批 parked 的 goal 不在启动/看门狗自动续跑（由审批放行钩子接手）
    if has_pending_approval(events):
        return None
    return state, start


def goal_payload(phase: str, state: GoalState, **extra) -> dict:
    """构造 goal 事件 payload。phase ∈ set|iter|judge|achieved|exhausted|stopped。"""
    payload = {
        "phase": phase,
        "objective": state.objective,
        "iteration": state.iteration,
        "max_iterations": state.max_iterations,
    }
    payload.update(extra)
    return payload


def summarize_goal_events(events: list) -> dict | None:
    """从事件流重建最新 goal 状态（供 GET 端点）。

    events 元素有 .type 和 .payload（type 可能是 enum）。
    无 goal 事件 → None；set 开新 goal；iter → running + 最新 iteration；
    achieved/exhausted/stopped → 对应终态。
    """
    objective = ""
    max_iterations = 5
    iteration = 0
    status = ""
    gap = ""
    seen = False
    for ev in events:
        etype = getattr(ev.type, "value", ev.type)
        if etype != "goal":
            continue
        payload = ev.payload or {}
        phase = payload.get("phase")
        if phase == "set":
            seen = True
            objective = payload.get("objective", "")
            max_iterations = payload.get("max_iterations", 5)
            iteration = 0
            status = "running"
            gap = ""
            continue
        if not seen:
            continue
        if phase == "iter":
            status = "running"
            iteration = payload.get("iteration", iteration)
        elif phase == "paused":
            # M191.2：审批驻留相位（非终态，不入 _TERMINAL_PHASES）
            status = "paused"
            iteration = payload.get("iteration", iteration)
        elif phase in _TERMINAL_PHASES:
            status = phase
            iteration = payload.get("iteration", iteration)
        if payload.get("gap"):
            gap = payload["gap"]
    if not seen:
        return None
    return {
        "objective": objective,
        "status": status,
        "iteration": iteration,
        "max_iterations": max_iterations,
        "gap": gap,
    }
