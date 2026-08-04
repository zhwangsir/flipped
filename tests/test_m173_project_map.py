"""M173 A 队 · 确定性项目地图（project_map）TDD 测试。

契约要点：
- build_project_map：纯确定性扫描，markdown 分节（技术栈/目录布局/依赖清单/入口与关键文件/README 摘要/代码统计），
  空节省略、单节异常跳过、max_chars 从末尾整节丢弃；root 无效 → 零值 ProjectMap。
- get_project_map：缓存命中 from_cache=True；重新扫 source_mtime 比缓存新 → stale=True（不自动重建）；
  缓存缺失/损坏 → 现建并写缓存。
- regenerate_project_map：强制重建 + 刷缓存，stale=False, from_cache=False。
- 全部测试用 tmp_path，缓存一律走 tmp_path / monkeypatch env，绝不污染真实 data/。
"""
from __future__ import annotations

import json
import os
import time

import pytest

from api.project_map import (
    MAP_INJECT_HEADER,
    ProjectMap,
    build_project_map,
    get_project_map,
    regenerate_project_map,
)


def _write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


# ---------- build_project_map：分节 ----------

def test_empty_dir_markdown_title_only(tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    m = build_project_map(proj)
    assert m.markdown.startswith("# 项目地图：proj")
    # 空目录：除标题外各节均省略
    assert "##" not in m.markdown
    assert m.stack == []
    assert m.source_mtime == 0.0
    assert m.generated_at  # ISO8601 仍填
    assert m.stale is False and m.from_cache is False


def test_stack_detection_and_stack_field(tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    _write(proj / "pyproject.toml", "[project]\nname='x'\n")
    _write(proj / "package.json", "{}")
    _write(proj / "tsconfig.json", "{}")
    _write(proj / "requirements.txt", "fastapi\n")  # Python 去重
    _write(proj / "Dockerfile", "FROM scratch\n")
    m = build_project_map(proj)
    assert m.stack == ["Python", "Node/JS", "TypeScript", "Docker"]
    assert "## 技术栈" in m.markdown
    for name in m.stack:
        assert name in m.markdown


def test_no_dependency_files_omits_deps_section(tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    _write(proj / "main.py", "print(1)\n")
    m = build_project_map(proj)
    assert "## 依赖清单" not in m.markdown


def test_package_json_deps_with_dev_annotation(tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    deps = {f"dep{i:02d}": "^1.0.0" for i in range(15)}
    dev = {f"devdep{i:02d}": "^1.0.0" for i in range(10)}
    _write(proj / "package.json", json.dumps({"dependencies": deps, "devDependencies": dev}))
    m = build_project_map(proj)
    assert "## 依赖清单" in m.markdown
    assert "- dep00\n" in m.markdown
    assert "- devdep00 (dev)" in m.markdown
    # dependencies+devDependencies 合计 top 20：15 deps + 前 5 个 devDeps
    assert "devdep04" in m.markdown
    assert "devdep05" not in m.markdown


def test_pyproject_dependencies_parsed(tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    _write(
        proj / "pyproject.toml",
        '[project]\nname = "x"\ndependencies = ["fastapi>=0.100", "uvicorn"]\n',
    )
    m = build_project_map(proj)
    assert "## 依赖清单" in m.markdown
    assert "fastapi>=0.100" in m.markdown
    assert "uvicorn" in m.markdown


def test_requirements_txt_first_20_lines_skip_comments(tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    lines = ["# 注释", "", "pkg00"] + [f"pkg{i:02d}" for i in range(1, 25)]
    _write(proj / "requirements.txt", "\n".join(lines) + "\n")
    m = build_project_map(proj)
    assert "- pkg00" in m.markdown
    assert "- pkg19" in m.markdown  # 第 20 行有效条目在内
    assert "pkg20" not in m.markdown  # 超出前 20
    assert "# 注释" not in m.markdown


def test_readme_summary_extraction_skips_title_and_badges(tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    _write(
        proj / "README.md",
        "# My Project\n\n[![ci](https://shields.io/badge.svg)](x)\n![img](logo.png)\n\n"
        "This is the real summary paragraph.\nMore of the same paragraph.\n\n"
        "Second paragraph must not be picked.\n",
    )
    m = build_project_map(proj)
    assert "## README 摘要" in m.markdown
    assert "This is the real summary paragraph." in m.markdown
    assert "More of the same paragraph." in m.markdown  # 同段落合并
    assert "Second paragraph" not in m.markdown
    assert "shields.io" not in m.markdown
    assert "My Project" not in m.markdown.split("## README 摘要")[1]


def test_readme_summary_truncated_to_300_chars(tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    _write(proj / "readme.md", "word " * 200 + "\n")  # 1000 字符单段，小写文件名探测
    m = build_project_map(proj)
    summary = m.markdown.split("## README 摘要\n")[1].split("\n\n")[0]  # 只取本节内容
    assert len(summary.strip()) <= 301  # 300 + 可能的截断省略号
    assert "…" in summary or summary.strip().endswith("word")


def test_code_stats_top8_ignores_noise_dirs(tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    for i in range(3):
        _write(proj / "src" / f"a{i}.py", "")
    for i in range(2):
        _write(proj / "src" / f"b{i}.ts", "")
    _write(proj / "README.md", "hi\n")
    _write(proj / "node_modules" / "dep" / "ignored.py", "")  # 忽略目录不计
    _write(proj / ".git" / "ignored.js", "")
    m = build_project_map(proj)
    assert "## 代码统计" in m.markdown
    stats_line = m.markdown.split("## 代码统计")[1].strip().splitlines()[0]
    assert ".py 3" in stats_line  # node_modules/.git 里的不计
    assert ".ts 2" in stats_line
    assert "·" in stats_line  # 分隔格式 `.py 3 · .ts 2`


def test_max_chars_drops_tail_sections_wholesale(tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    _write(proj / "package.json", json.dumps({"dependencies": {"react": "^18"}}))
    _write(proj / "README.md", "# T\n\nsummary text\n")
    _write(proj / "main.py", "")
    _write(proj / "src" / "x.py", "")
    full = build_project_map(proj)
    assert "## 代码统计" in full.markdown
    max_chars = len(full.markdown) - 5  # 仅少 5 字符 → 末节（代码统计）整节丢弃
    m = build_project_map(proj, max_chars=max_chars)
    assert len(m.markdown) <= max_chars
    assert m.markdown.startswith("# 项目地图：proj")  # 标题保留
    assert "## 技术栈" in m.markdown  # 技术栈保留
    assert "## 代码统计" not in m.markdown  # 末节整节丢弃，而非半截截断


def test_dir_purpose_heuristics_and_unknown_dir_children(tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    for d in ("src", "tests", "docs", "scripts"):
        (proj / d).mkdir()
    _write(proj / "foobar" / "alpha" / ".keep", "")
    _write(proj / "foobar" / "beta" / ".keep", "")
    (proj / ".hidden").mkdir()  # 点开头目录忽略
    (proj / "__pycache__").mkdir()  # 忽略目录
    m = build_project_map(proj)
    assert "- src/ — 源码" in m.markdown
    assert "- tests/ — 测试" in m.markdown
    assert "- docs/ — 文档" in m.markdown
    assert "foobar/（含 alpha、beta）" in m.markdown  # 未知目录列子项，不瞎编用途
    assert ".hidden" not in m.markdown
    assert "__pycache__" not in m.markdown


def test_entry_files_detected(tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    _write(proj / "main.py", "")
    _write(proj / "AGENTS.md", "")
    m = build_project_map(proj)
    assert "## 入口与关键文件" in m.markdown
    assert "- main.py" in m.markdown
    assert "- AGENTS.md" in m.markdown
    assert "- manage.py" not in m.markdown  # 不存在的不列


# ---------- root 无效 → 零值 ----------

@pytest.mark.parametrize("kind", ["missing", "file", "none"])
def test_invalid_root_returns_zero_value(tmp_path, kind):
    if kind == "missing":
        root = tmp_path / "nope"
    elif kind == "file":
        root = _write(tmp_path / "afile.txt", "x")
    else:
        root = None
    m = build_project_map(root)
    assert m.markdown == ""
    assert m.source_mtime == 0.0
    assert m.stack == []
    assert m.generated_at  # 仍填当前时间
    # get/regenerate 对无效 root 同样零值且不写缓存
    cache_dir = tmp_path / "cache"
    g = get_project_map(root, cache_dir=cache_dir)
    assert g.markdown == "" and g.from_cache is False and g.stale is False
    assert not cache_dir.exists() or not list(cache_dir.iterdir())


# ---------- 缓存：get / stale / regenerate ----------

def test_get_cache_hit_from_cache(tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    _write(proj / "main.py", "")
    cache_dir = tmp_path / "cache"
    first = get_project_map(proj, cache_dir=cache_dir)
    assert first.from_cache is False and first.stale is False
    assert (cache_dir / "proj.md").exists()
    assert (cache_dir / "proj.json").exists()
    meta = json.loads((cache_dir / "proj.json").read_text(encoding="utf-8"))
    assert meta["source_mtime"] == first.source_mtime
    assert meta["stack"] == first.stack
    assert meta["generated_at"] == first.generated_at
    second = get_project_map(proj, cache_dir=cache_dir)
    assert second.from_cache is True
    assert second.stale is False
    assert second.markdown == first.markdown
    assert second.source_mtime == first.source_mtime


def test_get_cache_dir_from_env(tmp_path, monkeypatch):
    proj = tmp_path / "proj"
    proj.mkdir()
    _write(proj / "main.py", "")
    monkeypatch.setenv("FLIPPED_MAP_CACHE_DIR", str(tmp_path / "envcache"))
    m = get_project_map(proj)
    assert (tmp_path / "envcache" / "proj.md").exists()
    assert m.from_cache is False


def test_stale_detection_after_project_update(tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    f = _write(proj / "main.py", "")
    cache_dir = tmp_path / "cache"
    first = get_project_map(proj, cache_dir=cache_dir)
    assert first.stale is False
    # 项目文件 mtime 调新 → 再 get 应 stale=True 且不自动重建
    new_t = first.source_mtime + 10
    os.utime(f, (new_t, new_t))
    second = get_project_map(proj, cache_dir=cache_dir)
    assert second.from_cache is True
    assert second.stale is True
    assert second.markdown == first.markdown  # 仍是旧缓存内容


def test_regenerate_refreshes_cache_and_clears_stale(tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    f = _write(proj / "package.json", json.dumps({"dependencies": {"react": "^18"}}))
    cache_dir = tmp_path / "cache"
    first = get_project_map(proj, cache_dir=cache_dir)
    assert "vue" not in first.markdown
    time.sleep(0.01)
    _write(proj / "package.json", json.dumps({"dependencies": {"react": "^18", "vue": "^3"}}))
    new_t = first.source_mtime + 10
    os.utime(f, (new_t, new_t))
    regen = regenerate_project_map(proj, cache_dir=cache_dir)
    assert regen.stale is False and regen.from_cache is False
    assert "vue" in regen.markdown  # 内容已重建
    assert regen.source_mtime >= new_t
    # 缓存已刷新：再 get 命中且不再 stale
    cached = (cache_dir / "proj.md").read_text(encoding="utf-8")
    assert cached == regen.markdown
    again = get_project_map(proj, cache_dir=cache_dir)
    assert again.from_cache is True and again.stale is False
    assert "vue" in again.markdown


def test_corrupt_cache_treated_as_missing(tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    _write(proj / "main.py", "")
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    _write(cache_dir / "proj.md", "stale content")
    _write(cache_dir / "proj.json", "{not valid json")  # meta 损坏
    m = get_project_map(proj, cache_dir=cache_dir)
    assert m.from_cache is False
    assert "## 入口与关键文件" in m.markdown  # 现建内容，非损坏缓存
    meta = json.loads((cache_dir / "proj.json").read_text(encoding="utf-8"))  # 缓存已重写为合法
    assert meta["source_mtime"] == m.source_mtime


# ---------- 健壮性 ----------

def test_section_exception_skipped_not_fatal(tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "package.json").write_bytes(b'\xff\xfe{bad json')  # 坏编码 + 坏 JSON
    _write(proj / "README.md", "# T\n\nreal summary here\n")
    _write(proj / "main.py", "")
    m = build_project_map(proj)
    # package.json 解析失败只跳过其依赖小节，整体不炸
    assert "## 依赖清单" not in m.markdown
    assert "Node/JS" in m.markdown  # 技术栈按存在性探测，仍在
    assert "## README 摘要" in m.markdown
    assert "real summary here" in m.markdown
    assert "## 入口与关键文件" in m.markdown


def test_map_inject_header_importable():
    assert MAP_INJECT_HEADER == "以下是用户项目的结构地图（全局概览）："
    assert isinstance(MAP_INJECT_HEADER, str)


def test_project_map_dataclass_defaults():
    m = ProjectMap(markdown="x", generated_at="t", source_mtime=1.0)
    assert m.stack == [] and m.stale is False and m.from_cache is False
