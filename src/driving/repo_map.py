"""仓库结构地图 / 仓库记忆(F5 · Qoder wiki / Cursor 索引式,轻量确定性版)。

自主循环拆解时,Supervisor 若知道项目的技术栈与目录结构,拆出的子任务更贴合项目实际
(不重造轮子、把代码放对位置)。本模块把活动项目压成一段紧凑的结构概览喂给 Supervisor。

为何选结构地图而非语义 RAG:Supervisor 需要的是**布局感知**(项目长什么样),不是语义
检索;语义检索对 Worker 找相关代码更有用,而 Worker 是 OpenHands 已能在沙盒里直接探索
文件系统。结构地图确定性、无 embedding 依赖、始终可用。纯函数、有大小上限。
(未来可选:给 Worker 加语义 RAG 逐子任务检索,非本增量所需。)
"""
from __future__ import annotations

from pathlib import Path

_IGNORE = {
    ".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build",
    ".pytest_cache", ".mypy_cache", ".ruff_cache", "chroma", ".next", "target",
    ".idea", ".vscode", ".DS_Store", "coverage", ".turbo", ".sessions.json",
}

# manifest 文件 → 技术栈标签(按序探测)
_STACK = [
    ("pyproject.toml", "Python"),
    ("requirements.txt", "Python"),
    ("setup.py", "Python"),
    ("package.json", "Node/JS"),
    ("tsconfig.json", "TypeScript"),
    ("Cargo.toml", "Rust"),
    ("go.mod", "Go"),
    ("pom.xml", "Java (Maven)"),
    ("build.gradle", "Java/Kotlin (Gradle)"),
    ("Gemfile", "Ruby"),
    ("composer.json", "PHP"),
    ("Dockerfile", "Docker"),
    ("docker-compose.yml", "Docker Compose"),
]
_KEY_FILES = [
    "README.md", "Makefile", "pyproject.toml", "package.json", "Cargo.toml",
    "go.mod", "Dockerfile", "docker-compose.yml", "tsconfig.json", "requirements.txt",
]

_MAX_TOP = 30
_MAX_DIR_CHILDREN = 8
_MAX_DIRS_EXPANDED = 6
_TOTAL_CAP = 2500


def _detect_stack(root: Path) -> list[str]:
    seen: list[str] = []
    for fname, label in _STACK:
        if (root / fname).is_file() and label not in seen:
            seen.append(label)
    return seen


def _children(d: Path) -> list[Path]:
    try:
        items = [p for p in d.iterdir()
                 if p.name not in _IGNORE and not p.name.startswith(".")]
    except OSError:
        return []
    # 目录在前,再按名字排序
    return sorted(items, key=lambda p: (p.is_file(), p.name.lower()))


def build_repo_map(root: Path | None) -> str:
    """把项目根压成紧凑结构概览(技术栈/顶层目录/关键文件/主目录二级布局)。无则空串。"""
    if root is None or not root.is_dir():
        return ""
    lines: list[str] = []

    stack = _detect_stack(root)
    if stack:
        lines.append("技术栈：" + "、".join(stack))

    top = _children(root)[:_MAX_TOP]
    top_dirs = [p for p in top if p.is_dir()]
    key_files = [p.name for p in top if p.is_file() and p.name in _KEY_FILES]

    if top_dirs:
        lines.append("顶层目录：" + "、".join(p.name + "/" for p in top_dirs))
    if key_files:
        lines.append("关键文件：" + "、".join(key_files))

    for d in top_dirs[:_MAX_DIRS_EXPANDED]:
        kids = _children(d)[:_MAX_DIR_CHILDREN]
        if kids:
            names = "、".join(k.name + ("/" if k.is_dir() else "") for k in kids)
            lines.append(f"{d.name}/ 下：{names}")

    return "\n".join(lines)[:_TOTAL_CAP]
