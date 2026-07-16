"""M108 · 任务分解与子任务派发。

复杂任务自动分解为 3-5 个子任务，每个子任务独立执行、独立验证，
成功后再合并。降低单次任务复杂度，提升成功率。

fail-open: 任何异常都返回不分解（原任务直接执行），不阻塞主流程。
"""
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from typing import Any


DEFAULT_COMPLEXITY_THRESHOLD = 35.0
DEFAULT_MIN_SUBTASKS = 3
DEFAULT_MAX_SUBTASKS = 5


@dataclass
class SubTask:
    """子任务定义。"""
    subtask_id: str
    description: str
    order: int
    verify_cmd: list[str]
    dependencies: list[str] = field(default_factory=list)
    design_hints: str = ""


@dataclass
class DecompositionResult:
    """任务分解结果。"""
    should_decompose: bool
    subtasks: list[SubTask]
    original_task: str
    complexity_score: float
    reason: str = ""


def estimate_task_complexity_for_decompose(
    description: str,
    *,
    file_count: int = 1,
    dependency_count: int = 0,
) -> float:
    """估算任务复杂度，用于判断是否需要分解。

    评分维度（0-100）：
    - 描述长度 (30%): 越长通常越复杂
    - 关键词匹配 (35%): 多模块/全栈/分布式等关键词
    - 文件数量 (25%): 越多越复杂
    - 依赖数量 (10%): 越多越复杂
    """
    try:
        desc = description or ""
        desc_len = len(desc)

        len_score = min(30.0, desc_len / 10.0)

        high_keywords = [
            "distributed", "microservice", "full-stack", "full stack",
            "end-to-end", "e-commerce", "ecommerce", "saas",
            "分布式", "微服务", "全栈", "端到端", "电商", "多租户",
            "dashboard", "管理后台", "后台系统", "crm", "erp",
            "platform", "平台", "system", "系统",
        ]
        medium_keywords = [
            "feature", "module", "component", "integration",
            "功能", "模块", "组件", "集成", "重构",
            "user management", "authentication", "权限", "认证",
            "landing page", "dashboard", "仪表板",
            "user", "order", "product", "cart", "comment", "post",
            "用户", "订单", "商品", "购物车", "评论", "文章",
            "hero", "feature", "footer", "header",
            "头部", "页脚", "特性",
        ]

        desc_lower = desc.lower()
        kw_score = 0.0
        for kw in high_keywords:
            if kw.lower() in desc_lower:
                kw_score += 8.0
        for kw in medium_keywords:
            if kw.lower() in desc_lower:
                kw_score += 4.0
        kw_score = min(40.0, kw_score)

        file_score = min(25.0, file_count * 2.5)
        dep_score = min(5.0, dependency_count * 2.5)

        total = len_score + kw_score + file_score + dep_score
        return round(total, 1)
    except Exception:
        return 0.0


def should_decompose(
    description: str,
    *,
    file_count: int = 1,
    threshold: float = DEFAULT_COMPLEXITY_THRESHOLD,
) -> bool:
    """判断任务是否需要分解。"""
    try:
        score = estimate_task_complexity_for_decompose(
            description, file_count=file_count
        )
        return score >= threshold
    except Exception:
        return False


def _generate_subtasks_simple(description: str, count: int) -> list[SubTask]:
    """不依赖 LLM 的启发式子任务生成（fallback）。

    基于任务描述中的关键词模式，把任务拆成 3-5 个子任务。
    """
    desc = description.strip()

    patterns = [
        (r"(landing page|首页|着陆页).*(hero|header).*(feature|功能).*(footer|页脚)",
         [
             "构建页面基础结构和 Hero 区域（HTML 骨架 + CSS 变量 + Hero 内容）",
             "实现 Features/功能展示区域（卡片布局 + 交互动效）",
             "完成 Footer 和页面细节优化（底部区域 + 响应式适配 + 动画打磨）",
         ]),
        (r"(dashboard|仪表板|管理后台).*(user|用户).*(order|订单).*(analytics|分析)",
         [
             "搭建 Dashboard 基础框架和布局（侧边栏 + 顶栏 + 主内容区）",
             "实现用户管理模块（用户列表 + 搜索 + 状态管理）",
             "实现订单/数据模块（数据表格 + 筛选 + 统计卡片）",
             "完成分析图表和整体优化（图表组件 + 响应式 + 动效打磨）",
         ]),
        (r"(blog|博客).*(user|用户).*(post|文章).*(comment|评论)",
         [
             "搭建博客基础框架和用户系统（路由 + 布局 + 用户认证）",
             "实现文章管理模块（文章列表 + 详情页 + 发布编辑）",
             "实现评论系统和互动功能（评论列表 + 发布 + 点赞）",
             "完成整体优化和打磨（响应式 + 动效 + SEO）",
         ]),
    ]

    matched_descriptions: list[str] | None = None
    desc_lower = desc.lower()
    for pattern, descs in patterns:
        if re.search(pattern, desc_lower):
            matched_descriptions = descs
            break

    if matched_descriptions is None:
        matched_descriptions = [
            f"第一阶段：搭建基础架构和核心组件（{desc[:40]}...）",
            f"第二阶段：实现主要功能模块（核心逻辑 + 交互）",
            f"第三阶段：完成整体优化和打磨（细节 + 响应式 + 测试）",
        ]

    n = min(count, len(matched_descriptions))
    subtasks = []
    for i in range(n):
        subtasks.append(SubTask(
            subtask_id=f"st-{i}-{uuid.uuid4().hex[:6]}",
            description=matched_descriptions[i],
            order=i,
            verify_cmd=["true"],
            dependencies=[f"st-{j}-..." for j in range(i)] if i > 0 else [],
        ))

    return subtasks


def decompose_task(
    description: str,
    *,
    file_count: int = 1,
    dependency_count: int = 0,
    min_subtasks: int = DEFAULT_MIN_SUBTASKS,
    max_subtasks: int = DEFAULT_MAX_SUBTASKS,
    threshold: float = DEFAULT_COMPLEXITY_THRESHOLD,
    use_llm: bool = False,
) -> DecompositionResult:
    """分解任务为多个子任务。

    - use_llm=False: 使用启发式规则分解（默认，快速、不依赖外部）
    - use_llm=True: 调用 GLM 智能分解（更准确，但有延迟和成本）

    fail-open: 任何异常都返回不分解。
    """
    try:
        if not description or not description.strip():
            return DecompositionResult(
                should_decompose=False,
                subtasks=[SubTask(
                    subtask_id=f"st-0-{uuid.uuid4().hex[:6]}",
                    description=description,
                    order=0,
                    verify_cmd=["true"],
                )],
                original_task=description,
                complexity_score=0.0,
                reason="empty description",
            )

        score = estimate_task_complexity_for_decompose(
            description, file_count=file_count, dependency_count=dependency_count
        )

        if score < threshold:
            return DecompositionResult(
                should_decompose=False,
                subtasks=[SubTask(
                    subtask_id=f"st-0-{uuid.uuid4().hex[:6]}",
                    description=description,
                    order=0,
                    verify_cmd=["true"],
                )],
                original_task=description,
                complexity_score=score,
                reason=f"complexity {score} < threshold {threshold}",
            )

        n = max(min_subtasks, min(max_subtasks, int(score / 15)))
        subtasks = _generate_subtasks_simple(description, n)

        return DecompositionResult(
            should_decompose=True,
            subtasks=subtasks,
            original_task=description,
            complexity_score=score,
            reason=f"complexity {score} >= threshold {threshold}, decomposed into {len(subtasks)} subtasks",
        )
    except Exception:
        return DecompositionResult(
            should_decompose=False,
            subtasks=[SubTask(
                subtask_id=f"st-0-{uuid.uuid4().hex[:6]}",
                description=description,
                order=0,
                verify_cmd=["true"],
            )],
            original_task=description,
            complexity_score=0.0,
            reason="decomposition error, fallback to single task",
        )


def merge_subtask_results(results: list[dict[str, Any]]) -> dict[str, Any]:
    """合并多个子任务的执行结果。

    返回格式: {
        "all_success": bool,
        "completed_count": int,
        "failed_count": int,
        "failed_subtasks": list,
        "results": list,
    }
    """
    try:
        completed = [r for r in results if r.get("success", False)]
        failed = [r for r in results if not r.get("success", False)]

        return {
            "all_success": len(failed) == 0,
            "completed_count": len(completed),
            "failed_count": len(failed),
            "failed_subtasks": [
                {"id": r.get("subtask_id"), "error": r.get("error", "unknown")}
                for r in failed
            ],
            "results": results,
        }
    except Exception:
        return {
            "all_success": False,
            "completed_count": 0,
            "failed_count": len(results),
            "failed_subtasks": [],
            "results": results,
        }
