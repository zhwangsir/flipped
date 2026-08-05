"""M189.2 · 项目地图 git 指纹深层变更感知 TDD 测试。

契约要点：
- _git_fingerprint：非 git 目录 / git 不可用 / 超时 / 任何异常 → None；
  git repo（含无 commit）→ sha256(HEAD + "\\0" + porcelain)[:16] 稳定指纹；
  porcelain 用 --untracked-files=all，深层 untracked 新文件也可感知。
- get_project_map 缓存命中分支：git 项目且缓存带指纹 → 指纹比对判 stale
  （深层内容编辑 / untracked 新文件 / commit 全感知）；非 git 或指纹缺失 →
  回退顶层 mtime 判定（保持 M173 现状语义）。
- 旧缓存（无 source_fingerprint 键）不炸，回退 mtime 判定。
- 测试一律用 tmp_path 造项目目录 + cache_dir 参数隔离缓存，绝不污染真实 data/。
"""
from __future__ import annotations

import json
import subprocess

from api.project_map import (
    _git_fingerprint,
    get_project_map,
    regenerate_project_map,
)


def _write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _git(root, *args):
    """在项目目录内执行 git 命令；commit 用 -c 注入身份避免全局配置依赖。"""
    return subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        text=True,
        timeout=10,
    )


def _git_init_repo(root):
    """git init + 空初始 commit，返回 repo 根。"""
    root.mkdir(parents=True, exist_ok=True)
    r = subprocess.run(
        ["git", "init"], cwd=root, capture_output=True, text=True, timeout=10
    )
    assert r.returncode == 0
    return root


def _git_commit_all(root, message="x"):
    _git(root, "add", "-A")
    r = _git(root, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-m", message)
    assert r.returncode == 0


# ---------- _git_fingerprint 纯逻辑 ----------

def test_fingerprint_none_for_non_git_dir(tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    _write(proj / "main.py", "")
    assert _git_fingerprint(proj) is None


def test_fingerprint_non_none_for_repo_without_commit(tmp_path):
    proj = _git_init_repo(tmp_path / "proj")
    fp = _git_fingerprint(proj)
    assert fp is not None  # 无 commit：HEAD 用空串，仍出指纹
    assert isinstance(fp, str) and len(fp) == 16


def test_fingerprint_stable_for_same_state(tmp_path):
    proj = _git_init_repo(tmp_path / "proj")
    _write(proj / "main.py", "print(1)\n")
    _git_commit_all(proj)
    fp1 = _git_fingerprint(proj)
    fp2 = _git_fingerprint(proj)
    assert fp1 is not None and fp1 == fp2


def test_fingerprint_changes_after_content_edit(tmp_path):
    proj = _git_init_repo(tmp_path / "proj")
    f = _write(proj / "src" / "a" / "b.py", "v1\n")
    _git_commit_all(proj)
    fp1 = _git_fingerprint(proj)
    _write(f, "v2\n")  # 深层文件内容编辑
    fp2 = _git_fingerprint(proj)
    assert fp1 is not None and fp2 is not None and fp1 != fp2


# ---------- get_project_map：git 项目 stale 感知 ----------

def test_stale_after_deep_content_edit_in_git_repo(tmp_path):
    proj = _git_init_repo(tmp_path / "proj")
    f = _write(proj / "src" / "a" / "b.py", "v1\n")
    _git_commit_all(proj)
    cache_dir = tmp_path / "cache"
    first = get_project_map(proj, cache_dir=cache_dir)
    assert first.from_cache is False and first.stale is False
    assert first.source_fingerprint  # 指纹已生成
    # 深层文件内容编辑：顶层 mtime 不冒泡，但指纹必须感知
    _write(f, "v2\n")
    second = get_project_map(proj, cache_dir=cache_dir)
    assert second.from_cache is True
    assert second.stale is True
    assert second.markdown == first.markdown  # 仍是旧缓存内容，不自动重建


def test_no_change_not_stale(tmp_path):
    proj = _git_init_repo(tmp_path / "proj")
    _write(proj / "src" / "a" / "b.py", "v1\n")
    _git_commit_all(proj)
    cache_dir = tmp_path / "cache"
    get_project_map(proj, cache_dir=cache_dir)
    second = get_project_map(proj, cache_dir=cache_dir)
    assert second.from_cache is True
    assert second.stale is False


def test_stale_after_deep_untracked_new_file(tmp_path):
    proj = _git_init_repo(tmp_path / "proj")
    _write(proj / "src" / "a" / "b.py", "v1\n")
    _git_commit_all(proj)
    cache_dir = tmp_path / "cache"
    get_project_map(proj, cache_dir=cache_dir)
    _write(proj / "src" / "a" / "deep" / "c.py", "new\n")  # 深层 untracked 新文件
    second = get_project_map(proj, cache_dir=cache_dir)
    assert second.from_cache is True
    assert second.stale is True


def test_stale_after_commit(tmp_path):
    proj = _git_init_repo(tmp_path / "proj")
    f = _write(proj / "src" / "a" / "b.py", "v1\n")
    _git_commit_all(proj, "init")
    cache_dir = tmp_path / "cache"
    get_project_map(proj, cache_dir=cache_dir)
    _write(f, "v2\n")
    _git_commit_all(proj, "update")  # HEAD 变化
    second = get_project_map(proj, cache_dir=cache_dir)
    assert second.from_cache is True
    assert second.stale is True


# ---------- 回退路径与兼容 ----------

def test_non_git_dir_falls_back_to_mtime_semantics(tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    f = _write(proj / "src" / "a" / "b.py", "v1\n")
    cache_dir = tmp_path / "cache"
    first = get_project_map(proj, cache_dir=cache_dir)
    assert first.from_cache is False
    assert first.source_fingerprint == ""  # 非 git：无指纹
    # 深层编辑顶层 mtime 不变 → stale=False（保持 M173 现状语义），且不炸
    _write(f, "v2\n")
    second = get_project_map(proj, cache_dir=cache_dir)
    assert second.from_cache is True
    assert second.stale is False


def test_legacy_cache_without_fingerprint_key(tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    _write(proj / "main.py", "")
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    _write(cache_dir / "proj.md", "# 旧缓存\n")
    # 手写一份无 source_fingerprint 键的旧版 meta
    meta = {"generated_at": "t", "source_mtime": 9999999999.0, "stack": ["Python"]}
    _write(cache_dir / "proj.json", json.dumps(meta))
    m = get_project_map(proj, cache_dir=cache_dir)
    assert m.from_cache is True
    assert m.source_fingerprint == ""
    assert m.stale is False  # mtime 远未来 → 不 stale；关键是不炸


def test_regenerate_persists_new_fingerprint(tmp_path):
    proj = _git_init_repo(tmp_path / "proj")
    f = _write(proj / "src" / "a" / "b.py", "v1\n")
    _git_commit_all(proj, "init")
    cache_dir = tmp_path / "cache"
    get_project_map(proj, cache_dir=cache_dir)
    _write(f, "v2\n")
    regen = regenerate_project_map(proj, cache_dir=cache_dir)
    assert regen.stale is False and regen.from_cache is False
    assert regen.source_fingerprint
    # 新指纹已落盘
    meta = json.loads((cache_dir / "proj.json").read_text(encoding="utf-8"))
    assert meta["source_fingerprint"] == regen.source_fingerprint
    # 再 get：指纹一致 → 不再 stale
    again = get_project_map(proj, cache_dir=cache_dir)
    assert again.from_cache is True
    assert again.stale is False
