"""M173 · 确定性项目地图（对标 ZCode Zread）：零 LLM / 零 embedding / 零新依赖。

纯文件系统扫描生成项目结构概览 markdown，供 B 队注入 system/context。
- build_project_map：现场扫描；分节渲染，空节省略，单节异常跳过不炸；
  总长超 max_chars 时从末尾整节丢弃（标题与技术栈尽量保留）。
- get_project_map：缓存命中直接返回（from_cache=True），并重扫 source_mtime
  判定 stale（项目更新不自动重建）；缓存缺失/损坏 → 现建并写缓存。
- regenerate_project_map：强制重建并刷新缓存。
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tomllib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

MAP_INJECT_HEADER = "以下是用户项目的结构地图（全局概览）："  # B 队注入用

DEFAULT_MAX_CHARS = 4000
_MAX_DIRS = 15
_MAX_DEPS = 20
_MAX_STATS = 8
_MAX_README_CHARS = 300

# 目录布局 / 代码统计统一忽略的噪声名（点开头的目录另行整体忽略）
IGNORED_NAMES = {
    ".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build",
    ".pytest_cache", "chroma", ".next", "target", ".idea", ".vscode",
    ".DS_Store", "coverage",
}

# 常见目录名 → 一句话用途（未知目录不瞎编，改列其子项）
DIR_PURPOSES = {
    "src": "源码", "tests": "测试", "test": "测试", "docs": "文档",
    "scripts": "脚本", "public": "静态资源", "assets": "资源", "config": "配置",
    "components": "组件", "api": "接口", "server": "服务端", "client": "客户端",
    "console": "前端台", "app": "应用", "lib": "库", "utils": "工具",
    "infra": "基础设施", "data": "数据",
}

# manifest → 技术栈标签（按此顺序探测，去重）
STACK_MANIFESTS = [
    (("pyproject.toml", "requirements.txt", "setup.py"), "Python"),
    (("package.json",), "Node/JS"),
    (("tsconfig.json",), "TypeScript"),
    (("Cargo.toml",), "Rust"),
    (("go.mod",), "Go"),
    (("pom.xml",), "Java (Maven)"),
    (("build.gradle",), "Java/Kotlin (Gradle)"),
    (("Gemfile",), "Ruby"),
    (("composer.json",), "PHP"),
    (("Dockerfile",), "Docker"),
    (("docker-compose.yml",), "Docker Compose"),
]

ENTRY_FILES = [
    "main.py", "app.py", "manage.py", "index.ts", "index.js", "main.ts",
    "Makefile", "Dockerfile", "docker-compose.yml", "AGENTS.md", "README.md",
    "CLAUDE.md",
]


@dataclass
class ProjectMap:
    markdown: str            # 渲染好的地图文档（≤ max_chars）
    generated_at: str        # ISO8601 UTC
    source_mtime: float      # 扫描时受监控文件最新 mtime（stale 判定基准）
    stack: list[str] = field(default_factory=list)
    stale: bool = False
    from_cache: bool = False
    source_fingerprint: str = ""  # M189.2：git 内容指纹（旧缓存无此键 → "" 回退 mtime 判定）


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_valid_root(root: Path | None) -> bool:
    try:
        return root is not None and Path(root).is_dir()
    except (OSError, ValueError):
        return False


def _zero_map() -> ProjectMap:
    return ProjectMap(markdown="", generated_at=_now_iso(), source_mtime=0.0)


def _iter_top_dirs(root: Path) -> list[Path]:
    dirs = []
    for entry in sorted(root.iterdir(), key=lambda p: p.name):
        if not entry.is_dir():
            continue
        if entry.name in IGNORED_NAMES or entry.name.startswith("."):
            continue
        dirs.append(entry)
    return dirs


def _scan_source_mtime(root: Path) -> float:
    """受监控对象 = 顶层文件（manifest、README 等）+ 顶层目录的最新 mtime；扫不到 → 0.0。

    顶层目录 mtime 在其直接子项增删时更新，可捕捉目录布局变化（地图的"目录布局"
    与"代码统计"分节依赖它）；深层文件内容编辑不触发（重建成本高，留给手动 regenerate）。
    """
    latest = 0.0
    try:
        for entry in root.iterdir():
            try:
                if entry.name in IGNORED_NAMES:
                    continue
                if entry.is_file() or entry.is_dir():
                    latest = max(latest, entry.stat().st_mtime)
            except OSError:
                continue
    except OSError:
        return 0.0
    return latest


def _git_fingerprint(root: Path) -> str | None:
    """M189.2 · 项目内容 git 指纹：HEAD + porcelain 全量状态的哈希。

    非 git repo / git 不可用 / 超时(5s) / 任何异常 → None（调用方回退 mtime 判定）。
    porcelain 用 --untracked-files=all：深层 untracked 新文件也可感知。

    M197.3（消化 L-M189-1）：未 ignore 的巨大 untracked 目录会拖慢
    `--untracked-files=all` 的 status——首试超时（TimeoutExpired）后降级
    `--untracked-files=normal` 重试一次（仍感知顶层新目录，深层文件感知降级），
    再超时 → None。env FLIPPED_FP_UNTRACKED=all|normal 显式指定首试模式。
    """
    try:
        probe = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--is-inside-work-tree"],
            capture_output=True, text=True, timeout=5,
        )
        if probe.returncode != 0 or probe.stdout.strip() != "true":
            return None
        head = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=5,
        )
        # 无 commit 的 repo returncode!=0 → HEAD 用空串，不算失败
        head_sha = head.stdout.strip() if head.returncode == 0 else ""
        untracked = os.environ.get("FLIPPED_FP_UNTRACKED", "all").strip().lower()
        if untracked not in ("all", "normal"):
            untracked = "all"
        status = _porcelain_status(root, untracked)
        if status is None and untracked == "all":  # 超时/失败 → normal 降级重试一次
            status = _porcelain_status(root, "normal")
        if status is None:
            return None
        return hashlib.sha256(
            (head_sha + "\0" + status).encode()
        ).hexdigest()[:16]
    except Exception:
        return None


def _porcelain_status(root: Path, untracked: str) -> str | None:
    """`git status --porcelain=v1 --untracked-files=<mode>` stdout；rc!=0/超时/异常 → None。"""
    try:
        out = subprocess.run(
            ["git", "-C", str(root), "status", "--porcelain=v1",
             f"--untracked-files={untracked}"],
            capture_output=True, text=True, timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout if out.returncode == 0 else None


# ---------- 各分节（独立容错，返回 "" 表示省略） ----------

def _detect_stack(root: Path) -> list[str]:
    stack: list[str] = []
    for names, label in STACK_MANIFESTS:
        if label not in stack and any((root / n).exists() for n in names):
            stack.append(label)
    return stack


def _stack_section(stack: list[str]) -> str:
    if not stack:
        return ""
    return "## 技术栈\n" + "\n".join(f"- {s}" for s in stack)


def _layout_section(root: Path) -> str:
    lines = []
    for d in _iter_top_dirs(root)[:_MAX_DIRS]:
        purpose = DIR_PURPOSES.get(d.name.lower())
        if purpose:
            lines.append(f"- {d.name}/ — {purpose}")
            continue
        # 未知目录：列其顶层子项名前几个，不瞎编用途
        try:
            children = [
                c.name for c in sorted(d.iterdir(), key=lambda p: p.name)
                if c.name not in IGNORED_NAMES and not c.name.startswith(".")
            ]
        except OSError:
            children = []
        if children:
            shown = "、".join(children[:3]) + (" 等" if len(children) > 3 else "")
            lines.append(f"- {d.name}/（含 {shown}）")
        else:
            lines.append(f"- {d.name}/")
    if not lines:
        return ""
    return "## 目录布局\n" + "\n".join(lines)


def _package_json_deps(root: Path) -> list[str]:
    data = json.loads((root / "package.json").read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return []
    deps = [f"- {n}" for n in (data.get("dependencies") or {})]
    devs = [f"- {n} (dev)" for n in (data.get("devDependencies") or {})]
    items = (deps + devs)[:_MAX_DEPS]
    if not items:
        return []
    return ["**package.json**:", *items]


def _pyproject_deps(root: Path) -> list[str]:
    with open(root / "pyproject.toml", "rb") as fh:
        data = tomllib.load(fh)
    deps = (data.get("project") or {}).get("dependencies") or []
    if not deps:
        return []
    return ["**pyproject.toml**:", *[f"- {d}" for d in deps]]


def _requirements_deps(root: Path) -> list[str]:
    lines = []
    for raw in (root / "requirements.txt").read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#"):
            lines.append(f"- {line}")
        if len(lines) >= _MAX_DEPS:
            break
    if not lines:
        return []
    return ["**requirements.txt**:", *lines]


def _deps_section(root: Path) -> str:
    blocks: list[str] = []
    for fname, parser in (
        ("package.json", _package_json_deps),
        ("pyproject.toml", _pyproject_deps),
        ("requirements.txt", _requirements_deps),
    ):
        if not (root / fname).exists():
            continue
        try:
            block = parser(root)
        except Exception:  # 单文件解析失败（坏 JSON/坏 TOML/坏编码）只跳过该小节
            continue
        if block:
            blocks.append("\n".join(block))
    if not blocks:
        return ""
    return "## 依赖清单\n" + "\n\n".join(blocks)


def _entry_section(root: Path) -> str:
    found = [f"- {n}" for n in ENTRY_FILES if (root / n).exists()]
    if not found:
        return ""
    return "## 入口与关键文件\n" + "\n".join(found)


def _find_readme(root: Path) -> Path | None:
    try:
        for entry in sorted(root.iterdir(), key=lambda p: p.name):
            if entry.is_file() and entry.name.lower() in ("readme.md", "readme"):
                return entry
    except OSError:
        pass
    return None


def _readme_section(root: Path) -> str:
    readme = _find_readme(root)
    if readme is None:
        return ""
    text = readme.read_text(encoding="utf-8")
    para: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            if para:  # 段落结束
                break
            continue
        if line.startswith("#"):  # 标题行
            continue
        if line.startswith("![") or line.startswith("[![") or "shields.io" in line:
            continue  # badge / 图片行
        para.append(line)
    summary = " ".join(" ".join(para).split())
    if not summary:
        return ""
    if len(summary) > _MAX_README_CHARS:
        summary = summary[:_MAX_README_CHARS] + "…"
    return f"## README 摘要\n{summary}"


def _stats_section(root: Path) -> str:
    counts: dict[str, int] = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [
            d for d in dirnames
            if d not in IGNORED_NAMES and not d.startswith(".")
        ]
        for fname in filenames:
            if fname in IGNORED_NAMES:
                continue
            ext = os.path.splitext(fname)[1].lower()
            if ext:
                counts[ext] = counts.get(ext, 0) + 1
    if not counts:
        return ""
    top = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:_MAX_STATS]
    return "## 代码统计\n" + " · ".join(f"{ext} {n}" for ext, n in top)


# ---------- 对外 API ----------

def build_project_map(root: Path | None, *, max_chars: int = DEFAULT_MAX_CHARS) -> ProjectMap:
    """纯确定性扫描生成项目地图；root 无效 → 零值 ProjectMap。"""
    if not _is_valid_root(root):
        return _zero_map()
    root = Path(root).resolve()  # 规范化：'.'/相对路径也能拿到真实目录名
    title = f"# 项目地图：{root.name}"
    stack = _detect_stack(root)
    sections: list[str] = []
    for builder in (
        lambda: _stack_section(stack),
        lambda: _layout_section(root),
        lambda: _deps_section(root),
        lambda: _entry_section(root),
        lambda: _readme_section(root),
        lambda: _stats_section(root),
    ):
        try:
            section = builder()
        except Exception:  # 单节异常跳过该节，整体不炸
            continue
        if section:
            sections.append(section)
    # 拼接；超 max_chars 从末尾整节丢弃（标题/技术栈居首尽量保留）
    markdown = title
    for section in sections:
        candidate = markdown + "\n\n" + section
        if len(candidate) > max_chars:
            break
        markdown = candidate
    return ProjectMap(
        markdown=markdown,
        generated_at=_now_iso(),
        source_mtime=_scan_source_mtime(root),
        stack=stack,
        source_fingerprint=_git_fingerprint(root) or "",
    )


def _resolve_cache_dir(cache_dir: Path | None) -> Path:
    if cache_dir is not None:
        return Path(cache_dir)
    return Path(os.environ.get("FLIPPED_MAP_CACHE_DIR") or "data/project_maps")


def _write_cache(root: Path, cache_dir: Path, m: ProjectMap) -> None:
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        (cache_dir / f"{root.name}.md").write_text(m.markdown, encoding="utf-8")
        meta = {
            "generated_at": m.generated_at,
            "source_mtime": m.source_mtime,
            "stack": m.stack,
            "source_fingerprint": m.source_fingerprint,
        }
        (cache_dir / f"{root.name}.json").write_text(
            json.dumps(meta, ensure_ascii=False), encoding="utf-8"
        )
    except Exception:  # 写缓存失败静默降级为仅返回内存结果
        pass


def get_project_map(
    root: Path | None,
    *,
    max_chars: int = DEFAULT_MAX_CHARS,
    cache_dir: Path | None = None,
) -> ProjectMap:
    """缓存优先：命中 → from_cache=True 并按当前 source_mtime 判定 stale；缺失/损坏 → 现建写缓存。"""
    if not _is_valid_root(root):
        return _zero_map()
    root = Path(root).resolve()
    cdir = _resolve_cache_dir(cache_dir)
    md_path = cdir / f"{root.name}.md"
    meta_path = cdir / f"{root.name}.json"
    if md_path.exists() and meta_path.exists():
        try:
            markdown = md_path.read_text(encoding="utf-8")
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            cached = ProjectMap(
                markdown=markdown,
                generated_at=str(meta["generated_at"]),
                source_mtime=float(meta["source_mtime"]),
                stack=list(meta["stack"]),
                from_cache=True,
                source_fingerprint=str(meta.get("source_fingerprint") or ""),  # 旧缓存无此键 → ""
            )
            # M189.2：git 项目用指纹判 stale（深层内容/untracked 新文件/commit 全感知），
            # 非 git 或指纹缺失回退顶层 mtime（现状）
            fp = _git_fingerprint(root)
            if cached.source_fingerprint and fp is not None:
                cached.stale = fp != cached.source_fingerprint
            else:
                cached.stale = _scan_source_mtime(root) > cached.source_mtime
            return cached
        except Exception:  # 缓存损坏按缺失处理
            pass
    m = build_project_map(root, max_chars=max_chars)
    _write_cache(root, cdir, m)
    return m


def regenerate_project_map(
    root: Path | None,
    *,
    max_chars: int = DEFAULT_MAX_CHARS,
    cache_dir: Path | None = None,
) -> ProjectMap:
    """强制重建并刷新缓存，stale=False, from_cache=False。"""
    if not _is_valid_root(root):
        return _zero_map()
    root = Path(root).resolve()
    m = build_project_map(root, max_chars=max_chars)
    _write_cache(root, _resolve_cache_dir(cache_dir), m)
    return m
