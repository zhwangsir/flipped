"""M177.1 · Review 面板强化（B 队后端）：diff 补 untracked + 逐文件 revert。

- GET /api/v1/project/diff：在原 `git diff HEAD` 结果后追加 untracked 新文件条目
  （agent 新写的文件在审查面板不再隐形）。条目形状：
  {"path", "added", "removed": 0, "lines": [], "untracked": True}；
  二进制（utf-8 解码失败 / 含 \\x00 / > _FILE_MAX_BYTES）→ added=0 + binary=True。
- POST /api/v1/project/revert：逐文件回滚。tracked → `git restore --source=HEAD
  --worktree -- <rel>`（只动 worktree，绝不碰 staging area）；untracked → 删除。
  防护：FLIPPED_REVIEW=0 → 404；无项目 → 400；路径穿越 → 403；目录 → 422；
  未知文件 → 404。

测试风格沿用 test_m168_undo.py：TestClient + ps.set_active/clear_active +
tmp_path 真 git 仓库（无 git → 全模块 skip）。
"""
from __future__ import annotations

import shutil
import subprocess

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git 不可用")


def _git(root, *args):
    subprocess.run(["git", *args], cwd=str(root), check=True,
                   capture_output=True, text=True)


@pytest.fixture()
def client(monkeypatch, tmp_path):
    """隔离 DB + mock orchestrator，返回 TestClient（同 test_m168_undo.py）。"""
    monkeypatch.setenv("FLIPPED_MOCK_ORCHESTRATOR", "1")
    monkeypatch.setattr("api.main.FLIPPED_CHECKPOINT_DB", str(tmp_path / "cp.db"))
    from api.main import app
    return TestClient(app)


@pytest.fixture()
def repo(tmp_path):
    """tmp_path 下真 git 仓库（含一个 tracked 文件）并设为活动项目；测后清理。"""
    from api import project_state as ps
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "t")
    (root / "tracked.txt").write_text("v1\n")
    _git(root, "add", ".")
    _git(root, "commit", "-m", "init")
    ps.set_active(root)
    yield root
    ps.clear_active()


def _diff_files(client):
    r = client.get("/api/v1/project/diff")
    assert r.status_code == 200, r.text
    return r.json()["files"]


def _revert(client, path):
    return client.post("/api/v1/project/revert", json={"path": path})


# ====================================================================
# 1 · diff 补 untracked
# ====================================================================

def test_diff_includes_untracked_files(client, repo):
    """agent 新写的未跟踪文件出现在 diff files 里，带 untracked=True 标记。"""
    (repo / "new.py").write_text("print(1)\n")
    files = _diff_files(client)
    match = [f for f in files if f["path"] == "new.py"]
    assert len(match) == 1
    entry = match[0]
    assert entry["untracked"] is True
    assert entry["removed"] == 0
    assert entry["lines"] == []


def test_diff_untracked_line_count(client, repo):
    """untracked 文本文件 added = utf-8 行数（splitlines 长度）。"""
    (repo / "three.txt").write_text("a\nb\nc\n")
    files = _diff_files(client)
    entry = next(f for f in files if f["path"] == "three.txt")
    assert entry["added"] == 3
    assert "binary" not in entry


def test_diff_untracked_binary_marked(client, repo):
    """含 \\x00 字节的 untracked 文件 → binary=True 且 added=0。"""
    (repo / "bin.dat").write_bytes(b"\x00\x01\x02\x03")
    files = _diff_files(client)
    entry = next(f for f in files if f["path"] == "bin.dat")
    assert entry["binary"] is True
    assert entry["added"] == 0


def test_diff_untracked_respects_gitignore(client, repo):
    """--exclude-standard：.gitignore 排除的文件不出现在 diff。"""
    (repo / ".gitignore").write_text("ignored.txt\n")
    _git(repo, "add", ".gitignore")
    _git(repo, "commit", "-m", "gitignore")
    (repo / "ignored.txt").write_text("x\n")
    (repo / "visible.txt").write_text("y\n")
    paths = [f["path"] for f in _diff_files(client)]
    assert "ignored.txt" not in paths
    assert "visible.txt" in paths


# ====================================================================
# 2 · revert 成功路径
# ====================================================================

def test_revert_tracked_modified_restores_head(client, repo):
    """tracked 文件被改 → revert → action=restored，内容回 HEAD。"""
    (repo / "tracked.txt").write_text("v2-modified\n")
    r = _revert(client, "tracked.txt")
    assert r.status_code == 200, r.text
    assert r.json() == {"ok": True, "path": "tracked.txt", "action": "restored"}
    assert (repo / "tracked.txt").read_text() == "v1\n"


def test_revert_tracked_deleted_restores_file(client, repo):
    """tracked 文件被删（仍在 index）→ revert → 文件恢复到 HEAD 内容。"""
    (repo / "tracked.txt").unlink()
    r = _revert(client, "tracked.txt")
    assert r.status_code == 200, r.text
    assert r.json()["action"] == "restored"
    assert (repo / "tracked.txt").read_text() == "v1\n"


def test_revert_untracked_deletes_file(client, repo):
    """untracked 新文件 → revert → action=deleted，文件不存在。"""
    new = repo / "agent_new.py"
    new.write_text("x\n")
    r = _revert(client, "agent_new.py")
    assert r.status_code == 200, r.text
    assert r.json() == {"ok": True, "path": "agent_new.py", "action": "deleted"}
    assert not new.exists()


# ====================================================================
# 3 · revert 防护
# ====================================================================

def test_revert_path_traversal_403(client, repo, tmp_path):
    """../ 穿越到项目外 → 403，且外部文件毫发无损。"""
    outside = tmp_path / "outside.txt"
    outside.write_text("evil\n")
    r = _revert(client, "../outside.txt")
    assert r.status_code == 403
    assert "outside" in r.json()["detail"]
    assert outside.exists(), "路径穿越绝不能删项目外文件"


def test_revert_directory_422(client, repo):
    """path 指向根目录(.)或子目录 → 422「不能回滚目录」。"""
    r = _revert(client, ".")
    assert r.status_code == 422
    assert "目录" in r.json()["detail"]
    subdir = repo / "pkg"
    subdir.mkdir()
    r2 = _revert(client, "pkg")
    assert r2.status_code == 422


def test_revert_unknown_file_404(client, repo):
    """path 不存在且非 tracked → 404 not a file。"""
    r = _revert(client, "nope.txt")
    assert r.status_code == 404
    assert "not a file" in r.json()["detail"]


def test_revert_disabled_by_env_404(client, repo, monkeypatch):
    """FLIPPED_REVIEW=0 → 404「Review 功能已禁用」。"""
    monkeypatch.setenv("FLIPPED_REVIEW", "0")
    r = _revert(client, "tracked.txt")
    assert r.status_code == 404
    assert "Review 功能已禁用" in r.json()["detail"]


def test_revert_keeps_staging_area_untouched(client, repo):
    """tracked 文件改动后 git add（已入 staging）→ revert 只回 worktree：

    worktree 内容回 HEAD，staging area 里的 staged 改动原样保留。
    """
    (repo / "tracked.txt").write_text("v2-staged\n")
    _git(repo, "add", "tracked.txt")
    r = _revert(client, "tracked.txt")
    assert r.status_code == 200, r.text
    assert r.json()["action"] == "restored"
    assert (repo / "tracked.txt").read_text() == "v1\n", "worktree 应回 HEAD"
    staged = subprocess.run(
        ["git", "diff", "--cached", "--name-only"],
        cwd=str(repo), capture_output=True, text=True, check=True,
    ).stdout.splitlines()
    assert "tracked.txt" in staged, "staging area 不得被 revert 触碰"
