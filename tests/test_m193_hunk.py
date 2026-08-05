"""M193.1 · 逐 hunk 拒绝（Review 面板）：POST /api/v1/project/revert-hunk。

契约：
- 请求 {path: str(min_length=1), hunk_index: int(ge=0)}；
  响应 {ok, path, hunk_index, action="hunk_reverted"}。
- 处理顺序钉死：FLIPPED_REVIEW=0 → 404；无项目 → 400；路径穿越 → 403；
  目录 → 422；untracked → 422「新文件无 hunk，请用整文件回滚」；
  git diff 失败 → 500；无变更 → 404「该文件当前无变更」；
  header 含 /dev/null（新增/删除文件）→ 422「新增/删除文件请用整文件回滚」；
  hunk_index 越界 → 422「hunk_index 越界（共 N 个 hunk）」；
  git apply --reverse 失败 → 409「工作区已变化（diff 漂移），请刷新后重试」。
- split_patch_hunks 纯函数：header = 首个 "@@ " 行之前的全部行；
  hunks[i] = 第 i 个 "@@ " 行起到下个 "@@ " 或 EOF；空 patch → ([], [])。

测试风格沿用 test_m177_review.py：TestClient + ps.set_active/clear_active +
tmp_path 真 git 仓库（无 git → 全模块 skip），不 mock git 语义；
仅「git apply 失败」一条用 monkeypatch mock subprocess.run 返 rc=1。
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
    """隔离 DB + mock orchestrator，返回 TestClient（同 test_m177_review.py）。"""
    monkeypatch.setenv("FLIPPED_MOCK_ORCHESTRATOR", "1")
    monkeypatch.setattr("api.main.FLIPPED_CHECKPOINT_DB", str(tmp_path / "cp.db"))
    from api.main import app
    return TestClient(app)


BASE_LINES = [f"line-{i:02d}" for i in range(1, 31)]  # 30 行基线


@pytest.fixture()
def repo(tmp_path):
    """tmp_path 下真 git 仓库：30 行 file.txt + 不动的 other.txt，设为活动项目。"""
    from api import project_state as ps
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "t")
    (root / "file.txt").write_text("\n".join(BASE_LINES) + "\n")
    (root / "other.txt").write_text("untouched\n")
    _git(root, "add", ".")
    _git(root, "commit", "-m", "init")
    ps.set_active(root)
    yield root
    ps.clear_active()


def _modify_two(repo):
    """改第 3 行与第 27 行（远隔，保证 git diff 产出 2 个 hunk）。"""
    lines = BASE_LINES.copy()
    lines[2] = "line-03-modified"
    lines[26] = "line-27-modified"
    (repo / "file.txt").write_text("\n".join(lines) + "\n")


def _post(client, path, hunk_index=0):
    return client.post("/api/v1/project/revert-hunk",
                       json={"path": path, "hunk_index": hunk_index})


# ====================================================================
# 1 · split_patch_hunks 纯函数
# ====================================================================

def test_split_patch_hunks_multi_hunk():
    """多 hunk 拆分：header 行数 / hunks 数 / 各 hunk 首行与内容边界。"""
    from api.main import split_patch_hunks
    patch = (
        "diff --git a/f b/f\n"
        "index 111..222 100644\n"
        "--- a/f\n"
        "+++ b/f\n"
        "@@ -1,3 +1,3 @@\n"
        " ctx\n"
        "-old\n"
        "+new\n"
        "@@ -10,3 +10,3 @@\n"
        " ctx2\n"
        "-old2\n"
        "+new2\n"
    )
    header, hunks = split_patch_hunks(patch)
    assert header == ["diff --git a/f b/f", "index 111..222 100644",
                      "--- a/f", "+++ b/f"]
    assert len(hunks) == 2
    assert hunks[0][0] == "@@ -1,3 +1,3 @@"
    assert hunks[0][1:] == [" ctx", "-old", "+new"]
    assert hunks[1][0] == "@@ -10,3 +10,3 @@"
    assert hunks[1][1:] == [" ctx2", "-old2", "+new2"]


def test_split_patch_hunks_header_only():
    """仅 header 无 hunk → hunks == []。"""
    from api.main import split_patch_hunks
    header, hunks = split_patch_hunks("diff --git a/f b/f\n--- a/f\n+++ b/f\n")
    assert header == ["diff --git a/f b/f", "--- a/f", "+++ b/f"]
    assert hunks == []


def test_split_patch_hunks_empty():
    """空 patch → ([], [])。"""
    from api.main import split_patch_hunks
    assert split_patch_hunks("") == ([], [])


# ====================================================================
# 2 · 契约校验（pydantic）
# ====================================================================

def test_contract_empty_path_422(client, repo):
    """空 path → 422（min_length=1）。"""
    r = client.post("/api/v1/project/revert-hunk",
                    json={"path": "", "hunk_index": 0})
    assert r.status_code == 422


def test_contract_negative_hunk_index_422(client, repo):
    """hunk_index=-1 → 422（ge=0）。"""
    r = client.post("/api/v1/project/revert-hunk",
                    json={"path": "file.txt", "hunk_index": -1})
    assert r.status_code == 422


# ====================================================================
# 3 · 真 repo 端到端：拒 hunk0 → 重取 diff → 拒剩余 hunk → 工作区干净
# ====================================================================

def test_revert_hunk_end_to_end(client, repo):
    """两处改动 2 个 hunk：拒 hunk0 后 hunk0 段回 HEAD、hunk1 段保留；
    重取 diff 再拒剩余 hunk 后 git diff HEAD 为空、文件 == HEAD。"""
    _modify_two(repo)
    r = _post(client, "file.txt", 0)
    assert r.status_code == 200, r.text
    assert r.json() == {"ok": True, "path": "file.txt", "hunk_index": 0,
                        "action": "hunk_reverted"}
    lines = (repo / "file.txt").read_text().splitlines()
    assert lines[2] == "line-03", "hunk0 段应回 HEAD 内容"
    assert lines[26] == "line-27-modified", "hunk1 段改动应保留"

    # diff 已漂移：重取 /project/diff 后再拒剩余的那个 hunk（新序号 0）
    r2 = client.get("/api/v1/project/diff")
    assert r2.status_code == 200, r2.text
    r3 = _post(client, "file.txt", 0)
    assert r3.status_code == 200, r3.text
    assert r3.json()["action"] == "hunk_reverted"

    assert (repo / "file.txt").read_text().splitlines() == BASE_LINES
    out = subprocess.run(["git", "diff", "HEAD"], cwd=str(repo),
                         capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "", "两个 hunk 都拒绝后工作区应与 HEAD 一致"


# ====================================================================
# 4 · hunk_index 越界 → 422（detail 含总数）
# ====================================================================

def test_hunk_index_out_of_range_422(client, repo):
    _modify_two(repo)
    r = _post(client, "file.txt", 99)
    assert r.status_code == 422
    assert "共 2 个 hunk" in r.json()["detail"]


# ====================================================================
# 5 · 无变更 tracked 文件 → 404
# ====================================================================

def test_no_change_tracked_file_404(client, repo):
    r = _post(client, "other.txt", 0)
    assert r.status_code == 404
    assert "无变更" in r.json()["detail"]


# ====================================================================
# 6 · 路径穿越 → 403；目录 → 422
# ====================================================================

def test_path_traversal_403(client, repo, tmp_path):
    """../ 穿越到项目外 → 403，且外部文件毫发无损。"""
    outside = tmp_path / "outside.txt"
    outside.write_text("evil\n")
    r = _post(client, "../outside.txt", 0)
    assert r.status_code == 403
    assert "outside" in r.json()["detail"]
    assert outside.read_text() == "evil\n", "路径穿越绝不能动项目外文件"


def test_directory_422(client, repo):
    """path 指向根目录(.)或子目录 → 422「不能回滚目录」。"""
    r = _post(client, ".", 0)
    assert r.status_code == 422
    assert "目录" in r.json()["detail"]
    (repo / "pkg").mkdir()
    r2 = _post(client, "pkg", 0)
    assert r2.status_code == 422
    assert "目录" in r2.json()["detail"]


# ====================================================================
# 7 · untracked 文件 → 422「整文件回滚」
# ====================================================================

def test_untracked_file_422(client, repo):
    (repo / "new.txt").write_text("new\n")
    r = _post(client, "new.txt", 0)
    assert r.status_code == 422
    assert "整文件回滚" in r.json()["detail"]


# ====================================================================
# 8 · git add 后的新文件（diff header 含 /dev/null）→ 422
# ====================================================================

def test_staged_new_file_422(client, repo):
    (repo / "staged_new.txt").write_text("new\n")
    _git(repo, "add", "staged_new.txt")
    r = _post(client, "staged_new.txt", 0)
    assert r.status_code == 422
    assert "整文件回滚" in r.json()["detail"]


# ====================================================================
# 9 · FLIPPED_REVIEW=0 → 404
# ====================================================================

def test_disabled_by_env_404(client, repo, monkeypatch):
    monkeypatch.setenv("FLIPPED_REVIEW", "0")
    r = _post(client, "file.txt", 0)
    assert r.status_code == 404
    assert "Review 功能已禁用" in r.json()["detail"]


# ====================================================================
# 10 · git apply 失败（mock subprocess.run 返 rc=1）→ 409「漂移」
# ====================================================================

def test_git_apply_failure_409(client, repo, monkeypatch):
    _modify_two(repo)
    real_run = subprocess.run

    def fake_run(args, **kwargs):
        # 只拦截 git apply，其余 git 调用（diff/ls-files）走真语义
        if isinstance(args, (list, tuple)) and "apply" in args:
            return subprocess.CompletedProcess(args, 1, "", "error: patch failed")
        return real_run(args, **kwargs)

    monkeypatch.setattr(subprocess, "run", fake_run)
    r = _post(client, "file.txt", 0)
    assert r.status_code == 409
    assert "漂移" in r.json()["detail"]


# ====================================================================
# 11 · 无活动项目 → 400
# ====================================================================

def test_no_project_400(client):
    from api import project_state as ps
    ps.clear_active()
    r = _post(client, "file.txt", 0)
    assert r.status_code == 400
    assert "未选择项目" in r.json()["detail"]
