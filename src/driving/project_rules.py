"""项目规则文件读取(F6 · 遵守项目约定)。

每个成熟 AI 编程工具都有"项目规则"文件让 agent 遵守项目特定约定:Codex 的 AGENTS.md、
Claude Code 的 CLAUDE.md、Cursor 的 .cursorrules、Windsurf 的 .windsurfrules、Cline 的
.clinerules、Copilot 的 .github/copilot-instructions.md。本模块从活动项目根读取这些文件,
拼成一段供 Supervisor 拆解时注入 prompt —— 自主开发不再无视项目规矩。

纯函数、有大小上限,读 host 项目根(规则文件在宿主机;Supervisor 节点在 host 跑)。
"""
from __future__ import annotations

from pathlib import Path

# 按优先级依次读取(存在即拼入);覆盖主流工具的约定文件
RULES_FILES = [
    "AGENTS.md",
    "CLAUDE.md",
    ".cursorrules",
    ".windsurfrules",
    ".clinerules",
    ".github/copilot-instructions.md",
    ".rules",
]
_PER_FILE_CAP = 4000   # 单文件字符上限
_TOTAL_CAP = 8000      # 拼接总字符上限(控制每轮 supervisor prompt 体积)


def read_project_rules(root: Path | None) -> str:
    """读取项目根的规则文件并拼成一段(带 `## 文件名` 分隔)。无则返回空串。"""
    if root is None or not root.is_dir():
        return ""
    parts: list[str] = []
    total = 0
    for rel in RULES_FILES:
        f = root / rel
        if not f.is_file():
            continue
        try:
            text = f.read_text(encoding="utf-8")[:_PER_FILE_CAP].strip()
        except (OSError, UnicodeDecodeError):
            continue
        if not text:
            continue
        block = f"## {rel}\n{text}"
        remaining = _TOTAL_CAP - total
        if len(block) > remaining:
            block = block[:remaining]
        parts.append(block)
        total += len(block)
        if total >= _TOTAL_CAP:
            break
    return "\n\n".join(parts)
