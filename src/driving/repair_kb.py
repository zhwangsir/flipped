"""P4-1 · 修复知识库沉淀。

将 AutoRepairEngine 的修复结果沉淀到 failure_kb，形成"从错误中学习"闭环。

闭环流程：
    auto_repair 产生 RepairResult
        → save_repair_knowledge() 写入 failure_kb
        → 下次任务执行前 get_repair_warnings() 检索历史
        → 注入预警到执行上下文

修复知识 = 失败记录 + 修复策略 + 验证结果 + 可复用性评估
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from driving.auto_repair import RepairResult, RepairStrategy, RepairAction
from driving.errors import ErrorRecord, classify_exception


@dataclass
class RepairKnowledge:
    """可复用的修复知识条目。"""
    task_description: str
    error_type: str
    error_message: str
    repair_strategy: str
    repair_actions: list[dict[str, Any]]
    success: bool
    attempts: int
    reusable: bool = False
    reuse_count: int = 0
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_description": self.task_description,
            "error_type": self.error_type,
            "error_message": self.error_message,
            "repair_strategy": self.repair_strategy,
            "repair_actions": self.repair_actions,
            "success": self.success,
            "attempts": self.attempts,
            "reusable": self.reusable,
            "reuse_count": self.reuse_count,
            "timestamp": self.timestamp,
        }


def save_repair_knowledge(
    task_description: str,
    repair_result: RepairResult,
    *,
    db_path: str = "data/failures.db",
) -> RepairKnowledge | None:
    """将修复结果沉淀到 failure_kb。

    成功的修复标记为 resolved + resolution；
    失败的修复标记为未解决，供后续任务规避。
    """
    try:
        from driving.failure_kb import record_failure

        error_record = repair_result.error_before
        if error_record is None:
            return None

        strategy_name = ""
        if repair_result.actions:
            strategy_name = repair_result.actions[0].strategy.value

        actions_summary = "; ".join(
            a.description or a.strategy.value for a in repair_result.actions
        )

        cause = error_record.error_type
        error_detail = error_record.message
        stop_reason = f"repair {'succeeded' if repair_result.success else 'failed'} after {repair_result.attempts} attempts"

        resolution = ""
        if repair_result.success:
            resolution = f"Fixed via {strategy_name}: {actions_summary}"

        reusable = repair_result.success and len(repair_result.actions) > 0

        entry = record_failure(
            task_description=task_description,
            design_style="auto",
            cause=cause,
            error_detail=error_detail,
            stop_reason=stop_reason,
            iterations=repair_result.attempts,
            resolved=repair_result.success,
            resolution=resolution,
            db_path=db_path,
        )

        knowledge = RepairKnowledge(
            task_description=task_description,
            error_type=error_record.error_type,
            error_message=error_record.message,
            repair_strategy=strategy_name,
            repair_actions=[a.to_dict() for a in repair_result.actions],
            success=repair_result.success,
            attempts=repair_result.attempts,
            reusable=reusable,
        )

        return knowledge

    except Exception:
        return None


def get_repair_warnings(
    task_description: str,
    *,
    db_path: str = "data/failures.db",
    max_warnings: int = 5,
) -> list[dict[str, Any]]:
    """检索历史修复知识，返回预警列表。

    返回格式：
    [
        {
            "cause": "ComparisonError",
            "error_detail": "dim missing",
            "resolution": "Fixed via align_dimensions",
            "resolved": True,
            "similarity": 0.85,
        },
        ...
    ]
    """
    try:
        from driving.failure_kb import query_similar_failures

        similar = query_similar_failures(
            task_description,
            design_style="auto",
            db_path=db_path,
            max_results=max_warnings,
            threshold=0.3,
        )

        warnings: list[dict[str, Any]] = []
        for entry in similar:
            warnings.append({
                "cause": entry.cause,
                "error_detail": entry.error_detail,
                "resolution": entry.resolution,
                "resolved": entry.resolved,
                "similarity": round(entry.similarity, 3),
                "stop_reason": entry.stop_reason,
            })

        return warnings

    except Exception:
        return []


def build_repair_warning_text(
    task_description: str,
    *,
    db_path: str = "data/failures.db",
    max_warnings: int = 3,
) -> str:
    """生成可注入到任务上下文的修复预警文本。"""
    try:
        warnings = get_repair_warnings(
            task_description, db_path=db_path, max_warnings=max_warnings
        )

        if not warnings:
            return ""

        lines = ["【修复知识预警】类似任务曾遇到以下问题，请注意规避："]
        for i, w in enumerate(warnings, 1):
            status = "已解决" if w["resolved"] else "未解决"
            resolution = f" → 解决方案: {w['resolution']}" if w["resolved"] else ""
            lines.append(
                f"  {i}. [{w['cause']}] {w['error_detail']} ({status}){resolution}"
            )

        return "\n".join(lines)

    except Exception:
        return ""


@dataclass
class RepairKBStats:
    """修复知识库统计。"""
    total_repairs_recorded: int = 0
    successful_repairs: int = 0
    failed_repairs: int = 0
    reuse_potential: int = 0
    by_strategy: dict[str, int] = field(default_factory=dict)
    by_error_type: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_repairs_recorded": self.total_repairs_recorded,
            "successful_repairs": self.successful_repairs,
            "failed_repairs": self.failed_repairs,
            "reuse_potential": self.reuse_potential,
            "by_strategy": self.by_strategy,
            "by_error_type": self.by_error_type,
            "success_rate": round(
                self.successful_repairs / max(1, self.total_repairs_recorded), 3
            ),
        }


def get_repair_kb_stats(*, db_path: str = "data/failures.db") -> RepairKBStats:
    """获取修复知识库统计。"""
    try:
        from driving.failure_kb import get_failure_stats

        stats = get_failure_stats(db_path=db_path)

        return RepairKBStats(
            total_repairs_recorded=stats.total_failures,
            successful_repairs=stats.resolved_count,
            failed_repairs=stats.unresolved_count,
            reuse_potential=stats.resolved_count,
            by_error_type=stats.by_cause,
        )

    except Exception:
        return RepairKBStats()
