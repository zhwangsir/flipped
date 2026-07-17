"""卡死检测 + delegate 子 Agent（M10.4-C）。

当 worker 在同一任务上反复失败时，触发 delegate：
- 把卡住的任务交给一个临时子 Agent
- 子 Agent 在干净的独立 thread_id + 独立 checkpoint 上跑
- 主 Agent 只接收结构化结果（不污染主上下文）

卡死信号：
1. 同一任务失败 ≥ stuck_threshold 次（默认 2）
2. 反复用同一动作签名（如反复改同一文件）
3. verify_cmd 反复因同一原因失败
4. 迭代预算耗尽（max_iterations 达到）

集成点：
- factory_loop 的 default_orchestrator_fn：第 N 次失败后改用 delegate orchestrator
- infinite_loop 的 _evolve_goal：把 delegate 失败记录作为下一轮输入
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any

from driving.factory_loop import FactoryTask, FactoryState, TaskResult
from driving.orchestrator import drive_orchestrated
from driving.db import default_db_path


@dataclass
class StuckSignal:
    """一次卡死检测的判定结果。"""
    is_stuck: bool
    reason: str = ""
    delegate_recommended: bool = False
    iterations_seen: int = 0


@dataclass
class StuckDetector:
    """跟踪一个 task 的迭代历史，判断是否卡死。

    用法：
        det = StuckDetector()
        for attempt in range(max_attempts):
            result = run_task(...)
            det.record(result.stop_reason, result.summary)
            if det.is_stuck():
                # 触发 delegate：用独立 thread_id 的子 Agent 重试
                break
    """
    fail_threshold: int = 2  # 同一 stop_reason 连续失败 N 次即卡死
    signature_threshold: int = 3  # 同一动作签名重复 N 次即卡死
    window: int = 5  # 跟踪窗口大小

    _stop_reasons: list[str] = field(default_factory=list)
    _summaries: list[str] = field(default_factory=list)

    def record(self, stop_reason: str, summary: str = "") -> None:
        self._stop_reasons.append(stop_reason or "")
        self._summaries.append((summary or "")[:200])
        # 限制窗口
        if len(self._stop_reasons) > self.window:
            self._stop_reasons = self._stop_reasons[-self.window:]
            self._summaries = self._summaries[-self.window:]

    def is_stuck(self) -> StuckSignal:
        """判定是否卡死 + 是否推荐 delegate。"""
        n = len(self._stop_reasons)
        if n == 0:
            return StuckSignal(is_stuck=False)

        # 信号 1：所有尝试都失败（无 verified）
        all_failed = all(r and r != "verified" for r in self._stop_reasons)
        if not all_failed:
            return StuckSignal(is_stuck=False, iterations_seen=n)

        # 信号 2：连续 ≥ fail_threshold 次同一 stop_reason
        if n >= self.fail_threshold:
            last_reasons = self._stop_reasons[-self.fail_threshold:]
            if len(set(last_reasons)) == 1:
                return StuckSignal(
                    is_stuck=True,
                    reason=f"连续 {self.fail_threshold} 次同一 stop_reason={last_reasons[0]}",
                    delegate_recommended=True,
                    iterations_seen=n,
                )

        # 信号 3：失败摘要高度相似（hash 相同）
        if n >= 2:
            hashes = [hashlib.md5(s.encode()).hexdigest()[:8] for s in self._summaries[-3:]]
            if len(set(hashes)) == 1 and len(hashes) >= 2:
                return StuckSignal(
                    is_stuck=True,
                    reason=f"连续 {len(hashes)} 次失败摘要相同（worker 在原地打转）",
                    delegate_recommended=True,
                    iterations_seen=n,
                )

        # 信号 4：失败摘要相似度极高（用简单 Jaccard）
        if n >= 2:
            a = set(self._summaries[-1].split())
            b = set(self._summaries[-2].split())
            if a and b:
                j = len(a & b) / max(1, len(a | b))
                if j >= 0.85 and n >= 2:
                    return StuckSignal(
                        is_stuck=True,
                        reason=f"连续失败摘要相似度 {j:.0%}（worker 反复犯同类错）",
                        delegate_recommended=True,
                        iterations_seen=n,
                    )

        return StuckSignal(is_stuck=False, iterations_seen=n)

    def reset(self) -> None:
        self._stop_reasons.clear()
        self._summaries.clear()


def delegate_orchestrator(
    task: FactoryTask,
    state: FactoryState,
    stuck_reason: str,
) -> TaskResult:
    """delegate：把卡住的任务交给临时子 Agent 在干净上下文里重试。

    实现：用一个全新的 thread_id（与主 Agent 隔离），把卡死原因作为 feedback 注入，
    让子 Agent 从零开始理解问题（而不是继承主 Agent 已被污染的上下文）。

    每次失败原因 → 给 supervisor 明确指示："前 N 次失败模式是 X，请用不同方法"。
    """
    import uuid

    # 独立 thread_id，让子 Agent 有干净上下文（不复用主 Agent 的 checkpoint）
    # M137：checkpoint 库已收敛为统一库，delegate 隔离由 "delegate-*" thread_id
    # 命名空间承担（共享 checkpoints/writes 表，按 thread_id 过滤）。
    delegate_thread = f"delegate-{state.factory_id}-{task.id}-{uuid.uuid4().hex[:6]}"

    # 把所有失败原因拼接成 feedback
    feedback = (
        f"⚠️ Delegate 警告：本任务已在前序 Agent 中失败 {task.attempts} 次。\n"
        f"卡死原因：{stuck_reason}\n"
        f"历史反馈：{task.feedback}\n\n"
        "请你（delegate sub-agent）用**与之前不同的方法**解决这个任务：\n"
        "1. 不要重复之前导致失败的做法\n"
        "2. 优先尝试最小化的精确修复，不要推倒重来\n"
        "3. 如果之前的失败是 verify_cmd 不通过，先看 verify_cmd 在测什么，再针对性修复"
    )

    result = drive_orchestrated(
        goal=task.description,
        cwd=state.cwd,
        verify_cmd=task.verify_cmd or ["true"],
        project_rules=(
            f"【Delegate 子任务】你是被主 Agent 委派的子 Agent，在干净上下文里处理一个卡住的任务。\n"
            f"工作目录：{state.cwd}\n"
            f"{state.design_context}\n\n"
            f"{feedback}"
        ),
        max_iterations=4,
        db_path=default_db_path(),  # M137：统一库；隔离靠上面的 delegate-* thread_id
        thread_id=delegate_thread,
    )
    return TaskResult(
        task=task,
        verified=bool(result.get("verified")),
        stop_reason=result.get("stop_reason", ""),
        iteration=result.get("iteration", 0),
        summary=f"[delegate] {_summarize_result(result)} | reason={stuck_reason}",
    )


def _summarize_result(values: dict) -> str:
    parts = [f"stop_reason={values.get('stop_reason', '')}"]
    if values.get("verified"):
        parts.append("verified=True")
    if values.get("feedback"):
        parts.append(f"feedback={values['feedback'][:150]}")
    return "; ".join(parts)
