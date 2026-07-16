"""M125 · git worktree 隔离层。

借鉴 Orca 的 worktree-native 设计：
- 每个子任务自动创建 git worktree
- Agent 间通过文件系统天然隔离
- 每个 worktree 可独立验证、独立回滚
- 支持合并回主分支

集成到 factory_loop 后，子任务派发到独立 worktree 并行执行。
"""
from __future__ import annotations

import os
import shutil
import subprocess
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from driving.structured_logger import StructuredLogger, LogLevel


class WorktreeStatus(str, Enum):
    """worktree 生命周期状态。"""
    active = "active"
    archived = "archived"
    failed = "failed"


@dataclass
class WorktreeEntry:
    """单个 worktree 记录。"""
    worktree_id: str
    task_id: str
    path: str
    branch: str
    status: WorktreeStatus
    created_at: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "worktree_id": self.worktree_id,
            "task_id": self.task_id,
            "path": self.path,
            "branch": self.branch,
            "status": self.status.value,
            "created_at": self.created_at,
            "metadata": self.metadata,
        }


class WorktreeManager:
    """git worktree 管理器。

    Args:
        repo_path: 主仓库路径（必须有 git 仓库）。
        worktree_root: worktree 存放根目录。
    """

    def __init__(
        self,
        *,
        repo_path: str = ".",
        worktree_root: str = "/tmp/flipped-worktrees",
        logger: StructuredLogger | None = None,
    ) -> None:
        self.repo_path = os.path.abspath(repo_path)
        self.worktree_root = os.path.abspath(worktree_root)
        self.logger = logger or StructuredLogger(
            module_name="worktree_manager",
            min_level=LogLevel.info,
        )
        self._entries: dict[str, WorktreeEntry] = {}
        self._task_index: dict[str, str] = {}  # task_id -> worktree_id

        os.makedirs(self.worktree_root, exist_ok=True)

    def _git(self, args: list[str], cwd: str | None = None) -> subprocess.CompletedProcess:
        """执行 git 命令。"""
        return subprocess.run(
            ["git"] + args,
            cwd=cwd or self.repo_path,
            capture_output=True,
            text=True,
        )

    def create(
        self,
        task_id: str,
        *,
        branch_name: str | None = None,
        base_branch: str | None = None,
    ) -> WorktreeEntry:
        """为任务创建 git worktree。

        Args:
            task_id: 任务标识。
            branch_name: 自定义分支名，默认自动生成。
            base_branch: 基于哪个分支创建，默认当前分支。
        """
        worktree_id = f"wt-{uuid.uuid4().hex[:8]}"
        wt_path = os.path.join(self.worktree_root, worktree_id)

        if branch_name is None:
            branch_name = f"wt/{task_id}/{worktree_id}"

        # 确定基础分支
        if base_branch is None:
            result = self._git(["rev-parse", "--abbrev-ref", "HEAD"])
            base_branch = result.stdout.strip() if result.returncode == 0 else "HEAD"

        # 创建分支 + worktree
        result = self._git([
            "worktree", "add", "-b", branch_name, wt_path, base_branch,
        ])

        if result.returncode != 0:
            self.logger.error("worktree_create_failed", {
                "task_id": task_id,
                "error": result.stderr.strip(),
            })
            entry = WorktreeEntry(
                worktree_id=worktree_id,
                task_id=task_id,
                path=wt_path,
                branch=branch_name,
                status=WorktreeStatus.failed,
                created_at=datetime.now(timezone.utc).isoformat(),
                metadata={"error": result.stderr.strip()},
            )
            self._entries[worktree_id] = entry
            self._task_index[task_id] = worktree_id
            raise RuntimeError(f"git worktree add failed: {result.stderr.strip()}")

        entry = WorktreeEntry(
            worktree_id=worktree_id,
            task_id=task_id,
            path=wt_path,
            branch=branch_name,
            status=WorktreeStatus.active,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        self._entries[worktree_id] = entry
        self._task_index[task_id] = worktree_id

        self.logger.info("worktree_created", {
            "worktree_id": worktree_id,
            "task_id": task_id,
            "path": wt_path,
            "branch": branch_name,
        })

        return entry

    def get(self, worktree_id: str) -> WorktreeEntry | None:
        """按 worktree_id 获取。"""
        return self._entries.get(worktree_id)

    def get_by_task(self, task_id: str) -> WorktreeEntry | None:
        """按 task_id 获取。"""
        wt_id = self._task_index.get(task_id)
        if wt_id is None:
            return None
        return self._entries.get(wt_id)

    def list_all(self, *, status: WorktreeStatus | None = None) -> list[WorktreeEntry]:
        """列出所有 worktree。"""
        if status is not None:
            return [e for e in self._entries.values() if e.status == status]
        return list(self._entries.values())

    def remove(self, worktree_id: str) -> bool:
        """移除 worktree（删除目录 + 分支）。"""
        entry = self._entries.get(worktree_id)
        if entry is None:
            return False

        # git worktree remove
        if os.path.exists(entry.path):
            self._git(["worktree", "remove", "--force", entry.path])
            # 确保目录被删除
            if os.path.exists(entry.path):
                shutil.rmtree(entry.path, ignore_errors=True)

        # 删除分支
        self._git(["branch", "-D", entry.branch])

        del self._entries[worktree_id]
        # 清理 task 索引
        task_id = entry.task_id
        if self._task_index.get(task_id) == worktree_id:
            del self._task_index[task_id]

        self.logger.info("worktree_removed", {
            "worktree_id": worktree_id,
            "task_id": task_id,
        })

        return True

    def remove_by_task(self, task_id: str) -> bool:
        """按 task_id 移除 worktree。"""
        entry = self.get_by_task(task_id)
        if entry is None:
            return False
        return self.remove(entry.worktree_id)

    def archive(self, worktree_id: str) -> bool:
        """归档 worktree（标记为 archived，不删除目录）。"""
        entry = self._entries.get(worktree_id)
        if entry is None:
            return False
        entry.status = WorktreeStatus.archived
        self.logger.info("worktree_archived", {"worktree_id": worktree_id})
        return True

    def cleanup_all(self) -> int:
        """清理所有 active worktree。"""
        count = 0
        for entry in list(self._entries.values()):
            if entry.status == WorktreeStatus.active:
                if self.remove(entry.worktree_id):
                    count += 1
        return count

    def merge_to_main(self, worktree_id: str) -> bool:
        """将 worktree 分支合并回主分支。

        Args:
            worktree_id: 要合并的 worktree。
        """
        entry = self._entries.get(worktree_id)
        if entry is None:
            return False

        # 先在 worktree 中提交所有改动
        self._git(["add", "-A"], cwd=entry.path)
        commit_result = self._git(["diff", "--cached", "--quiet"], cwd=entry.path)
        if commit_result.returncode != 0:
            self._git(["commit", "-m", f"merge from {entry.task_id}"], cwd=entry.path)

        # 在主仓库 merge
        result = self._git(["merge", entry.branch, "--no-edit"])
        if result.returncode != 0:
            self.logger.error("merge_failed", {
                "worktree_id": worktree_id,
                "branch": entry.branch,
                "error": result.stderr.strip(),
            })
            # 中止合并
            self._git(["merge", "--abort"])
            return False

        self.logger.info("worktree_merged", {
            "worktree_id": worktree_id,
            "branch": entry.branch,
        })

        return True

    def stats(self) -> dict[str, Any]:
        """获取统计信息。"""
        entries = list(self._entries.values())
        return {
            "total": len(entries),
            "active": sum(1 for e in entries if e.status == WorktreeStatus.active),
            "archived": sum(1 for e in entries if e.status == WorktreeStatus.archived),
            "failed": sum(1 for e in entries if e.status == WorktreeStatus.failed),
        }
