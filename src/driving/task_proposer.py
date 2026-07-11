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
    """如果有 HTML 文件，计算 design_score 让 GLM 知道当前质量。

    M40 增强：当 design_score < 阈值时，附带具体 lint 违规 rule 名，
    让 GLM 能生成精准的修复任务而非泛泛的"改进设计"。
    """
    try:
        from driving.design_context import design_score, lint_design_quality
        score, notes = design_score(cwd)
        if score > 0:
            notes_str = "; ".join(notes[:5]) if isinstance(notes, list) else str(notes)
            base = f"design_score={score}/100 ({notes_str[:120]})"
            # M40: 低分时附带具体违规 rule 名
            threshold = int(os.environ.get("FLIPPED_DESIGN_SCORE_THRESHOLD", "70"))
            if score < threshold:
                violations = lint_design_quality(cwd)
                if violations:
                    rule_names = sorted({
                        f"{v['rule']}({v['severity']})"
                        for v in violations[:10]
                    })
                    base += f" | 违规项: {', '.join(rule_names)}"
            return base
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

    # M40: 设计质量不达标时，明确指示 GLM 生成修复任务
    design_warning = ""
    if "违规项:" in score_info:
        design_warning = (
            "\n⚠️ 设计质量不达标，请优先生成针对上述违规项的修复任务"
            "（如补充 meta viewport、img alt、aria-label、响应式断点等）。\n"
        )

    msg = (
        f"产品目标：{state.product_goal}\n"
        f"工作目录：{state.cwd}\n"
        f"当前产物文件：{files if files else '空'}\n"
        f"已完成任务：\n{completed_summary}\n"
        f"设计质量：{score_info}\n"
        f"设计风格：{state.design_style}\n"
        f"{design_warning}\n"
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


def propose_design_fix_task(state: FactoryState) -> FactoryTask | None:
    """确定性 design fix fallback（M41）。

    当 GLM 不可用（propose_next_task 返回 None）时，检查 design_score：
    - 如果 HTML 的 design_score 低于阈值，自动生成修复任务
    - 先运行 auto_fix_design_issues，再用 design_score 验证
    - 不依赖 GLM，纯确定性逻辑，确保"无限迭代"不因模型不可用而中断

    M44 增强：在计算 score 前先运行 auto_fix_design_issues，
    如果 auto-fix 后 score 已达标，不需要生成修复任务。

    返回 None 表示：
    - 无 HTML 文件
    - design_score 已达标（含 auto-fix 后达标）
    - design_score 不可用
    - score 停滞（循环熔断，M43）
    """
    try:
        from driving.design_context import design_score, lint_design_quality, auto_fix_design_issues
    except Exception:
        return None

    cwd = state.cwd

    # M44: 先运行 auto_fix，看看能否直接修复到达标
    try:
        auto_fix_design_issues(cwd)
    except Exception:
        pass  # auto_fix 失败时不阻塞，继续检查 score

    try:
        score, notes = design_score(cwd)
    except Exception:
        return None

    if score == 0:
        return None  # 无 HTML 文件

    threshold = int(os.environ.get("FLIPPED_DESIGN_SCORE_THRESHOLD", "70"))
    if score >= threshold:
        return None  # auto-fix 后已达标，无需生成修复任务

    # M43: 循环检测 — 从最近 2 个 design-fix 任务的 feedback 解析 score，
    # 如果 score 连续无提升，说明 auto-fix + worker 无法修复剩余问题，停止
    import re as _re
    recent_fixes = [
        r for r in state.completed
        if "design-fix" in r.task.id
    ][-2:]
    if len(recent_fixes) >= 2:
        prev_scores = []
        for r in recent_fixes:
            m = _re.search(r"design_score=(\d+)/", r.task.feedback or "")
            if m:
                prev_scores.append(int(m.group(1)))
        if len(prev_scores) >= 2 and prev_scores[-1] == prev_scores[-2]:
            return None  # score 停滞，循环熔断

    # 获取具体违规项
    try:
        violations = lint_design_quality(cwd)
    except Exception:
        violations = []

    error_rules = sorted({v["rule"] for v in violations if v["severity"] == "error"})
    warning_rules = sorted({v["rule"] for v in violations if v["severity"] == "warning"})
    all_rules = error_rules + warning_rules

    # 构造修复任务描述
    if error_rules:
        rule_str = ", ".join(error_rules[:5])
        desc = f"修复设计质量问题（error级违规: {rule_str}）"
    elif warning_rules:
        rule_str = ", ".join(warning_rules[:5])
        desc = f"提升设计质量（warning级违规: {rule_str}）"
    else:
        desc = f"提升设计质量（当前 {score}/{threshold}）"

    # 验收命令：检查 design_score 是否达标
    verify_cmd = [
        f"python -c \"import sys; sys.path.insert(0,'src'); "
        f"from driving.design_context import design_score; "
        f"s,_=design_score('{cwd}'); "
        f"exit(0 if s>={threshold} else 1)\""
    ]

    feedback = (
        f"(确定性 fallback: design_score={score}/{threshold}, "
        f"auto_fix 已修复 11 组维度, "
        f"剩余违规: {', '.join(all_rules[:8]) if all_rules else '无'})"
    )

    return FactoryTask(
        id=f"design-fix-{state.iteration_count + 1}",
        description=desc,
        verify_cmd=verify_cmd,
        feedback=feedback,
    )


def propose_feature_task(state: FactoryState) -> FactoryTask | None:
    """确定性 feature proposer（M64，第三个 fallback）。

    当 GLM 不可用且 design_score 已达标时，扫描当前 HTML 产物，
    找出缺少的功能维度，生成有意义的增强任务，让工厂持续迭代产出更丰富的页面。

    每个功能维度有对应的确定性验收命令，不依赖 LLM。
    已完成的或 HTML 已有的功能维度不重复生成。
    所有功能维度都已具备时返回 None。
    """
    import os as _os

    cwd = state.cwd
    if not _os.path.exists(cwd):
        return None

    # 读取第一个 HTML 文件内容
    html_content = ""
    try:
        for fname in _os.listdir(cwd):
            if fname.endswith(".html"):
                fpath = _os.path.join(cwd, fname)
                if _os.path.isfile(fpath):
                    try:
                        html_content = open(fpath, "r", encoding="utf-8").read()
                        break
                    except Exception:
                        continue
    except Exception:
        return None

    if not html_content:
        return None

    # 已完成的 feature 任务 id 集合（去重）
    done_feature_ids = {
        r.task.id for r in state.completed if r.task.id.startswith("feature-")
    }

    safe_cwd = cwd.replace("'", "\\'")

    # 功能维度清单：(id, HTML 标记, 任务描述, 验收命令)
    # 验收命令统一用 python -c 格式，检查 HTML 是否包含对应标记
    features = [
        ("feature-1", "<form",
         "添加表单组件（<form> + input + label，用于用户交互）",
         f"python -c \"f=open('{safe_cwd}/index.html');c=f.read();assert '<form' in c,'no form';f.close()\""),
        ("feature-2", "<svg",
         "添加 SVG 图标（内联 SVG，提升视觉表现力）",
         f"python -c \"f=open('{safe_cwd}/index.html');c=f.read();assert '<svg' in c,'no svg';f.close()\""),
        ("feature-3", "<picture",
         "添加响应式图片（<picture> + source srcset，适配不同屏幕）",
         f"python -c \"f=open('{safe_cwd}/index.html');c=f.read();assert '<picture' in c,'no picture';f.close()\""),
        ("feature-4", "@media print",
         "添加打印样式（@media print，优化打印输出效果）",
         f"python -c \"f=open('{safe_cwd}/index.html');c=f.read();assert '@media print' in c.lower(),'no print styles';f.close()\""),
        ("feature-5", "<details",
         "添加折叠组件（<details> + <summary>，用于可展开内容）",
         f"python -c \"f=open('{safe_cwd}/index.html');c=f.read();assert '<details' in c,'no details';f.close()\""),
        ("feature-6", "scroll-behavior",
         "添加平滑滚动（CSS scroll-behavior: smooth，提升导航体验）",
         f"python -c \"f=open('{safe_cwd}/index.html');c=f.read();assert 'scroll-behavior' in c,'no smooth scroll';f.close()\""),
        ("feature-7", 'name="description"',
         "添加 SEO meta（<meta name=\"description\">，优化搜索引擎收录）",
         f"python -c \"f=open('{safe_cwd}/index.html');c=f.read();assert 'name=\\\"description\\\"' in c or 'name=\\'description\\'' in c,'no seo meta';f.close()\""),
        ("feature-8", "prefers-color-scheme",
         "添加暗色模式适配（@media prefers-color-scheme，跟随系统主题）",
         f"python -c \"f=open('{safe_cwd}/index.html');c=f.read();assert 'prefers-color-scheme' in c,'no dark mode';f.close()\""),
        ("feature-9", 'rel="icon"',
         "添加 favicon（<link rel=\"icon\">，浏览器标签图标）",
         f"python -c \"f=open('{safe_cwd}/index.html');c=f.read();assert 'rel=\\\"icon\\\"' in c or 'rel=\\'icon\\'' in c,'no favicon';f.close()\""),
        ("feature-10", 'rel="preload"',
         "添加资源预加载（<link rel=\"preload\">，优化关键资源加载）",
         f"python -c \"f=open('{safe_cwd}/index.html');c=f.read();assert 'rel=\\\"preload\\\"' in c or 'rel=\\'preload\\'' in c,'no preload';f.close()\""),
    ]

    for fid, marker, desc, verify in features:
        if fid in done_feature_ids:
            continue  # 已完成的任务，跳过
        if marker in html_content:
            continue  # HTML 已有此功能，跳过
        return FactoryTask(
            id=fid,
            description=desc,
            verify_cmd=[verify],
            feedback=f"(确定性 feature: 添加 {marker})",
        )

    return None  # 所有功能维度都已具备
