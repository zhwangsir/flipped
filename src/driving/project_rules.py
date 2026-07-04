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


# 新建项目的默认规则模板(F8 三跑实测经验固化)。由 create_project 写入,
# 每轮拆解经 read_project_rules 注入 Supervisor —— 直接提升自主任务一次通过率:
# 第一跑 FastAPI 撞 `from app import counter` 值拷贝陷阱调试死循环,正是缺这类约定。
DEFAULT_AGENTS_MD = """\
# AGENTS.md — 本项目的 agent 开发约定

## 代码
- 可变状态封装在类里(勿用模块级全局变量存数据),便于测试隔离与重置。
- 遵循已有代码的风格、命名与存储结构;修改前先阅读相关文件。

## 测试
- 每个功能都写 pytest 测试,覆盖正常与异常分支。
- 统一用 `python3 -m pytest` 运行(不要用裸 `pytest` 命令)。
- 测试之间不得共享可变状态;在 fixture/setup 里重建被测对象。

## 依赖与执行
- 用到第三方库先 `pip install`;失败时先看完整报错再改。
- 同一个调试命令连续失败 2 次就换思路,不要原地重试。
"""


def write_default_rules(root: Path) -> bool:
    """给新项目写入默认 AGENTS.md(已存在则不覆盖)。返回是否写入。"""
    target = root / "AGENTS.md"
    if target.exists():
        return False
    try:
        target.write_text(DEFAULT_AGENTS_MD, encoding="utf-8")
        return True
    except OSError:
        return False


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
