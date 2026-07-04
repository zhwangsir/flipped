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


class PlanTracker:
    """把 orchestrator 的子任务累积成有序计划清单并实时 emit(F4 · 可见脊柱)。

    每个 supervisor 子任务 = 一个步骤(status=running);overseer replan→retry / abort→aborted;
    下一个子任务开始时关闭上一步(仍 running 记 done);verify 通过→末步 done + 全局 complete。
    状态变更都产生新 dict(不就地改),清单本身是一次运行的累积器。
    """

    def __init__(self, bus: EventBus, session_id: str):
        self.bus = bus
        self.session_id = session_id
        self.steps: list[dict[str, Any]] = []
        self.complete = False

    def _emit(self) -> None:
        self.bus.emit(self.session_id, EventType.plan, Role.supervisor,
                      {"steps": [dict(s) for s in self.steps], "complete": self.complete})

    def _close_running(self, status: str = "done") -> None:
        if self.steps and self.steps[-1]["status"] == "running":
            self.steps[-1] = {**self.steps[-1], "status": status}

    def add(self, text: str) -> None:
        """开始一个新步骤(先关闭上一 running 步为 done)。"""
        self._close_running("done")
        self.steps.append({"index": len(self.steps) + 1, "text": text, "status": "running"})
        self._emit()

    def mark_last(self, status: str) -> None:
        """标注当前 running 步的非常规结局(retry/aborted)。"""
        if self.steps and self.steps[-1]["status"] == "running":
            self.steps[-1] = {**self.steps[-1], "status": status}
            self._emit()

    def finish(self, ok: bool) -> None:
        """验收判定:通过→末步 done + 全局 complete;未过不改末步(下个子任务会关闭它)。"""
        if ok:
            self._close_running("done")
            self.complete = True
            self._emit()


def instrument_supervisor(bus: EventBus, session_id: str,
                          base: SupervisorFn = default_supervisor,
                          tracker: PlanTracker | None = None) -> SupervisorFn:
    """包装 supervisor:产出子任务 → 计划清单加一步 + emit supervisor 消息。"""

    def supervisor(state: dict) -> dict:
        upd = base(state)
        subtask = upd.get("current_subtask", "")
        believe_done = bool(upd.get("believe_done"))
        if tracker is not None and not believe_done and subtask:
            tracker.add(subtask)
        text = "相信目标已达成,进入强制验证。" if believe_done else f"拆解子任务:{subtask}"
        bus.emit(session_id, EventType.message, Role.supervisor,
                 {"text": text, "subtask": subtask, "believe_done": believe_done})
        return upd

    return supervisor


def instrument_overseer(bus: EventBus, session_id: str,
                        base: OverseerFn = default_overseer,
                        tracker: PlanTracker | None = None) -> OverseerFn:
    """包装 overseer:verdict → 标注当前步(replan=retry/abort=aborted) + emit overseer 消息。"""

    def overseer(state: dict) -> dict:
        upd = base(state)
        verdict = upd.get("verdict", {}) or {}
        if tracker is not None:
            action = verdict.get("action")
            if action == "replan":
                tracker.mark_last("retry")
            elif action == "abort":
                tracker.mark_last("aborted")
        bus.emit(session_id, EventType.message, Role.overseer,
                 {"verdict": verdict, "text": verdict.get("rationale", "")})
        return upd

    return overseer


def instrument_verifier(bus: EventBus, session_id: str, base: VerifierFn,
                        tracker: PlanTracker | None = None) -> VerifierFn:
    """包装 verifier:验收判定 → 收尾计划清单 + emit verify 消息(命令+通过否+尾部输出)。"""

    def verifier(cmd: list, cwd: str) -> "tuple[bool, str]":
        ok, output = base(cmd, cwd)
        if tracker is not None:
            tracker.finish(ok)
        bus.emit(session_id, EventType.message, Role.verify,
                 {"ok": ok, "text": "强制验收通过 ✓" if ok else "强制验收未过 ✗",
                  "command": " ".join(cmd), "output": (output or "")[-_VERIFY_OUTPUT_TAIL:]})
        return ok, output

    return verifier


def build_streaming_nodes(bus: EventBus, session_id: str,
                          base_verifier: VerifierFn) -> dict[str, Callable[..., Any]]:
    """返回接了真实事件流 + 共享计划清单的 supervisor/worker/overseer/verifier。"""
    tracker = PlanTracker(bus, session_id)
    return {
        "supervisor": instrument_supervisor(bus, session_id, tracker=tracker),
        "worker": make_openhands_worker(bus, session_id),
        "overseer": instrument_overseer(bus, session_id, tracker=tracker),
        "verifier": instrument_verifier(bus, session_id, base_verifier, tracker=tracker),
    }
