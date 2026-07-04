"""把 orchestrator 每步实时推到 WS 事件流(F2 · 去黑盒)。

orchestrator 默认用 NullEventBus,Supervisor/Worker/Overseer/Verify 的进展 UI 全看不到,
跑完才出结果。本模块用 (bus, session_id) 把可注入节点包一层:每步产出即 emit 对应事件
(supervisor 子任务 / worker 沙盒轨迹 / overseer verdict / verify 判定),让自主循环像
Devin/Windsurf 一样全程可见。事件形状与 mock_run 一致 → 前端已能渲染。

emit 走闭包不进 LangGraph checkpoint 状态(callable 不可序列化,放进 state 会破坏崩溃恢复)。
"""
from __future__ import annotations

from typing import Any, Callable

from api.events import EventBus
from api.schemas import EventType, Role
from driving.orchestrator import (
    SupervisorFn,
    OverseerFn,
    VerifierFn,
    default_overseer,
    default_supervisor,
    make_openhands_worker,
)

_VERIFY_OUTPUT_TAIL = 1000


def instrument_supervisor(bus: EventBus, session_id: str,
                          base: SupervisorFn = default_supervisor) -> SupervisorFn:
    """包装 supervisor:产出子任务后 emit 一条 supervisor 消息。"""

    def supervisor(state: dict) -> dict:
        upd = base(state)
        subtask = upd.get("current_subtask", "")
        believe_done = bool(upd.get("believe_done"))
        text = "相信目标已达成,进入强制验证。" if believe_done else f"拆解子任务:{subtask}"
        bus.emit(session_id, EventType.message, Role.supervisor,
                 {"text": text, "subtask": subtask, "believe_done": believe_done})
        return upd

    return supervisor


def instrument_overseer(bus: EventBus, session_id: str,
                        base: OverseerFn = default_overseer) -> OverseerFn:
    """包装 overseer:产出 verdict 后 emit 一条 overseer 消息。"""

    def overseer(state: dict) -> dict:
        upd = base(state)
        verdict = upd.get("verdict", {}) or {}
        bus.emit(session_id, EventType.message, Role.overseer,
                 {"verdict": verdict, "text": verdict.get("rationale", "")})
        return upd

    return overseer


def instrument_verifier(bus: EventBus, session_id: str, base: VerifierFn) -> VerifierFn:
    """包装 verifier:验收判定后 emit 一条 verify 消息(命令 + 通过与否 + 尾部输出)。"""

    def verifier(cmd: list, cwd: str) -> "tuple[bool, str]":
        ok, output = base(cmd, cwd)
        bus.emit(session_id, EventType.message, Role.verify,
                 {"ok": ok, "text": "强制验收通过 ✓" if ok else "强制验收未过 ✗",
                  "command": " ".join(cmd), "output": (output or "")[-_VERIFY_OUTPUT_TAIL:]})
        return ok, output

    return verifier


def build_streaming_nodes(bus: EventBus, session_id: str,
                          base_verifier: VerifierFn) -> dict[str, Callable[..., Any]]:
    """返回接了真实事件流的 supervisor/worker/overseer/verifier,供 drive_orchestrated 注入。"""
    return {
        "supervisor": instrument_supervisor(bus, session_id),
        "worker": make_openhands_worker(bus, session_id),
        "overseer": instrument_overseer(bus, session_id),
        "verifier": instrument_verifier(bus, session_id, base_verifier),
    }
