"""P3 · 异常分级体系。

将裸 ValueError 细分为语义化异常，便于上层精准捕获和处理。

异常层级：
    FlippedError                    所有异常的基类
    ├── ConfigurationError          配置错误（参数非法、范围越界）
    ├── ValidationError             数据校验错误（类型不符、缺失字段）
    ├── ComparisonError             对比评估错误（维度缺失、权重为零）
    ├── LoopError                   循环引擎错误（迭代失败、状态异常）
    └── AutoRepairError             自动修复错误（无法定位、修复失败）

每个异常携带 context dict，方便结构化日志和自动修复系统消费。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


class FlippedError(Exception):
    """所有 flipped 系统异常的基类。"""

    def __init__(self, message: str, *, context: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.context: dict[str, Any] = context or {}

    def to_dict(self) -> dict[str, Any]:
        return {
            "error_type": self.__class__.__name__,
            "message": self.message,
            "context": self.context,
        }


class ConfigurationError(FlippedError):
    """配置错误：参数非法、范围越界、空值。"""


class ValidationError(FlippedError):
    """数据校验错误：类型不符、缺失字段、格式错误。"""


class ComparisonError(FlippedError):
    """对比评估错误：维度缺失、权重为零、得分越界。"""


class LoopError(FlippedError):
    """循环引擎错误：迭代失败、状态异常、超过预算。"""


class AutoRepairError(FlippedError):
    """自动修复错误：无法定位根因、修复失败、重试耗尽。"""


@dataclass
class ErrorRecord:
    """结构化错误记录，用于日志和自动修复系统消费。"""
    error_type: str
    message: str
    context: dict[str, Any] = field(default_factory=dict)
    module: str = ""
    function: str = ""
    recoverable: bool = True
    suggested_fix: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "error_type": self.error_type,
            "message": self.message,
            "context": self.context,
            "module": self.module,
            "function": self.function,
            "recoverable": self.recoverable,
            "suggested_fix": self.suggested_fix,
        }


def classify_exception(exc: Exception) -> ErrorRecord:
    """将任意异常分类为 ErrorRecord，供自动修复系统消费。

    >>> from driving.errors import classify_exception, ConfigurationError
    >>> rec = classify_exception(ValueError("bad"))
    >>> rec.error_type
    'ValueError'
    >>> rec.recoverable
    True

    >>> rec2 = classify_exception(ConfigurationError("cfg", context={"k": "v"}))
    >>> rec2.error_type
    'ConfigurationError'
    >>> rec2.context["k"]
    'v'
    """
    if isinstance(exc, FlippedError):
        return ErrorRecord(
            error_type=exc.__class__.__name__,
            message=exc.message,
            context=exc.context,
            recoverable=not isinstance(exc, AutoRepairError),
        )

    if isinstance(exc, ValueError):
        return ErrorRecord(
            error_type="ValueError",
            message=str(exc),
            recoverable=True,
            suggested_fix="check input parameters and types",
        )

    if isinstance(exc, (KeyError, IndexError)):
        return ErrorRecord(
            error_type=type(exc).__name__,
            message=str(exc),
            recoverable=True,
            suggested_fix="check data structure and key/index existence",
        )

    if isinstance(exc, (TypeError, AttributeError)):
        return ErrorRecord(
            error_type=type(exc).__name__,
            message=str(exc),
            recoverable=True,
            suggested_fix="check type annotations and attribute existence",
        )

    return ErrorRecord(
        error_type=type(exc).__name__,
        message=str(exc),
        recoverable=False,
        suggested_fix="manual investigation required",
    )
