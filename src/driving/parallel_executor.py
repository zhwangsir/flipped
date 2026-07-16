"""M125-M126 · 并行执行器 + Fan-out 对比模式。

借鉴 Orca 的 Fan-out 设计：
- 同一任务分发到 N 个独立 git worktree 并行执行
- 每个 worktree 中的 Agent 互不干扰
- 执行完成后质量对比，merge 胜出方案

两种模式：
1. fan_out: 同 prompt → N 个 worktree → 对比 → merge 最优
2. parallel_subtasks: 不同子任务 → 各自 worktree → 并行执行 → 合并
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

from driving.worktree_manager import WorktreeManager, WorktreeEntry, WorktreeStatus
from driving.quality_comparison import (
    compare_outputs,
    ComparisonResult,
    ComparisonConfig,
    calculate_gap,
)
from driving.structured_logger import StructuredLogger, LogLevel


@dataclass
class AgentRun:
    """单个 Agent 在一个 worktree 中的执行记录。"""
    agent_id: str
    worktree_id: str
    worktree_path: str
    output: dict[str, Any] = field(default_factory=dict)
    duration_ms: float = 0.0
    success: bool = False
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "worktree_id": self.worktree_id,
            "worktree_path": self.worktree_path,
            "output": self.output,
            "duration_ms": self.duration_ms,
            "success": self.success,
            "error": self.error,
        }


@dataclass
class FanOutResult:
    """Fan-out 执行结果。"""
    task_id: str
    runs: list[AgentRun] = field(default_factory=list)
    comparison: ComparisonResult | None = None
    winner: AgentRun | None = None
    merged: bool = False
    total_duration_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "runs": [r.to_dict() for r in self.runs],
            "comparison": self.comparison.to_dict() if self.comparison else None,
            "winner": self.winner.agent_id if self.winner else None,
            "merged": self.merged,
            "total_duration_ms": self.total_duration_ms,
        }


class ParallelExecutor:
    """并行执行器。

    Args:
        repo_path: 主仓库路径。
        worktree_root: worktree 存放目录。
        execute_fn: 任务执行函数 (task, worktree_path) -> dict[str, Any]。
    """

    def __init__(
        self,
        *,
        repo_path: str = ".",
        worktree_root: str = "/tmp/flipped-worktrees",
        execute_fn: Callable[[Any, str], dict[str, Any]] | None = None,
        comparison_config: ComparisonConfig | None = None,
        logger: StructuredLogger | None = None,
    ) -> None:
        self.wt_mgr = WorktreeManager(
            repo_path=repo_path,
            worktree_root=worktree_root,
            logger=logger,
        )
        self.execute_fn = execute_fn or self._default_execute
        self.comparison_config = comparison_config or ComparisonConfig()
        self.logger = logger or StructuredLogger(
            module_name="parallel_executor",
            min_level=LogLevel.info,
        )

    def _default_execute(self, task: Any, worktree_path: str) -> dict[str, Any]:
        """默认执行函数（模拟）。"""
        return {"correctness": 75, "design": 70, "code_quality": 72}

    def fan_out(
        self,
        task: Any,
        *,
        agent_count: int = 3,
        merge_winner: bool = True,
    ) -> FanOutResult:
        """Fan-out 模式：同一任务分发到 N 个 worktree 并行执行。

        Args:
            task: 任务对象（需有 id 和 description 属性）。
            agent_count: 并行 Agent 数量。
            merge_winner: 是否将胜出方案的 worktree 合并回主分支。
        """
        task_id = getattr(task, "id", "unknown")
        start = time.time()

        self.logger.info("fan_out_start", {
            "task_id": task_id,
            "agent_count": agent_count,
        })

        # 1. 为每个 Agent 创建 worktree
        runs: list[AgentRun] = []
        for i in range(agent_count):
            agent_id = f"agent-{i+1}"
            try:
                wt = self.wt_mgr.create(f"{task_id}-{agent_id}")
                runs.append(AgentRun(
                    agent_id=agent_id,
                    worktree_id=wt.worktree_id,
                    worktree_path=wt.path,
                ))
            except Exception as exc:
                self.logger.error("worktree_create_failed", {
                    "agent_id": agent_id,
                    "error": str(exc),
                })
                runs.append(AgentRun(
                    agent_id=agent_id,
                    worktree_id="",
                    worktree_path="",
                    error=str(exc),
                ))

        # 2. 并行执行（当前串行模拟，真实环境可替换为多进程）
        for run in runs:
            if not run.worktree_path:
                continue
            exec_start = time.time()
            try:
                output = self.execute_fn(task, run.worktree_path)
                run.output = output
                run.success = True
            except Exception as exc:
                run.error = str(exc)
                run.success = False
            run.duration_ms = round((time.time() - exec_start) * 1000, 2)

        # 3. 质量对比
        successful_runs = [r for r in runs if r.success and r.output]
        comparison = None
        winner = None

        if len(successful_runs) >= 2:
            # 两两对比，选总分最高的
            best_score = -1.0
            for i, run in enumerate(successful_runs):
                # 与其他所有 run 对比，计算平均分
                total_score = 0.0
                for j, other in enumerate(successful_runs):
                    if i == j:
                        continue
                    dims = list(set(run.output.keys()) & set(other.output.keys()))
                    if dims:
                        comp = compare_outputs(
                            run.output, other.output, dims,
                            config=self.comparison_config,
                        )
                        total_score += comp.flipped_score
                avg_score = total_score / max(1, len(successful_runs) - 1)
                if avg_score > best_score:
                    best_score = avg_score
                    winner = run

            # 生成最终对比结果（winner vs 其他的平均）
            if winner:
                other_avg = {}
                for r in successful_runs:
                    if r is winner:
                        continue
                    for k, v in r.output.items():
                        other_avg.setdefault(k, []).append(v)
                other_avg = {k: sum(v) / len(v) for k, v in other_avg.items()}
                dims = list(set(winner.output.keys()) & set(other_avg.keys()))
                if dims:
                    comparison = compare_outputs(
                        winner.output, other_avg, dims,
                        config=self.comparison_config,
                    )

        elif len(successful_runs) == 1:
            winner = successful_runs[0]

        # 4. 合并胜出方案
        merged = False
        if winner and merge_winner and winner.worktree_id:
            try:
                merged = self.wt_mgr.merge_to_main(winner.worktree_id)
            except Exception as exc:
                self.logger.error("merge_failed", {
                    "worktree_id": winner.worktree_id,
                    "error": str(exc),
                })

        # 5. 清理非胜出的 worktree
        for run in runs:
            if run.worktree_id and (winner is None or run.agent_id != winner.agent_id):
                try:
                    self.wt_mgr.remove(run.worktree_id)
                except Exception:
                    pass

        total_ms = round((time.time() - start) * 1000, 2)

        result = FanOutResult(
            task_id=task_id,
            runs=runs,
            comparison=comparison,
            winner=winner,
            merged=merged,
            total_duration_ms=total_ms,
        )

        self.logger.info("fan_out_complete", {
            "task_id": task_id,
            "runs": len(runs),
            "successful": len(successful_runs),
            "winner": winner.agent_id if winner else None,
            "merged": merged,
            "duration_ms": total_ms,
        })

        return result

    def parallel_subtasks(
        self,
        subtasks: list[Any],
        *,
        merge_all: bool = True,
    ) -> list[FanOutResult]:
        """并行子任务模式：不同子任务各自 worktree 并行执行。

        Args:
            subtasks: 子任务列表。
            merge_all: 是否将所有 worktree 合并回主分支。
        """
        results: list[FanOutResult] = []

        for st in subtasks:
            result = self.fan_out(st, agent_count=1, merge_winner=False)
            results.append(result)

        if merge_all:
            for r in results:
                if r.winner and r.winner.worktree_id:
                    try:
                        self.wt_mgr.merge_to_main(r.winner.worktree_id)
                        r.merged = True
                    except Exception:
                        pass

        return results

    def cleanup(self) -> int:
        """清理所有 worktree。"""
        return self.wt_mgr.cleanup_all()

    def stats(self) -> dict[str, Any]:
        """获取统计。"""
        return self.wt_mgr.stats()
