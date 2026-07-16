"""P3-4 · 错误场景自动化修复。

自动检测错误模式 → 定位根因 → 生成修复策略 → 应用修复 → 验证 → 记录。

修复策略库：
1. 缺失字段 → 补充默认值
2. 类型不匹配 → 强制转换
3. 范围越界 → clamp 到合法范围
4. 空值 → 注入安全默认
5. 权重为零 → 均匀分布
6. 维度不匹配 → 对齐维度集合

修复流程：
    detect_error → classify → match_strategy → apply_fix → verify_fix → record

每条修复记录可供 Failure KB 和 Skill 系统消费，形成学习闭环。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from driving.errors import (
    FlippedError,
    ConfigurationError,
    ValidationError,
    ComparisonError,
    LoopError,
    AutoRepairError,
    ErrorRecord,
    classify_exception,
)


class RepairStrategy(str, Enum):
    fill_default = "fill_default"
    type_cast = "type_cast"
    clamp_range = "clamp_range"
    inject_safe_value = "inject_safe_value"
    uniform_weights = "uniform_weights"
    align_dimensions = "align_dimensions"
    retry_with_backoff = "retry_with_backoff"
    skip_and_continue = "skip_and_continue"
    manual_required = "manual_required"


@dataclass
class RepairAction:
    """一次修复动作。"""
    strategy: RepairStrategy
    target: str
    before: Any
    after: Any
    description: str = ""
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy": self.strategy.value,
            "target": self.target,
            "before": self.before,
            "after": self.after,
            "description": self.description,
            "timestamp": self.timestamp,
        }


@dataclass
class RepairResult:
    """修复结果。"""
    success: bool
    actions: list[RepairAction] = field(default_factory=list)
    error_before: ErrorRecord | None = None
    error_after: ErrorRecord | None = None
    attempts: int = 0
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "actions": [a.to_dict() for a in self.actions],
            "error_before": self.error_before.to_dict() if self.error_before else None,
            "error_after": self.error_after.to_dict() if self.error_after else None,
            "attempts": self.attempts,
            "timestamp": self.timestamp,
        }


class AutoRepairEngine:
    """错误场景自动化修复引擎。"""

    # 错误类型 → 修复策略映射
    STRATEGY_MAP: dict[str, RepairStrategy] = {
        "ConfigurationError": RepairStrategy.inject_safe_value,
        "ValidationError": RepairStrategy.fill_default,
        "ComparisonError": RepairStrategy.align_dimensions,
        "ValueError": RepairStrategy.fill_default,
        "KeyError": RepairStrategy.fill_default,
        "TypeError": RepairStrategy.type_cast,
        "IndexError": RepairStrategy.clamp_range,
        "LoopError": RepairStrategy.retry_with_backoff,
    }

    def __init__(self, max_attempts: int = 3) -> None:
        self.max_attempts = max_attempts
        self.repair_history: list[RepairResult] = []

    def detect_and_classify(self, exc: Exception) -> ErrorRecord:
        """检测并分类异常。"""
        return classify_exception(exc)

    def match_strategy(self, error_record: ErrorRecord) -> RepairStrategy:
        """根据错误记录匹配修复策略。"""
        strategy = self.STRATEGY_MAP.get(error_record.error_type)
        if strategy is None:
            if error_record.recoverable:
                return RepairStrategy.skip_and_continue
            return RepairStrategy.manual_required
        return strategy

    def apply_fix(
        self,
        error_record: ErrorRecord,
        target_data: dict[str, Any],
        *,
        strategy: RepairStrategy | None = None,
    ) -> tuple[dict[str, Any], list[RepairAction]]:
        """应用修复策略到目标数据，返回修复后的数据和动作列表。"""
        actions: list[RepairAction] = []
        s = strategy or self.match_strategy(error_record)
        data = dict(target_data)

        if s == RepairStrategy.fill_default:
            key = error_record.context.get("dimension", error_record.context.get("key", ""))
            if key and key not in data:
                data[key] = 50.0
                actions.append(RepairAction(
                    strategy=s, target=str(key),
                    before=None, after=50.0,
                    description=f"Filled missing key '{key}' with default 50.0",
                ))

        elif s == RepairStrategy.type_cast:
            for key, val in list(data.items()):
                if not isinstance(val, (int, float)) and isinstance(val, str):
                    try:
                        casted = float(val)
                        data[key] = casted
                        actions.append(RepairAction(
                            strategy=s, target=key,
                            before=val, after=casted,
                            description=f"Cast '{key}' from str to float",
                        ))
                    except (ValueError, TypeError):
                        pass

        elif s == RepairStrategy.clamp_range:
            lo, hi = 0.0, 100.0
            for key, val in list(data.items()):
                if isinstance(val, (int, float)):
                    clamped = max(lo, min(hi, val))
                    if clamped != val:
                        data[key] = clamped
                        actions.append(RepairAction(
                            strategy=s, target=key,
                            before=val, after=clamped,
                            description=f"Clamped '{key}' from {val} to {clamped}",
                        ))

        elif s == RepairStrategy.inject_safe_value:
            for key in error_record.context.get("missing_keys", []):
                if key not in data:
                    data[key] = 0.0
                    actions.append(RepairAction(
                        strategy=s, target=key,
                        before=None, after=0.0,
                        description=f"Injected safe value 0.0 for '{key}'",
                    ))

        elif s == RepairStrategy.uniform_weights:
            weight_keys = [k for k in data if k.startswith("weight_")]
            if weight_keys:
                uniform = 1.0 / len(weight_keys)
                for k in weight_keys:
                    old = data[k]
                    data[k] = uniform
                    actions.append(RepairAction(
                        strategy=s, target=k,
                        before=old, after=uniform,
                        description=f"Set uniform weight {uniform:.4f} for '{k}'",
                    ))

        elif s == RepairStrategy.align_dimensions:
            required = set(error_record.context.get("dimensions", []))
            single_dim = error_record.context.get("dimension")
            if single_dim:
                required.add(single_dim)
            present = set(data.keys())
            for dim in required - present:
                data[dim] = 50.0
                actions.append(RepairAction(
                    strategy=s, target=dim,
                    before=None, after=50.0,
                    description=f"Aligned dimensions: added '{dim}' with default 50.0",
                ))

        elif s == RepairStrategy.skip_and_continue:
            actions.append(RepairAction(
                strategy=s, target="*",
                before=None, after=None,
                description="Skipped non-critical error",
            ))

        elif s == RepairStrategy.manual_required:
            raise AutoRepairError(
                f"Cannot auto-repair: {error_record.message}",
                context=error_record.to_dict(),
            )

        return data, actions

    def verify_fix(
        self,
        fixed_data: dict[str, Any],
        validate_fn,
    ) -> bool:
        """验证修复后的数据是否通过校验函数。"""
        try:
            validate_fn(fixed_data)
            return True
        except Exception:
            return False

    def repair(
        self,
        exc: Exception,
        target_data: dict[str, Any],
        *,
        validate_fn=None,
    ) -> RepairResult:
        """完整修复流程：检测→匹配→修复→验证。"""
        result = RepairResult(success=False)
        result.error_before = self.detect_and_classify(exc)

        for attempt in range(1, self.max_attempts + 1):
            result.attempts = attempt
            try:
                strategy = self.match_strategy(result.error_before)
                fixed_data, actions = self.apply_fix(
                    result.error_before, target_data, strategy=strategy,
                )
                result.actions.extend(actions)
                target_data = fixed_data

                if validate_fn and self.verify_fix(fixed_data, validate_fn):
                    result.success = True
                    break
                elif validate_fn is None:
                    result.success = True
                    break
                else:
                    result.error_after = ErrorRecord(
                        error_type="ValidationError",
                        message=f"Validation failed on attempt {attempt}",
                        recoverable=attempt < self.max_attempts,
                    )
            except AutoRepairError:
                result.error_after = ErrorRecord(
                    error_type="AutoRepairError",
                    message="Manual repair required",
                    recoverable=False,
                )
                break
            except Exception as e:
                result.error_after = classify_exception(e)

        self.repair_history.append(result)
        return result

    def get_stats(self) -> dict[str, Any]:
        """获取修复统计。"""
        total = len(self.repair_history)
        if total == 0:
            return {"total_repairs": 0, "success_rate": 0.0}
        successes = sum(1 for r in self.repair_history if r.success)
        return {
            "total_repairs": total,
            "successful": successes,
            "failed": total - successes,
            "success_rate": round(successes / total, 3),
            "avg_attempts": round(
                sum(r.attempts for r in self.repair_history) / total, 2
            ),
        }
