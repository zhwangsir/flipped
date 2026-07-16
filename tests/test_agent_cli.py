"""M129 · Agent CLI 工具暴露测试。"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile

from driving.agent_cli import AgentCLI, CLIResult


def _make_repo() -> str:
    repo_dir = tempfile.mkdtemp(prefix="repo_")
    subprocess.run(["git", "init", repo_dir], capture_output=True)
    subprocess.run(["git", "-C", repo_dir, "config", "user.email", "t@t.com"], capture_output=True)
    subprocess.run(["git", "-C", repo_dir, "config", "user.name", "T"], capture_output=True)
    with open(os.path.join(repo_dir, "README.md"), "w") as f:
        f.write("# Test\n")
    subprocess.run(["git", "-C", repo_dir, "add", "."], capture_output=True)
    subprocess.run(["git", "-C", repo_dir, "commit", "-m", "init"], capture_output=True)
    return repo_dir


def _cleanup(*paths: str) -> None:
    for p in paths:
        if os.path.exists(p):
            shutil.rmtree(p, ignore_errors=True)


class TestCLIResult:
    def test_to_json(self):
        r = CLIResult(success=True, output={"key": "val"}, message="ok")
        j = r.to_json()
        assert '"success": true' in j
        assert '"key": "val"' in j


class TestAgentCLI:
    def test_help(self):
        cli = AgentCLI()
        result = cli.help()
        assert result.success is True
        assert "commands" in result.output
        assert "worktree_create" in result.output["commands"]

    def test_execute_empty_returns_help(self):
        cli = AgentCLI()
        result = cli.execute([])
        assert result.success is True
        assert "commands" in result.output

    def test_execute_unknown_command(self):
        cli = AgentCLI()
        result = cli.execute(["nonexistent"])
        assert result.success is False
        assert "Unknown command" in result.message

    def test_worktree_create_and_list(self):
        repo = _make_repo()
        wt_root = tempfile.mkdtemp(prefix="wt_")
        try:
            cli = AgentCLI(repo_path=repo, worktree_root=wt_root)
            # Create
            result = cli.execute(["worktree", "create", "task-001"])
            assert result.success is True
            assert "worktree_id" in result.output

            # List
            result = cli.execute(["worktree", "list"])
            assert result.success is True
            assert result.output["count"] == 1
        finally:
            _cleanup(repo, wt_root)

    def test_worktree_stats(self):
        repo = _make_repo()
        wt_root = tempfile.mkdtemp(prefix="wt_")
        try:
            cli = AgentCLI(repo_path=repo, worktree_root=wt_root)
            cli.execute(["worktree", "create", "task-001"])
            result = cli.execute(["worktree", "stats"])
            assert result.success is True
            assert result.output["total"] == 1
        finally:
            _cleanup(repo, wt_root)

    def test_worktree_remove(self):
        repo = _make_repo()
        wt_root = tempfile.mkdtemp(prefix="wt_")
        try:
            cli = AgentCLI(repo_path=repo, worktree_root=wt_root)
            create_result = cli.execute(["worktree", "create", "task-001"])
            wt_id = create_result.output["worktree_id"]
            result = cli.execute(["worktree", "remove", wt_id])
            assert result.success is True
        finally:
            _cleanup(repo, wt_root)

    def test_status_list(self):
        cli = AgentCLI()
        result = cli.execute(["status", "list"])
        assert result.success is True
        assert "total" in result.output

    def test_status_update(self):
        cli = AgentCLI()
        result = cli.execute(["status", "update", "agent-1", "active"])
        assert result.success is True
        assert result.output["new_status"] == "active"

    def test_status_update_invalid(self):
        cli = AgentCLI()
        result = cli.execute(["status", "update", "agent-1", "invalid"])
        assert result.success is False
        assert "Invalid status" in result.message

    def test_worktree_create_with_branch(self):
        repo = _make_repo()
        wt_root = tempfile.mkdtemp(prefix="wt_")
        try:
            cli = AgentCLI(repo_path=repo, worktree_root=wt_root)
            result = cli.execute([
                "worktree", "create", "task-001", "--branch", "feature/test"
            ])
            assert result.success is True
            assert result.output["branch"] == "feature/test"
        finally:
            _cleanup(repo, wt_root)

    def test_snapshot(self):
        """截图命令测试（使用 mock 截图函数）。"""
        cli = AgentCLI()
        # 注入 mock 截图函数
        def mock_screenshot(url, path):
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as f:
                f.write(b"png")
            from driving.visual_feedback import ScreenshotResult
            return ScreenshotResult(path=path, timestamp="t", file_hash="h")
        cli.visual.screenshot_fn = mock_screenshot

        result = cli.execute(["snapshot", "http://localhost:3000", "--name", "test"])
        assert result.success is True
        assert "path" in result.output

    def test_fan_out(self):
        repo = _make_repo()
        wt_root = tempfile.mkdtemp(prefix="wt_")
        try:
            cli = AgentCLI(repo_path=repo, worktree_root=wt_root)
            result = cli.execute(["fan_out", "task-001", "--agents", "2"])
            assert result.success is True
            assert "runs" in result.output
        finally:
            _cleanup(repo, wt_root)

    def test_to_json_output(self):
        """验证所有命令输出可序列化为 JSON。"""
        cli = AgentCLI()
        for cmd in [["help"], ["status", "list"], ["worktree", "stats"]]:
            result = cli.execute(cmd)
            # 不应抛出异常
            j = result.to_json()
            assert isinstance(j, str)
