"""M129 · Agent CLI 工具暴露。

借鉴 Orca CLI 设计：让 Agent 自身也能驱动 worktree 管理、截图、状态查询。

命令清单：
    worktree create <task_id>     — 为任务创建 worktree
    worktree list                 — 列出所有 worktree
    worktree remove <worktree_id> — 移除 worktree
    worktree merge <worktree_id>  — 合并 worktree 到主分支
    worktree stats                — worktree 统计
    snapshot <url> [--name NAME]  — 截取页面截图
    status list                   — 列出所有 Agent 状态
    status update <agent> <state> — 更新 Agent 状态
    fan_out <task_id> [--agents N]— Fan-out 并行执行
    help                          — 显示帮助

设计：每个命令返回 JSON，可直接被 Agent 解析使用。
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from typing import Any

from driving.worktree_manager import WorktreeManager, WorktreeStatus
from driving.agent_status_hook import StatusHook, AgentStatus
from driving.visual_feedback import VisualFeedbackLoop
from driving.parallel_executor import ParallelExecutor
from driving.structured_logger import StructuredLogger, LogLevel


@dataclass
class CLIResult:
    """命令执行结果。"""
    success: bool
    output: dict[str, Any]
    message: str = ""

    def to_json(self) -> str:
        return json.dumps({
            "success": self.success,
            "message": self.message,
            "output": self.output,
        }, ensure_ascii=False, indent=2)


class AgentCLI:
    """Agent 自驱动 CLI。

    Agent 可通过代码调用或命令行调用这些方法。
    所有方法返回 CLIResult，包含 JSON 可序列化的输出。
    """

    def __init__(
        self,
        *,
        repo_path: str = ".",
        worktree_root: str = "/tmp/flipped-worktrees",
        screenshot_dir: str = "/tmp/flipped-screenshots",
    ) -> None:
        self.wt_mgr = WorktreeManager(
            repo_path=repo_path,
            worktree_root=worktree_root,
        )
        self.status_hook = StatusHook()
        self.visual = VisualFeedbackLoop(screenshot_dir=screenshot_dir)
        self.repo_path = repo_path

    # ── worktree 命令 ──

    def worktree_create(self, task_id: str, *, branch: str | None = None) -> CLIResult:
        """为任务创建 worktree。"""
        try:
            wt = self.wt_mgr.create(task_id, branch_name=branch)
            return CLIResult(
                success=True,
                output=wt.to_dict(),
                message=f"Worktree created: {wt.worktree_id}",
            )
        except Exception as exc:
            return CLIResult(
                success=False,
                output={},
                message=f"Failed to create worktree: {exc}",
            )

    def worktree_list(self) -> CLIResult:
        """列出所有 worktree。"""
        entries = self.wt_mgr.list_all()
        return CLIResult(
            success=True,
            output={
                "worktrees": [e.to_dict() for e in entries],
                "count": len(entries),
            },
            message=f"{len(entries)} worktrees",
        )

    def worktree_remove(self, worktree_id: str) -> CLIResult:
        """移除 worktree。"""
        removed = self.wt_mgr.remove(worktree_id)
        return CLIResult(
            success=removed,
            output={"worktree_id": worktree_id},
            message=f"Removed: {worktree_id}" if removed else f"Not found: {worktree_id}",
        )

    def worktree_merge(self, worktree_id: str) -> CLIResult:
        """合并 worktree 到主分支。"""
        merged = self.wt_mgr.merge_to_main(worktree_id)
        return CLIResult(
            success=merged,
            output={"worktree_id": worktree_id},
            message=f"Merged: {worktree_id}" if merged else f"Merge failed: {worktree_id}",
        )

    def worktree_stats(self) -> CLIResult:
        """worktree 统计。"""
        return CLIResult(
            success=True,
            output=self.wt_mgr.stats(),
            message="Worktree stats",
        )

    # ── snapshot 命令 ──

    def snapshot(self, url: str, *, name: str = "") -> CLIResult:
        """截取页面截图。"""
        result = self.visual.capture(url, name=name)
        return CLIResult(
            success=result.success,
            output=result.to_dict(),
            message=f"Screenshot saved: {result.path}" if result.success else f"Failed: {result.error}",
        )

    # ── status 命令 ──

    def status_list(self) -> CLIResult:
        """列出所有 Agent 状态。"""
        stats = self.status_hook.stats()
        return CLIResult(
            success=True,
            output=stats,
            message=f"{stats['total']} agents tracked",
        )

    def status_update(self, agent_id: str, status: str) -> CLIResult:
        """更新 Agent 状态。"""
        try:
            new_status = AgentStatus(status)
        except ValueError:
            valid = [s.value for s in AgentStatus]
            return CLIResult(
                success=False,
                output={},
                message=f"Invalid status '{status}'. Valid: {valid}",
            )

        old_state = self.status_hook.get_state(agent_id)
        if old_state is None:
            self.status_hook.register(agent_id)

        self.status_hook.update(agent_id, new_status)
        return CLIResult(
            success=True,
            output={"agent_id": agent_id, "new_status": status},
            message=f"Agent {agent_id} → {status}",
        )

    # ── fan_out 命令 ──

    def fan_out(self, task_id: str, *, agents: int = 3) -> CLIResult:
        """Fan-out 并行执行。"""
        try:
            executor = ParallelExecutor(repo_path=self.repo_path)

            class MockTask:
                id = task_id
                description = task_id

            result = executor.fan_out(MockTask(), agent_count=agents, merge_winner=False)
            return CLIResult(
                success=True,
                output=result.to_dict(),
                message=f"Fan-out complete: {len(result.runs)} runs, winner: {result.winner.agent_id if result.winner else 'none'}",
            )
        except Exception as exc:
            return CLIResult(
                success=False,
                output={},
                message=f"Fan-out failed: {exc}",
            )

    # ── help ──

    def help(self) -> CLIResult:
        """显示帮助。"""
        commands = {
            "worktree_create": "worktree create <task_id> [--branch NAME]",
            "worktree_list": "worktree list",
            "worktree_remove": "worktree remove <worktree_id>",
            "worktree_merge": "worktree merge <worktree_id>",
            "worktree_stats": "worktree stats",
            "snapshot": "snapshot <url> [--name NAME]",
            "status_list": "status list",
            "status_update": "status update <agent_id> <status>",
            "fan_out": "fan_out <task_id> [--agents N]",
            "help": "help",
        }
        return CLIResult(
            success=True,
            output={"commands": commands},
            message="Available commands",
        )

    # ── 命令分发 ──

    def execute(self, args: list[str]) -> CLIResult:
        """执行命令行参数。

        Args:
            args: 命令行参数列表，如 ["worktree", "list"]。
        """
        if not args:
            return self.help()

        cmd = args[0]
        rest = args[1:]

        if cmd == "worktree":
            if not rest:
                return self.worktree_stats()
            sub = rest[0]
            if sub == "create" and len(rest) >= 2:
                branch = None
                if "--branch" in rest:
                    idx = rest.index("--branch")
                    if idx + 1 < len(rest):
                        branch = rest[idx + 1]
                return self.worktree_create(rest[1], branch=branch)
            elif sub == "list":
                return self.worktree_list()
            elif sub == "remove" and len(rest) >= 2:
                return self.worktree_remove(rest[1])
            elif sub == "merge" and len(rest) >= 2:
                return self.worktree_merge(rest[1])
            elif sub == "stats":
                return self.worktree_stats()
            return CLIResult(False, {}, f"Unknown worktree subcommand: {sub}")

        elif cmd == "snapshot":
            if not rest:
                return CLIResult(False, {}, "Usage: snapshot <url> [--name NAME]")
            url = rest[0]
            name = ""
            if "--name" in rest:
                idx = rest.index("--name")
                if idx + 1 < len(rest):
                    name = rest[idx + 1]
            return self.snapshot(url, name=name)

        elif cmd == "status":
            if not rest:
                return self.status_list()
            sub = rest[0]
            if sub == "list":
                return self.status_list()
            elif sub == "update" and len(rest) >= 3:
                return self.status_update(rest[1], rest[2])
            return CLIResult(False, {}, f"Unknown status subcommand: {sub}")

        elif cmd == "fan_out":
            if not rest:
                return CLIResult(False, {}, "Usage: fan_out <task_id> [--agents N]")
            task_id = rest[0]
            agents = 3
            if "--agents" in rest:
                idx = rest.index("--agents")
                if idx + 1 < len(rest):
                    agents = int(rest[idx + 1])
            return self.fan_out(task_id, agents=agents)

        elif cmd == "help":
            return self.help()

        return CLIResult(False, {}, f"Unknown command: {cmd}")
