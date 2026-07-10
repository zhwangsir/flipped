"""自主任务生成器（M31）。

当 factory_loop 的初始 roadmap 全部执行完后，task_proposer 基于当前项目状态
（已完成的任务、产物文件、design_score）自主生成下一个有意义的开发任务，
让工厂能"无限迭代"——只需给出方向，系统自己想出下一步该做什么。

设计原则：
- 基于事实：扫描 cwd 实际文件 + 已完成任务，不凭空臆想
- 有限迭代：max_rounds 限制自主生成轮次，防止空转
- fail-open：GLM 不可用时返回 None（停止迭代），不阻塞流程
"""
from __future__ import annotations

import os
from pathlib import Path

from pydantic import BaseModel, Field

from driving.factory_loop import FactoryState, FactoryTask
from driving.orchestrator import _invoke_structured, _make_llm  # noqa: WPS450


class TaskProposal(BaseModel):
    """GLM 返回的下一个任务提议。"""
    description: str = Field(description="下一个任务的描述，60 字以内")
    verify_cmd: list[str] = Field(
        default_factory=list,
        description="单行 shell 验收命令，必须用 python -m pytest 或文件检查",
    )
    reasoning: str = Field(description="为什么这个任务有价值，一句话")
    should_continue: bool = Field(
        default=True,
        description="False 表示项目已完善，没有更多有意义的任务了",
    )


def _scan_cwd_files(cwd: str, max_depth: int = 2, max_files: int = 30) -> list[str]:
    """扫描 cwd 的文件列表（相对路径），用于让 GLM 了解当前产物。

    跳过 .git / node_modules / __pycache__ / .venv 等目录。
    """
    skip_dirs = {".git", "node_modules", "__pycache__", ".venv", ".pytest_cache",
                 "dist", "build", ".next", ".cache", "test-results"}
    skip_exts = {".pyc", ".log", ".db", ".sqlite", ".zip", ".tar.gz"}
    files: list[str] = []

    def _walk(dir_path: Path, depth: int):
        if depth > max_depth or len(files) >= max_files:
            return
        try:
            entries = sorted(dir_path.iterdir(), key=lambda p: (p.is_file(), p.name))
        except PermissionError:
            return
        for entry in entries:
            if entry.name in skip_dirs:
                continue
            if entry.is_file():
                if entry.suffix in skip_exts:
                    continue
                rel = str(entry.relative_to(cwd))
                files.append(rel)
                if len(files) >= max_files:
                    return
            elif entry.is_dir():
                _walk(entry, depth + 1)

    _walk(Path(cwd), 0)
    return files


def _summarize_completed(state: FactoryState, max_items: int = 8) -> str:
    """把已完成的任务列表格式化为简短摘要。"""
    if not state.completed:
        return "无"
    lines = []
    for r in state.completed[-max_items:]:
        lines.append(f"  [{r.task.id}] {r.task.description}: {'done' if r.verified else 'failed'}")
    return "\n".join(lines)


def _get_design_score(cwd: str) -> str:
    """如果有 HTML 文件，计算 design_score 让 GLM 知道当前质量。"""
    try:
        from driving.design_context import design_score
        score, notes = design_score(cwd)
        if score > 0:
            notes_str = "; ".join(notes[:5]) if isinstance(notes, list) else str(notes)
            return f"design_score={score}/100 ({notes_str[:120]})"
    except Exception:
        pass
    return "无 HTML 产物或评分失败"


def propose_next_task(state: FactoryState) -> FactoryTask | None:
    """基于当前项目状态，自主生成下一个有意义的开发任务。

    返回 None 表示：
    - GLM 判定项目已完善（should_continue=False）
    - GLM 不可用或调用失败（fail-open，停止迭代）

    调用方（factory_loop）负责限制 max_rounds 防止空转。
    """
    files = _scan_cwd_files(state.cwd)
    completed_summary = _summarize_completed(state)
    score_info = _get_design_score(state.cwd)

    msg = (
        f"产品目标：{state.product_goal}\n"
        f"工作目录：{state.cwd}\n"
        f"当前产物文件：{files if files else '空'}\n"
        f"已完成任务：\n{completed_summary}\n"
        f"设计质量：{score_info}\n"
        f"设计风格：{state.design_style}\n\n"
        "你是产品架构师。基于当前项目状态，判断下一步最有价值的开发任务。\n"
        "任务必须自包含、可被一条验收命令验证。\n"
        "如果项目已经完善（功能完整、设计质量高、无明显改进空间），设 should_continue=False。\n"
        "verify_cmd 规则：单行 shell 命令，禁止裸 pytest（用 python -m pytest），禁止多行。\n"
        "输出要紧凑，避免冗长说明。"
    )

    try:
        proposal = _invoke_structured(_make_llm("architect"), TaskProposal, msg)
    except Exception:
        return None  # fail-open：GLM 不可用时停止迭代

    if not proposal.should_continue:
        return None

    if not proposal.description:
        return None

    # 复用 factory_loop 的 verify_cmd 清洗逻辑
    from driving.factory_loop import _sanitize_verify_cmd
    verify_cmd = _sanitize_verify_cmd(proposal.verify_cmd)

    return FactoryTask(
        id=f"proposed-{state.iteration_count + 1}",
        description=proposal.description,
        verify_cmd=verify_cmd,
        feedback=f"(自主生成: {proposal.reasoning})" if proposal.reasoning else "",
    )
