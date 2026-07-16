"""M103 · 增量改进模式 — verify 失败后基于现有产物精准修复。

核心思路：
- 首次生成 = 全量生成（从零写）
- verify 失败后 = 增量修复（在现有文件基础上改）
- 最多 MAX_INCREMENTAL_ROUNDS 轮增量修复，仍失败则 fallback 全量重写

这样既避免了"失败就重写"的浪费，也给了系统从错误中学习的机会。
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


MAX_INCREMENTAL_ROUNDS = 3

_SOURCE_EXTS = {
    ".html", ".css", ".js", ".mjs", ".ts", ".tsx", ".jsx",
    ".py", ".json", ".md", ".yml", ".yaml", ".svg", ".vue",
    ".svelte", ".scss", ".less",
}

_SKIP_DIRS = {
    ".git", "node_modules", "__pycache__", ".venv", ".pytest_cache",
    "dist", "build", ".next", ".cache", "test-results", ".DS_Store",
}


@dataclass
class IncrementalContext:
    """增量修复的上下文信息。"""
    cwd: str
    failure_output: str
    round_num: int = 1
    rca_cause: str = ""
    rca_suggestion: str = ""
    max_rounds: int = MAX_INCREMENTAL_ROUNDS
    extra_context: dict[str, Any] = field(default_factory=dict)

    def is_final_round(self) -> bool:
        return self.round_num >= self.max_rounds


def detect_existing_artifacts(
    cwd: str,
    max_depth: int = 3,
    max_size_kb: int = 100,
) -> dict[str, str]:
    """扫描 cwd 下已有源文件，返回 {相对路径: 内容}。

    用于让 worker 在现有产物基础上修复，而非从零重写。
    跳过二进制、大文件、非源码文件。
    """
    artifacts: dict[str, str] = {}
    max_bytes = max_size_kb * 1024

    def _walk(dir_path: Path, depth: int):
        if depth > max_depth:
            return
        try:
            entries = sorted(dir_path.iterdir(), key=lambda p: (p.is_file(), p.name))
        except (PermissionError, FileNotFoundError):
            return
        for entry in entries:
            if entry.name in _SKIP_DIRS:
                continue
            if entry.is_dir():
                _walk(entry, depth + 1)
            elif entry.is_file():
                if entry.suffix.lower() not in _SOURCE_EXTS:
                    continue
                try:
                    size = entry.stat().st_size
                    if size > max_bytes:
                        continue
                    rel = str(entry.relative_to(cwd))
                    artifacts[rel] = entry.read_text(encoding="utf-8")
                except Exception:
                    pass

    _walk(Path(cwd), 0)
    return artifacts


def build_incremental_prompt(
    ctx: IncrementalContext,
    task_description: str,
    *,
    max_files: int = 5,
) -> str:
    """构建增量修复模式的 worker prompt。

    关键点：
    1. 明确告诉 worker 这是"修复"不是"重写"
    2. 注入现有文件内容（让 worker 知道改哪里）
    3. 注入失败输出 + RCA 分析（让 worker 知道改什么）
    4. 限制输出格式为完整文件内容（避免 patch 格式难以解析）
    """
    artifacts = detect_existing_artifacts(ctx.cwd)
    file_items = sorted(artifacts.items())[:max_files]

    parts = [
        f"【增量修复模式 · 第 {ctx.round_num} 轮】",
        f"任务：{task_description}",
        "",
        "当前项目已有文件：",
    ]

    if not file_items:
        parts.append("  （无现有文件，需从头创建）")
    else:
        for path, content in file_items:
            preview = content[:2000] + ("..." if len(content) > 2000 else "")
            parts.append(f"--- {path} ---")
            parts.append(preview)
            parts.append("")

    parts.append(f"上一轮验证失败输出：")
    parts.append(ctx.failure_output[:1000] if ctx.failure_output else "（无）")
    parts.append("")

    if ctx.rca_cause:
        parts.append(f"根因分析：{ctx.rca_cause}")
    if ctx.rca_suggestion:
        parts.append(f"修复建议：{ctx.rca_suggestion}")
    parts.append("")

    if ctx.is_final_round():
        parts.append("⚠️ 这是最后一轮增量修复机会。如仍失败将全量重写。请务必精准修复。")
        parts.append("")

    parts.append("要求：")
    parts.append("1. 在现有文件基础上修复问题，不要重写与问题无关的部分")
    parts.append("2. 保持原有设计风格、配色、布局不变")
    parts.append("3. 用 ```语言:文件路径 格式输出完整的修复后文件内容")
    parts.append("4. 只需输出需要修改的文件，无需输出所有文件")
    parts.append("5. 只输出代码块，不要额外解释")

    return "\n".join(parts)


def apply_patch_to_file(cwd: str, file_path: str, content: str) -> bool:
    """把修复后的文件内容写回 cwd 下对应路径。

    支持：
    - 覆盖现有文件
    - 创建新文件（含嵌套目录）
    - 空内容返回 False（不写空文件）
    """
    if not content.strip():
        return False

    try:
        full_path = Path(cwd) / file_path
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(content, encoding="utf-8")
        return True
    except Exception:
        return False


def should_use_incremental(
    iteration: int,
    has_artifacts: bool,
    max_rounds: int = MAX_INCREMENTAL_ROUNDS,
) -> bool:
    """判断是否应该使用增量修复模式。

    规则：
    - iteration = 0（首轮）：不用增量，全量生成
    - 有现有产物 + 未超过最大轮次：用增量
    - 超过最大轮次：fallback 全量重写
    """
    if iteration <= 0:
        return False
    if not has_artifacts:
        return False
    if iteration > max_rounds:
        return False
    return True
