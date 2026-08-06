"""M196 · 评审历史项目资产化（消化 L-M186-1）+ RAG_EMBEDDING=mock 开关（M196.3 hermetic）。

- _reviews_dir 三级解析：env FLIPPED_REVIEWS_DIR 覆盖 > 活动项目 {root}/.flipped/reviews
  > data/reviews 兜底。
- _reviews_dir_migrated：env 未设时 legacy data/reviews/<project> 一次性 move 迁入；
  env 覆盖时跳过迁移（测试隔离语义不动）。
- migrate_legacy_reviews：move 一次幂等 / 目标已有不覆盖 / 源缺失 False / src==dst 守卫。
- 端点级（无 env）：POST /project/review 落盘进项目 .flipped/reviews；预置 legacy
  记录经 GET /project/reviews 触发迁移后可见且 legacy 目录消失。
- _default_embedding：RAG_EMBEDDING=mock 短路返回 MockEmbedding（不实例化 ST）。
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api.review_store import list_reviews, migrate_legacy_reviews, save_review
from rag.embeddings import MockEmbedding, _default_embedding

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git 不可用")


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=str(root), check=True,
                   capture_output=True, text=True)


@pytest.fixture()
def repo(tmp_path):
    """tmp_path 下真 git 仓库（含 tracked 文件）并设为活动项目；测后清理。"""
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


@pytest.fixture()
def client_no_env(monkeypatch, tmp_path):
    """TestClient：不设 FLIPPED_REVIEWS_DIR（走 M196.4 项目资产默认路径）。"""
    monkeypatch.delenv("FLIPPED_REVIEWS_DIR", raising=False)
    monkeypatch.setenv("FLIPPED_MOCK_ORCHESTRATOR", "1")
    monkeypatch.setattr("api.main.FLIPPED_CHECKPOINT_DB", str(tmp_path / "cp.db"))
    from api.main import app
    return TestClient(app)


@pytest.fixture()
def fake_llm(monkeypatch):
    """fake _llm_chat（返回空 findings 列表）+ resolve_worker_model_config。"""

    async def _fake_chat(base_url, model, system, user, timeout=120.0):
        return "[]", None

    monkeypatch.setattr("api.main._llm_chat", _fake_chat)
    monkeypatch.setattr(
        "driving.model_router.resolve_worker_model_config",
        lambda alias="coder": ("http://fake-llm", f"fake-{alias}"),
    )


# ====================================================================
# 1 · _reviews_dir 三级解析
# ====================================================================

def test_reviews_dir_env_override_wins(monkeypatch, repo, tmp_path):
    """env 覆盖优先：有活动项目也走 env 路径。"""
    from api.main import _reviews_dir
    monkeypatch.setenv("FLIPPED_REVIEWS_DIR", str(tmp_path / "iso"))
    assert _reviews_dir() == tmp_path / "iso"


def test_reviews_dir_project_asset_default(monkeypatch, repo):
    """无 env + 活动项目 → {root}/.flipped/reviews（项目资产）。"""
    from api.main import _reviews_dir
    monkeypatch.delenv("FLIPPED_REVIEWS_DIR", raising=False)
    assert _reviews_dir() == repo / ".flipped" / "reviews"


def test_reviews_dir_no_project_fallback(monkeypatch):
    """无 env + 无活动项目 → data/reviews 兜底（现状语义）。"""
    from api import project_state as ps
    from api.main import _reviews_dir
    monkeypatch.delenv("FLIPPED_REVIEWS_DIR", raising=False)
    ps.clear_active()
    assert _reviews_dir() == Path("data/reviews")


# ====================================================================
# 2 · migrate_legacy_reviews 纯逻辑
# ====================================================================

def test_migrate_moves_legacy_once(tmp_path):
    """legacy 整目录 move 到新位置；二次调用幂等 False。"""
    legacy = tmp_path / "data" / "reviews"
    new = tmp_path / "proj" / ".flipped" / "reviews"
    save_review(legacy, project="p", model="m", files_reviewed=0, findings=[])
    assert migrate_legacy_reviews(legacy, new, "p") is True
    assert not (legacy / "p").exists()
    assert len(list((new / "p").glob("*.json"))) == 1
    assert migrate_legacy_reviews(legacy, new, "p") is False  # 幂等


def test_migrate_skips_when_dst_exists(tmp_path):
    """目标已有该项目目录 → 不覆盖，legacy 保留。"""
    legacy = tmp_path / "legacy"
    new = tmp_path / "new"
    save_review(legacy, project="p", model="m", files_reviewed=0, findings=[])
    save_review(new, project="p", model="m", files_reviewed=0, findings=[])
    assert migrate_legacy_reviews(legacy, new, "p") is False
    assert (legacy / "p").is_dir()


def test_migrate_missing_src(tmp_path):
    """legacy 无该项目目录 → False。"""
    assert migrate_legacy_reviews(tmp_path / "legacy", tmp_path / "new", "p") is False


def test_migrate_same_dir_guard(tmp_path):
    """src == dst（如 env 把 reviews 指回 data/reviews）→ False 不自残。"""
    base = tmp_path / "reviews"
    save_review(base, project="p", model="m", files_reviewed=0, findings=[])
    assert migrate_legacy_reviews(base, base, "p") is False
    assert (base / "p").is_dir()


# ====================================================================
# 3 · 端点级：项目资产落盘 + legacy 迁移
# ====================================================================

def test_review_saves_into_project_asset(client_no_env, repo, fake_llm):
    """无 env：评审记录落 {root}/.flipped/reviews/<name>/，端点回 review_id。"""
    (repo / "tracked.txt").write_text("v2\n")  # 制造 dirty worktree
    r = client_no_env.post("/api/v1/project/review", json={})
    assert r.status_code == 200, r.text
    rid = r.json().get("review_id")
    assert rid, "落盘成功应回 review_id"
    f = repo / ".flipped" / "reviews" / "repo" / f"{rid}.json"
    assert f.is_file(), "评审记录应落在项目 .flipped/reviews 资产位置"
    rec = json.loads(f.read_text(encoding="utf-8"))
    assert rec["project"] == "repo" and rec["id"] == rid


def test_reviews_list_triggers_legacy_migration(client_no_env, repo, fake_llm,
                                                monkeypatch, tmp_path):
    """预置 legacy data/reviews/<name>/ → GET 列表触发迁移：旧记录可见且 legacy 消失。"""
    monkeypatch.chdir(tmp_path)  # legacy "data/reviews" 相对路径隔离到 tmp
    legacy = tmp_path / "data" / "reviews"
    old = save_review(legacy, project="repo", model="m", files_reviewed=1, findings=[])
    r = client_no_env.get("/api/v1/project/reviews")
    assert r.status_code == 200, r.text
    ids = [e["id"] for e in r.json().get("reviews", [])]
    assert old["id"] in ids, "迁移后 legacy 记录应在新位置可见"
    assert not (legacy / "repo").exists(), "legacy 目录应已 move 走"
    # 详情也从新位置读得到
    r2 = client_no_env.get(f"/api/v1/project/reviews/{old['id']}")
    assert r2.status_code == 200 and r2.json()["id"] == old["id"]


def test_env_override_skips_migration(client_no_env, repo, fake_llm,
                                      monkeypatch, tmp_path):
    """env 显式覆盖 → 不迁移 legacy，落盘走 env 路径（隔离语义不动）。"""
    monkeypatch.chdir(tmp_path)
    iso = tmp_path / "iso"
    monkeypatch.setenv("FLIPPED_REVIEWS_DIR", str(iso))
    legacy = tmp_path / "data" / "reviews"
    save_review(legacy, project="repo", model="m", files_reviewed=1, findings=[])
    (repo / "tracked.txt").write_text("v2\n")
    r = client_no_env.post("/api/v1/project/review", json={})
    assert r.status_code == 200, r.text
    rid = r.json().get("review_id")
    assert (iso / "repo" / f"{rid}.json").is_file(), "env 路径落盘"
    assert (legacy / "repo").is_dir(), "env 覆盖时 legacy 不动"
    assert not (repo / ".flipped" / "reviews").exists(), "env 覆盖时不写项目资产位"


# ====================================================================
# 4 · RAG_EMBEDDING=mock 开关（M196.3 hermetic）
# ====================================================================

def test_rag_embedding_mock_short_circuits(monkeypatch):
    """RAG_EMBEDDING=mock → 直接 MockEmbedding，绝不实例化 SentenceTransformerEmbeddings。"""
    import rag.embeddings as emb

    def _boom(*a, **kw):
        raise AssertionError("RAG_EMBEDDING=mock 时不应实例化 ST")

    monkeypatch.setenv("RAG_EMBEDDING", "mock")
    monkeypatch.setattr(emb, "SentenceTransformerEmbeddings", _boom)
    m = _default_embedding()
    assert isinstance(m, MockEmbedding)


def test_rag_embedding_env_case_insensitive(monkeypatch):
    """大小写/空白容忍：' Mock ' 同样生效。"""
    monkeypatch.setenv("RAG_EMBEDDING", " Mock ")
    assert isinstance(_default_embedding(), MockEmbedding)


# ====================================================================
# 5 · _git_snapshot racy index 自愈（M196 黑盒抓到的真 bug 修复）
# ====================================================================
#
# 背景：verify_m196 场景 a 首轮 agent 消息 snapshot 事件缺失。根因——
# project_open 用 shutil.copytree 拷外部项目进 ~/projects，拷贝来的 repo
# index stat 缓存与文件实际不匹配（racy index），首次 `git stash create`
# rc=1 空 stderr 假失败 → snapshot=None → undo 地基缺失。修复：rc!=0 时先
# `git update-index -q --refresh` 再重试一次（幂等只读）。

def test_git_snapshot_copied_repo_self_heals(tmp_path):
    """行为级：copytree 拷来的 repo（racy index）首次 _git_snapshot 即返回 HEAD。"""
    from api.assistant import _git_head, _git_snapshot
    src = tmp_path / "src"
    src.mkdir()
    _git(src, "init")
    _git(src, "config", "user.email", "t@example.com")
    _git(src, "config", "user.name", "t")
    (src / "f.txt").write_text("v1\n")
    _git(src, "add", ".")
    _git(src, "commit", "-m", "init")
    dst = tmp_path / "dst"
    shutil.copytree(src, dst)
    snap = _git_snapshot(dst)
    assert snap is not None, "拷贝来的 repo 首次快照不应失败（racy index 应自愈）"
    assert snap == _git_head(dst), "干净工作区应回退 HEAD hash"


def test_git_snapshot_retries_after_index_refresh(monkeypatch, repo):
    """机制级：首次 stash create rc=1 → 先 update-index --refresh 再重试成功。"""
    from api import assistant
    real_run = subprocess.run
    calls: list[list[str]] = []

    def _fake_run(cmd, **kw):
        calls.append(list(cmd))
        if cmd[1:3] == ["stash", "create"] and \
                sum(1 for c in calls if c[1:3] == ["stash", "create"]) == 1:
            return subprocess.CompletedProcess(cmd, 1, "", "")  # 模拟 racy 假失败
        return real_run(cmd, **kw)

    monkeypatch.setattr(assistant.subprocess, "run", _fake_run)
    snap = assistant._git_snapshot(repo)
    assert snap is not None
    assert any(c[1:3] == ["update-index", "-q"] for c in calls), \
        "失败后应先刷新 index 再重试"
    assert sum(1 for c in calls if c[1:3] == ["stash", "create"]) == 2


def test_git_snapshot_non_repo_stays_none(tmp_path):
    """边界：非 git 目录重试后仍 None（重试不改变失败语义，不误判为可用快照）。"""
    from api.assistant import _git_snapshot
    assert _git_snapshot(tmp_path) is None
