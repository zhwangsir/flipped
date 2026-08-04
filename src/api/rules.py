"""M180 · 项目规则系统（对标 ZCode 规则系统）：项目级规则文件装载纯逻辑。

候选文件按优先级拼接（全部命中全部收）：`.flipped/rules.md`（本系统可写的主文件）、
`AGENTS.md`、`.cursorrules`（兼容存量工具约定）。装载结果供 B 队注入 chat/plan
system prompt（RULES_INJECT_HEADER），并供 GET/PUT /project/rules 端点组装响应。

- load_project_rules：现场读取，无缓存；单文件解码失败/读取异常/内容空白跳过该文件；
  拼接超 max_chars 从末尾整节丢弃（首节尽量保留）并注记「…已截断 N 节」。
- rules_raw_content：`.flipped/rules.md` 原始文本（编辑器初值用），不存在/读失败 → ""。
- write_project_rules：原子写 `.flipped/rules.md`（固定相对路径，零穿越面）。

纯函数模块：零 FastAPI import，函数级不 import main。
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

RULE_FILES = (".flipped/rules.md", "AGENTS.md", ".cursorrules")
RULES_MAX_CHARS = 4000
RULES_INJECT_HEADER = "以下是用户项目的规则（必须遵守）："  # B 队注入用

# 可写主文件（PUT 唯一目标，固定相对路径）
WRITABLE_RULES_PATH = ".flipped/rules.md"


@dataclass
class ProjectRules:
    files: list[str] = field(default_factory=list)  # 命中的相对路径（按 RULE_FILES 顺序）
    markdown: str = ""       # 渲染好的规则文档（≤ max_chars，截断注记「…已截断 N 节」）
    total_chars: int = 0     # 未截断前总长


def _read_rule_file(path: Path) -> str | None:
    """读单个规则文件：不存在/解码失败/读取异常/内容空白 → None（跳过该文件）。"""
    try:
        if not path.is_file():
            return None
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError, ValueError):
        return None
    if not text.strip():  # 空白文件不命中（空规则零注入）
        return None
    return text


def load_project_rules(root: Path | None, *, max_chars: int = RULES_MAX_CHARS) -> ProjectRules:
    """按 RULE_FILES 顺序收集存在的文件，渲染拼接为规则文档。

    每文件渲染为「## {relpath}\\n\\n{content}」节；拼接超 max_chars 从末尾整节丢弃
    （首节尽量保留：即使单节超预算也完整保留，避免空注入）并注记「…已截断 N 节」
    （注记在截断后追加，不计入预算）。files 记录全部命中文件（含被截断丢弃的节）。
    total_chars = 未截断前拼接总长。root None → 空 ProjectRules。纯函数，无缓存。
    """
    if root is None:
        return ProjectRules()
    files: list[str] = []
    sections: list[str] = []
    for rel in RULE_FILES:
        text = _read_rule_file(Path(root) / rel)
        if text is None:
            continue
        files.append(rel)
        sections.append(f"## {rel}\n\n{text}")
    if not sections:
        return ProjectRules()
    total_chars = len("\n\n".join(sections))
    kept: list[str] = []
    dropped = 0
    for i, section in enumerate(sections):
        if i > 0:
            candidate = "\n\n".join([*kept, section])
            if len(candidate) > max_chars:
                dropped = len(sections) - i  # 从末尾整节丢弃：此后各节一并丢弃
                break
        kept.append(section)
    markdown = "\n\n".join(kept)
    if dropped:
        markdown += f"\n\n…已截断 {dropped} 节"
    return ProjectRules(files=files, markdown=markdown, total_chars=total_chars)


def rules_raw_content(root: Path) -> str:
    """`.flipped/rules.md` 原始文本（编辑器初值用）；不存在/读失败 → ""。"""
    try:
        path = Path(root) / WRITABLE_RULES_PATH
        if not path.is_file():
            return ""
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError, ValueError):
        return ""


def write_project_rules(root: Path, content: str) -> str:
    """写 `.flipped/rules.md`（mkdir parents + tmp+os.replace 原子写），返回相对路径。

    固定相对路径（零穿越面），绝不接受调用方传路径。
    """
    target = Path(root) / WRITABLE_RULES_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = f"{target}.tmp"
    Path(tmp).write_text(content, encoding="utf-8")
    os.replace(tmp, target)
    return WRITABLE_RULES_PATH
