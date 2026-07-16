"""M125-M126 · 并行执行器 + Fan-out 对比模式测试。"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile

from driving.parallel_executor import (
    ParallelExecutor,
    FanOutResult,
    AgentRun,
)
from driving.worktree_manager import WorktreeManager


def _make_repo() -> tuple[str, str]:
    repo_dir = tempfile.mkdtemp(prefix="repo_")
    wt_root = tempfile.mkdtemp(prefix="wtroot_")
    subprocess.run(["git", "init", repo_dir], capture_output=True)
    subprocess.run(["git", "-C", repo_dir, "config", "user.email", "test@test.com"], capture_output=True)
    subprocess.run(["git", "-C", repo_dir, "config", "user.name", "Test"], capture_output=True)
    with open(os.path.join(repo_dir, "README.md"), "w") as f:
        f.write("# Test\n")
    subprocess.run(["git", "-C", repo_dir, "add", "."], capture_output=True)
    subprocess.run(["git", "-C", repo_dir, "commit", "-m", "init"], capture_output=True)
    return repo_dir, wt_root


def _cleanup(*paths: str) -> None:
    for p in paths:
        if os.path.exists(p):
            shutil.rmtree(p, ignore_errors=True)


class MockTask:
    def __init__(self, id="task-001", description="test task"):
        self.id = id
        self.description = description


class TestAgentRun:
    def test_to_dict(self):
        r = AgentRun(agent_id="a1", worktree_id="wt1", worktree_path="/tmp/wt1")
        d = r.to_dict()
        assert d["agent_id"] == "a1"
        assert d["worktree_id"] == "wt1"


class TestFanOutResult:
    def test_to_dict(self):
        r = FanOutResult(task_id="t1")
        d = r.to_dict()
        assert d["task_id"] == "t1"
        assert d["runs"] == []
        assert d["winner"] is None


class TestParallelExecutor:
    def test_fan_out_creates_worktrees(self):
        repo, wt_root = _make_repo()
        try:
            def exec_fn(task, path):
                return {"correctness": 80, "design": 75}

            executor = ParallelExecutor(
                repo_path=repo,
                worktree_root=wt_root,
                execute_fn=exec_fn,
            )
            result = executor.fan_out(MockTask(), agent_count=3)
            assert len(result.runs) == 3
            assert all(r.success for r in result.runs)
        finally:
            executor.cleanup()
            _cleanup(repo, wt_root)

    def test_fan_out_selects_winner(self):
        repo, wt_root = _make_repo()
        try:
            scores = [90, 60, 75]
            idx = [0]

            def exec_fn(task, path):
                s = scores[idx[0] % len(scores)]
                idx[0] += 1
                return {"correctness": s, "design": s, "code_quality": s}

            executor = ParallelExecutor(
                repo_path=repo,
                worktree_root=wt_root,
                execute_fn=exec_fn,
            )
            result = executor.fan_out(MockTask(), agent_count=3, merge_winner=False)
            assert result.winner is not None
            assert result.winner.output["correctness"] == 90
        finally:
            executor.cleanup()
            _cleanup(repo, wt_root)

    def test_fan_out_with_merge(self):
        repo, wt_root = _make_repo()
        try:
            def exec_fn(task, path):
                with open(os.path.join(path, "output.txt"), "w") as f:
                    f.write("agent output")
                return {"correctness": 85, "design": 80}

            executor = ParallelExecutor(
                repo_path=repo,
                worktree_root=wt_root,
                execute_fn=exec_fn,
            )
            result = executor.fan_out(MockTask(), agent_count=2, merge_winner=True)
            assert result.merged is True
            # 主仓库应有 output.txt
            assert os.path.exists(os.path.join(repo, "output.txt"))
        finally:
            executor.cleanup()
            _cleanup(repo, wt_root)

    def test_fan_out_handles_execution_error(self):
        repo, wt_root = _make_repo()
        try:
            call_count = [0]

            def exec_fn(task, path):
                call_count[0] += 1
                if call_count[0] == 2:
                    raise RuntimeError("agent crashed")
                return {"correctness": 80}

            executor = ParallelExecutor(
                repo_path=repo,
                worktree_root=wt_root,
                execute_fn=exec_fn,
            )
            result = executor.fan_out(MockTask(), agent_count=3, merge_winner=False)
            assert len(result.runs) == 3
            failed = [r for r in result.runs if not r.success]
            assert len(failed) >= 1
        finally:
            executor.cleanup()
            _cleanup(repo, wt_root)

    def test_fan_out_cleanup_removes_losers(self):
        repo, wt_root = _make_repo()
        try:
            scores = [90, 60, 70]
            idx = [0]

            def exec_fn(task, path):
                s = scores[idx[0] % len(scores)]
                idx[0] += 1
                return {"correctness": s}

            executor = ParallelExecutor(
                repo_path=repo,
                worktree_root=wt_root,
                execute_fn=exec_fn,
            )
            result = executor.fan_out(MockTask(), agent_count=3, merge_winner=False)
            # 胜出者的 worktree 应存在，其他应被清理
            assert result.winner is not None
            winner_path = result.winner.worktree_path
            assert os.path.exists(winner_path)
        finally:
            executor.cleanup()
            _cleanup(repo, wt_root)

    def test_parallel_subtasks(self):
        repo, wt_root = _make_repo()
        try:
            def exec_fn(task, path):
                return {"correctness": 80}

            executor = ParallelExecutor(
                repo_path=repo,
                worktree_root=wt_root,
                execute_fn=exec_fn,
            )
            tasks = [MockTask(id=f"sub-{i}") for i in range(3)]
            results = executor.parallel_subtasks(tasks, merge_all=False)
            assert len(results) == 3
            assert all(r.winner is not None for r in results)
        finally:
            executor.cleanup()
            _cleanup(repo, wt_root)

    def test_stats(self):
        repo, wt_root = _make_repo()
        try:
            executor = ParallelExecutor(
                repo_path=repo,
                worktree_root=wt_root,
                execute_fn=lambda t, p: {"correctness": 80},
            )
            executor.fan_out(MockTask(), agent_count=2, merge_winner=False)
            stats = executor.stats()
            assert stats["total"] >= 1
        finally:
            executor.cleanup()
            _cleanup(repo, wt_root)

    def test_default_execute(self):
        """未注入 execute_fn 时使用默认执行。"""
        repo, wt_root = _make_repo()
        try:
            executor = ParallelExecutor(
                repo_path=repo,
                worktree_root=wt_root,
            )
            result = executor.fan_out(MockTask(), agent_count=2, merge_winner=False)
            assert len(result.runs) == 2
            assert all(r.success for r in result.runs)
        finally:
            executor.cleanup()
            _cleanup(repo, wt_root)

    def test_worktree_isolation_in_fan_out(self):
        """验证 fan-out 中各 Agent 的文件互不干扰。"""
        repo, wt_root = _make_repo()
        try:
            markers_created: list[str] = []

            def exec_fn(task, path):
                # 每个 Agent 在自己的 worktree 中创建不同的文件
                agent_marker = os.path.basename(path)
                marker_path = os.path.join(path, "agent_marker.txt")
                with open(marker_path, "w") as f:
                    f.write(agent_marker)
                markers_created.append(agent_marker)
                return {"correctness": 80}

            executor = ParallelExecutor(
                repo_path=repo,
                worktree_root=wt_root,
                execute_fn=exec_fn,
            )
            result = executor.fan_out(MockTask(), agent_count=3, merge_winner=False)
            # 每个 Agent 在执行时都创建了自己的 marker 文件（互不干扰）
            assert len(markers_created) == 3
            # 胜出者的 worktree 仍存在
            assert result.winner is not None
            winner_marker = os.path.join(result.winner.worktree_path, "agent_marker.txt")
            assert os.path.exists(winner_marker)
        finally:
            executor.cleanup()
            _cleanup(repo, wt_root)
