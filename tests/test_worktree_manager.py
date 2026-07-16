"""M125 · git worktree 隔离层测试。"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile

from driving.worktree_manager import (
    WorktreeManager,
    WorktreeEntry,
    WorktreeStatus,
)


def _make_repo() -> tuple[str, str]:
    """创建临时 git 仓库，返回 (repo_path, worktree_root)。"""
    repo_dir = tempfile.mkdtemp(prefix="repo_")
    wt_root = tempfile.mkdtemp(prefix="wtroot_")
    subprocess.run(["git", "init", repo_dir], capture_output=True)
    subprocess.run(
        ["git", "-C", repo_dir, "config", "user.email", "test@test.com"],
        capture_output=True,
    )
    subprocess.run(
        ["git", "-C", repo_dir, "config", "user.name", "Test"],
        capture_output=True,
    )
    # 创建初始 commit
    test_file = os.path.join(repo_dir, "README.md")
    with open(test_file, "w") as f:
        f.write("# Test Repo\n")
    subprocess.run(["git", "-C", repo_dir, "add", "."], capture_output=True)
    subprocess.run(
        ["git", "-C", repo_dir, "commit", "-m", "initial"],
        capture_output=True,
    )
    return repo_dir, wt_root


def _cleanup(*paths: str) -> None:
    for p in paths:
        if os.path.exists(p):
            shutil.rmtree(p, ignore_errors=True)


class TestWorktreeStatus:
    def test_values(self):
        assert WorktreeStatus.active.value == "active"
        assert WorktreeStatus.archived.value == "archived"
        assert WorktreeStatus.failed.value == "failed"


class TestWorktreeEntry:
    def test_to_dict(self):
        e = WorktreeEntry(
            worktree_id="wt-001",
            task_id="task-001",
            path="/tmp/wt-001",
            branch="wt-001-branch",
            status=WorktreeStatus.active,
            created_at="2026-01-01T00:00:00Z",
        )
        d = e.to_dict()
        assert d["worktree_id"] == "wt-001"
        assert d["task_id"] == "task-001"
        assert d["status"] == "active"


class TestWorktreeManager:
    def test_create_worktree(self):
        repo, wt_root = _make_repo()
        try:
            mgr = WorktreeManager(repo_path=repo, worktree_root=wt_root)
            wt = mgr.create("task-001")
            assert wt.task_id == "task-001"
            assert wt.status == WorktreeStatus.active
            assert os.path.exists(wt.path)
            assert os.path.isdir(wt.path)
        finally:
            _cleanup(repo, wt_root)

    def test_create_generates_unique_id(self):
        repo, wt_root = _make_repo()
        try:
            mgr = WorktreeManager(repo_path=repo, worktree_root=wt_root)
            wt1 = mgr.create("task-001")
            wt2 = mgr.create("task-002")
            assert wt1.worktree_id != wt2.worktree_id
            assert wt1.path != wt2.path
        finally:
            _cleanup(repo, wt_root)

    def test_list_worktrees(self):
        repo, wt_root = _make_repo()
        try:
            mgr = WorktreeManager(repo_path=repo, worktree_root=wt_root)
            mgr.create("task-001")
            mgr.create("task-002")
            entries = mgr.list_all()
            assert len(entries) == 2
        finally:
            _cleanup(repo, wt_root)

    def test_get_by_task_id(self):
        repo, wt_root = _make_repo()
        try:
            mgr = WorktreeManager(repo_path=repo, worktree_root=wt_root)
            mgr.create("task-001")
            wt = mgr.get_by_task("task-001")
            assert wt is not None
            assert wt.task_id == "task-001"
        finally:
            _cleanup(repo, wt_root)

    def test_get_by_task_id_not_found(self):
        repo, wt_root = _make_repo()
        try:
            mgr = WorktreeManager(repo_path=repo, worktree_root=wt_root)
            assert mgr.get_by_task("nonexistent") is None
        finally:
            _cleanup(repo, wt_root)

    def test_remove_worktree(self):
        repo, wt_root = _make_repo()
        try:
            mgr = WorktreeManager(repo_path=repo, worktree_root=wt_root)
            wt = mgr.create("task-001")
            assert os.path.exists(wt.path)
            mgr.remove(wt.worktree_id)
            assert not os.path.exists(wt.path)
            assert mgr.get(wt.worktree_id) is None
        finally:
            _cleanup(repo, wt_root)

    def test_remove_by_task_id(self):
        repo, wt_root = _make_repo()
        try:
            mgr = WorktreeManager(repo_path=repo, worktree_root=wt_root)
            wt = mgr.create("task-001")
            mgr.remove_by_task("task-001")
            assert not os.path.exists(wt.path)
        finally:
            _cleanup(repo, wt_root)

    def test_archive_worktree(self):
        repo, wt_root = _make_repo()
        try:
            mgr = WorktreeManager(repo_path=repo, worktree_root=wt_root)
            wt = mgr.create("task-001")
            mgr.archive(wt.worktree_id)
            entry = mgr.get(wt.worktree_id)
            assert entry.status == WorktreeStatus.archived
        finally:
            _cleanup(repo, wt_root)

    def test_cleanup_all(self):
        repo, wt_root = _make_repo()
        try:
            mgr = WorktreeManager(repo_path=repo, worktree_root=wt_root)
            wt1 = mgr.create("task-001")
            wt2 = mgr.create("task-002")
            mgr.cleanup_all()
            assert not os.path.exists(wt1.path)
            assert not os.path.exists(wt2.path)
            assert len(mgr.list_all()) == 0
        finally:
            _cleanup(repo, wt_root)

    def test_path_isolation(self):
        """验证两个 worktree 的文件互不影响。"""
        repo, wt_root = _make_repo()
        try:
            mgr = WorktreeManager(repo_path=repo, worktree_root=wt_root)
            wt1 = mgr.create("task-001")
            wt2 = mgr.create("task-002")
            # 在 wt1 中创建文件
            f1 = os.path.join(wt1.path, "from_wt1.txt")
            with open(f1, "w") as f:
                f.write("from wt1")
            # wt2 中不应有这个文件
            f2 = os.path.join(wt2.path, "from_wt1.txt")
            assert not os.path.exists(f2)
        finally:
            _cleanup(repo, wt_root)

    def test_commit_in_worktree_visible_in_main(self):
        """在 worktree 中 commit 后，主仓库能看到该分支。"""
        repo, wt_root = _make_repo()
        try:
            mgr = WorktreeManager(repo_path=repo, worktree_root=wt_root)
            wt = mgr.create("task-001")
            # 在 worktree 中创建文件并 commit
            f = os.path.join(wt.path, "new_file.txt")
            with open(f, "w") as fh:
                fh.write("new content")
            subprocess.run(["git", "-C", wt.path, "add", "."], capture_output=True)
            subprocess.run(
                ["git", "-C", wt.path, "commit", "-m", "from worktree"],
                capture_output=True,
            )
            # 主仓库应能看到该分支
            result = subprocess.run(
                ["git", "-C", repo, "branch", "--list"],
                capture_output=True, text=True,
            )
            assert wt.branch in result.stdout
        finally:
            _cleanup(repo, wt_root)

    def test_stats(self):
        repo, wt_root = _make_repo()
        try:
            mgr = WorktreeManager(repo_path=repo, worktree_root=wt_root)
            mgr.create("task-001")
            mgr.create("task-002")
            mgr.create("task-003")
            wt = mgr.create("task-004")
            mgr.archive(wt.worktree_id)
            stats = mgr.stats()
            assert stats["total"] == 4
            assert stats["active"] == 3
            assert stats["archived"] == 1
        finally:
            _cleanup(repo, wt_root)

    def test_custom_branch_name(self):
        repo, wt_root = _make_repo()
        try:
            mgr = WorktreeManager(repo_path=repo, worktree_root=wt_root)
            wt = mgr.create("task-001", branch_name="feature/custom")
            assert wt.branch == "feature/custom"
        finally:
            _cleanup(repo, wt_root)

    def test_fail_status_on_git_error(self):
        """git 命令失败时标记为 failed。"""
        repo, wt_root = _make_repo()
        try:
            # 指向不存在的 repo
            mgr = WorktreeManager(
                repo_path="/nonexistent/repo",
                worktree_root=wt_root,
            )
            try:
                mgr.create("task-001")
            except Exception:
                pass
            # 失败后不应有 worktree 记录
            assert len(mgr.list_all()) == 0
        finally:
            _cleanup(repo, wt_root)

    def test_merge_worktree_branch(self):
        """worktree 分支可合并回主分支。"""
        repo, wt_root = _make_repo()
        try:
            mgr = WorktreeManager(repo_path=repo, worktree_root=wt_root)
            wt = mgr.create("task-001")
            # 在 worktree 中创建文件并 commit
            f = os.path.join(wt.path, "merged_file.txt")
            with open(f, "w") as fh:
                fh.write("merged content")
            subprocess.run(["git", "-C", wt.path, "add", "."], capture_output=True)
            subprocess.run(
                ["git", "-C", wt.path, "commit", "-m", "to merge"],
                capture_output=True,
            )
            # 合并回主分支
            result = mgr.merge_to_main(wt.worktree_id)
            assert result is True
            # 主仓库应有 merged_file.txt
            merged_file = os.path.join(repo, "merged_file.txt")
            assert os.path.exists(merged_file)
        finally:
            _cleanup(repo, wt_root)
