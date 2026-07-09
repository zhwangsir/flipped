"""失败根因自动归因（M12 RCA）。

当 worker/verify 失败时，自动分析错误模式，分类根因，给 supervisor 提供精确修复建议。
比 stuck_detector（只检测"是否卡住"）更进一步——告诉 supervisor **为什么卡住**和**怎么修**。

RCA 分类：
1. reasoning_overflow — Kimi reasoning_content 吃光 tokens (content_len < 50)
2. syntax_error — 生成代码有语法错误
3. missing_import — 生成代码缺少 import
4. verify_mismatch — verify_cmd 失败但代码能跑
5. design_violation — design-lint 失败
6. a11y_violation — a11y 扫描失败
7. timeout — worker 超时
8. max_iterations — worker 迭代上限
9. empty_output — worker 返回空内容
10. infra_failure — 模型/服务器不可达
11. unknown — 未分类

每类根因附带 fix_suggestion，直接注入 supervisor feedback。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class RootCause(str, Enum):
    REASONING_OVERFLOW = "reasoning_overflow"
    SYNTAX_ERROR = "syntax_error"
    MISSING_IMPORT = "missing_import"
    VERIFY_MISMATCH = "verify_mismatch"
    DESIGN_VIOLATION = "design_violation"
    A11Y_VIOLATION = "a11y_violation"
    TIMEOUT = "timeout"
    MAX_ITERATIONS = "max_iterations"
    EMPTY_OUTPUT = "empty_output"
    INFRA_FAILURE = "infra_failure"
    UNKNOWN = "unknown"


@dataclass
class RcaResult:
    """一次根因分析的判定结果。"""
    cause: RootCause
    confidence: float  # 0.0-1.0
    detail: str = ""
    fix_suggestion: str = ""
    related_rules: list[str] = field(default_factory=list)

    def to_feedback(self) -> str:
        """转成给 supervisor 的 feedback 文本。"""
        parts = [f"[RCA] 根因={self.cause.value} (置信度{self.confidence:.0%})"]
        if self.detail:
            parts.append(f"详情：{self.detail[:200]}")
        if self.fix_suggestion:
            parts.append(f"建议：{self.fix_suggestion}")
        return " | ".join(parts)


# ---------- 模式匹配规则 ----------

# 每条规则：(pattern_regex, cause, fix_suggestion, confidence)
_RULES: list[tuple[re.Pattern, RootCause, str, float]] = [
    # reasoning overflow：content_len 很小
    (re.compile(r"content_len\s*[=:]\s*0\b|content_len\s*[=:]\s*[1-9]\b|content_len\s*[=:]\s*[1-4]\d\b", re.I),
     RootCause.REASONING_OVERFLOW,
     "Kimi reasoning_content 占满 max_tokens，几乎没产出内容。精简 prompt（移除冗余上下文），或用最小 prompt 重试。",
     0.9),
    (re.compile(r"reasoning.overflow|reasoning_content", re.I),
     RootCause.REASONING_OVERFLOW,
     "reasoning_content 干扰。确保 enable_thinking=false + streaming 模式只收 content deltas。",
     0.7),

    # 语法错误
    (re.compile(r"SyntaxError|IndentationError|unexpected (token|indent|EOF)|invalid syntax", re.I),
     RootCause.SYNTAX_ERROR,
     "生成代码有语法错误。检查缩进/括号/引号匹配，用 python -m py_compile 验证。",
     0.85),
    (re.compile(r"SyntaxError: unexpected character", re.I),
     RootCause.SYNTAX_ERROR,
     "字符语法错误（可能是中文标点混入）。确保代码用英文标点。",
     0.9),

    # 缺少 import
    (re.compile(r"ModuleNotFoundError|ImportError: No module named", re.I),
     RootCause.MISSING_IMPORT,
     "缺少 import 语句。在文件顶部添加对应的 import。",
     0.9),
    (re.compile(r"NameError: name '(\w+)' is not defined", re.I),
     RootCause.MISSING_IMPORT,
     "变量未定义，可能是缺少 import 或拼写错误。检查 NameError 指出的变量名。",
     0.8),

    # verify 失败
    (re.compile(r"verify.*fail|assertion.*fail|assert\s.*Error|FAILED\s*\(|tests?\s+failed", re.I),
     RootCause.VERIFY_MISMATCH,
     "verify_cmd 失败。先看 verify_cmd 测的是什么，再针对性修复，不要推倒重来。",
     0.7),

    # design-lint 失败
    (re.compile(r"design.?lint.*fail|design.*未通过|design_colors|no_named_colors|entry_file.*error", re.I),
     RootCause.DESIGN_VIOLATION,
     "design-lint 失败。使用设计系统要求的 hex 颜色值，添加响应式断点和 hover/focus 状态。",
     0.85),

    # a11y 失败
    (re.compile(r"a11y.*未通过|axe.*violation|image-alt|html-has-lang|color-contrast.*fail", re.I),
     RootCause.A11Y_VIOLATION,
     "a11y 扫描失败。给 img 添加 alt 属性，给 html 添加 lang 属性，确保颜色对比度达标。",
     0.85),

    # 超时
    (re.compile(r"timeout|timed?\s*out|ReadTimeout|ConnectTimeout", re.I),
     RootCause.TIMEOUT,
     "执行超时。可能是任务太大或模型响应慢。拆小任务或增加超时时间。",
     0.7),

    # 迭代上限
    (re.compile(r"MaxIterationsReached|maximum iterations|max_iterations.*reached", re.I),
     RootCause.MAX_ITERATIONS,
     "达到迭代上限。子任务太大或陷入调试循环。拆成更小的子任务。",
     0.85),

    # 空输出
    (re.compile(r"empty.*content|content.*empty|no.*output|output.*empty|returned\s+empty", re.I),
     RootCause.EMPTY_OUTPUT,
     "worker 返回空内容。用最小 prompt 重试，确保只输出代码块。",
     0.7),

    # 基础设施故障
    (re.compile(r"connection.*refused|unreachable|503|502|504|ConnectionError|ConnectError", re.I),
     RootCause.INFRA_FAILURE,
     "基础设施故障（模型/服务器不可达）。不要重试同一任务，检查服务状态。",
     0.8),
    (re.compile(r"rate.?limit|too many requests|429", re.I),
     RootCause.INFRA_FAILURE,
     "速率限制。等待后重试或降低请求频率。",
     0.7),
]


def analyze_failure(
    stop_reason: str = "",
    summary: str = "",
    feedback: str = "",
    verify_output: str = "",
    content_len: int | None = None,
    extra: dict[str, Any] | None = None,
) -> RcaResult:
    """分析失败模式，判定根因。

    Args:
        stop_reason: orchestrator 的 stop_reason（verified/verify_failed/overseer_abort/...）
        summary: 失败摘要 / worker 输出
        feedback: 已有的 feedback 链
        verify_output: verify_cmd 的输出
        content_len: worker 生成的内容长度（用于检测 reasoning overflow）
        extra: 额外上下文

    Returns:
        RcaResult，包含根因分类 + 修复建议
    """
    extra = extra or {}
    # 合并所有文本用于模式匹配
    texts = [
        stop_reason or "",
        summary or "",
        feedback or "",
        verify_output or "",
        str(extra.get("error", "")),
    ]

    # 特殊检测：content_len 很小 → reasoning overflow（高优先级）
    if content_len is not None and content_len < 50:
        return RcaResult(
            cause=RootCause.REASONING_OVERFLOW,
            confidence=0.95,
            detail=f"content_len={content_len}（几乎无内容产出）",
            fix_suggestion="Kimi reasoning_content 占满 max_tokens。用最小 prompt 重试，确保 streaming 模式 + enable_thinking=false。",
        )

    # 规则匹配
    combined = "\n".join(texts)
    matches: list[tuple[float, RootCause, str]] = []
    for pattern, cause, fix, conf in _RULES:
        if pattern.search(combined):
            matches.append((conf, cause, fix))

    if not matches:
        # 检查 stop_reason 级别
        if stop_reason == "verify_failed":
            return RcaResult(
                cause=RootCause.VERIFY_MISMATCH,
                confidence=0.6,
                detail="verify_cmd 未通过",
                fix_suggestion="verify_cmd 失败。检查 verify_cmd 测的是什么，针对性修复。",
            )
        if stop_reason == "worker_error":
            return RcaResult(
                cause=RootCause.INFRA_FAILURE,
                confidence=0.5,
                detail="worker_error（执行器报错）",
                fix_suggestion="执行器报错。检查模型服务是否可用。",
            )
        if stop_reason == "loop_detected":
            return RcaResult(
                cause=RootCause.MAX_ITERATIONS,
                confidence=0.6,
                detail="循环检测触发",
                fix_suggestion="陷入循环。换不同方法，不要重复之前的动作。",
            )
        return RcaResult(
            cause=RootCause.UNKNOWN,
            confidence=0.3,
            detail=f"未分类失败 (stop_reason={stop_reason})",
            fix_suggestion="未知失败模式。检查 summary 和 feedback 获取线索。",
        )

    # 取置信度最高的匹配
    matches.sort(key=lambda x: x[0], reverse=True)
    best_conf, best_cause, best_fix = matches[0]

    # 提取相关详情：取第一个非空文本的前 200 字符
    detail = ""
    for text in texts:
        if text and text.strip():
            detail = text.strip()[:200]
            break

    return RcaResult(
        cause=best_cause,
        confidence=best_conf,
        detail=detail,
        fix_suggestion=best_fix,
        related_rules=[m[1].value for m in matches[1:3]],  # 其他匹配作为参考
    )


def enrich_feedback(base_feedback: str, rca: RcaResult, max_len: int = 300) -> str:
    """把 RCA 结果追加到 feedback（截断防 prompt 过长）。

    M11.1 教训：feedback 过长会触发 Kimi reasoning 循环，所以严格截断。
    """
    rca_text = rca.to_feedback()
    if len(rca_text) > max_len:
        rca_text = rca_text[:max_len]
    if not base_feedback:
        return rca_text
    # 截断 base_feedback 留空间给 RCA
    available = max_len - len(rca_text) - 2
    if available > 20:
        base_short = base_feedback[-available:] if len(base_feedback) > available else base_feedback
        return f"{base_short}\n{rca_text}"
    return rca_text
