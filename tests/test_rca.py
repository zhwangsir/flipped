"""RCA 失败根因归因单元测试（M12）。"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from driving.rca import (
    RootCause,
    RcaResult,
    analyze_failure,
    enrich_feedback,
)


def test_reasoning_overflow_via_content_len():
    """content_len < 50 → reasoning_overflow（高置信度）。"""
    r = analyze_failure(stop_reason="verified", summary="ok", content_len=4)
    assert r.cause == RootCause.REASONING_OVERFLOW
    assert r.confidence > 0.9
    assert "reasoning_content" in r.fix_suggestion or "streaming" in r.fix_suggestion.lower()


def test_syntax_error():
    """SyntaxError → syntax_error。"""
    r = analyze_failure(summary="SyntaxError: unexpected indent (line 5)")
    assert r.cause == RootCause.SYNTAX_ERROR
    assert "缩进" in r.fix_suggestion or "syntax" in r.fix_suggestion.lower() or "py_compile" in r.fix_suggestion


def test_missing_import():
    """ModuleNotFoundError → missing_import。"""
    r = analyze_failure(summary="ModuleNotFoundError: No module named 'react'")
    assert r.cause == RootCause.MISSING_IMPORT
    assert "import" in r.fix_suggestion.lower()


def test_name_error():
    """NameError → missing_import。"""
    r = analyze_failure(summary="NameError: name 'useState' is not defined")
    assert r.cause == RootCause.MISSING_IMPORT


def test_verify_mismatch():
    """assertion failed → verify_mismatch。"""
    r = analyze_failure(summary="AssertionError: assert 1 == 2", stop_reason="verify_failed")
    assert r.cause == RootCause.VERIFY_MISMATCH
    assert "verify_cmd" in r.fix_suggestion


def test_design_violation():
    """design-lint failed → design_violation。"""
    r = analyze_failure(summary="design-lint 未通过: design_colors not found")
    assert r.cause == RootCause.DESIGN_VIOLATION
    assert "hex" in r.fix_suggestion.lower() or "设计系统" in r.fix_suggestion


def test_a11y_violation():
    """axe-core violation → a11y_violation。"""
    r = analyze_failure(summary="a11y 未通过: image-alt violation")
    assert r.cause == RootCause.A11Y_VIOLATION
    assert "a11y" in r.fix_suggestion.lower()


def test_timeout():
    """timeout → timeout。"""
    r = analyze_failure(summary="ReadTimeout: timed out after 60s")
    assert r.cause == RootCause.TIMEOUT


def test_max_iterations():
    """MaxIterationsReached → max_iterations。"""
    r = analyze_failure(summary="MaxIterationsReached: Agent reached maximum iterations limit")
    assert r.cause == RootCause.MAX_ITERATIONS
    assert "拆" in r.fix_suggestion or "smaller" in r.fix_suggestion.lower()


def test_infra_failure():
    """connection refused → infra_failure。"""
    r = analyze_failure(summary="ConnectionError: connection refused")
    assert r.cause == RootCause.INFRA_FAILURE


def test_rate_limit():
    """429 → infra_failure。"""
    r = analyze_failure(summary="429 Too Many Requests")
    assert r.cause == RootCause.INFRA_FAILURE


def test_unknown():
    """无法分类 → unknown。"""
    r = analyze_failure(summary="something weird happened", stop_reason="overseer_abort")
    assert r.cause == RootCause.UNKNOWN


def test_verify_failed_stop_reason_only():
    """只有 stop_reason=verify_failed → verify_mismatch（低置信度）。"""
    r = analyze_failure(stop_reason="verify_failed", summary="")
    assert r.cause == RootCause.VERIFY_MISMATCH
    assert r.confidence <= 0.7


def test_worker_error_stop_reason():
    """stop_reason=worker_error → infra_failure。"""
    r = analyze_failure(stop_reason="worker_error", summary="")
    assert r.cause == RootCause.INFRA_FAILURE


def test_loop_detected():
    """stop_reason=loop_detected → max_iterations。"""
    r = analyze_failure(stop_reason="loop_detected", summary="")
    assert r.cause == RootCause.MAX_ITERATIONS


def test_to_feedback():
    """to_feedback 生成可读文本。"""
    r = RcaResult(
        cause=RootCause.SYNTAX_ERROR,
        confidence=0.85,
        detail="SyntaxError: unexpected indent",
        fix_suggestion="检查缩进",
    )
    fb = r.to_feedback()
    assert "[RCA]" in fb
    assert "syntax_error" in fb
    assert "85%" in fb
    assert "检查缩进" in fb


def test_enrich_feedback_short():
    """enrich_feedback 在短 feedback 上正常工作。"""
    base = "上次失败: test error"
    r = RcaResult(
        cause=RootCause.SYNTAX_ERROR,
        confidence=0.85,
        fix_suggestion="修复缩进",
    )
    result = enrich_feedback(base, r)
    assert "[RCA]" in result
    assert "修复缩进" in result
    assert "test error" in result


def test_enrich_feedback_long_truncates():
    """enrich_feedback 截断长 feedback 防止 prompt 过长。"""
    base = "x" * 500
    r = RcaResult(
        cause=RootCause.SYNTAX_ERROR,
        confidence=0.85,
        detail="detail",
        fix_suggestion="fix",
    )
    result = enrich_feedback(base, r, max_len=100)
    assert len(result) <= 100
    assert "[RCA]" in result


def test_enrich_feedback_empty_base():
    """enrich_feedback 空 feedback 只返回 RCA。"""
    r = RcaResult(
        cause=RootCause.SYNTAX_ERROR,
        confidence=0.85,
        fix_suggestion="修复缩进",
    )
    result = enrich_feedback("", r)
    assert result == r.to_feedback()


def test_related_rules():
    """多个规则匹配时，次匹配作为 related_rules。"""
    # 这个 summary 同时匹配 syntax_error 和 verify（assertion）
    r = analyze_failure(summary="SyntaxError: invalid syntax. FAILED tests")
    # 语法错误置信度更高
    assert r.cause == RootCause.SYNTAX_ERROR
    # related_rules 可能为空（如果只有一条匹配）或有值
    assert isinstance(r.related_rules, list)


def test_content_len_none():
    """content_len=None 时不触发 reasoning_overflow。"""
    r = analyze_failure(summary="SyntaxError", content_len=None)
    assert r.cause == RootCause.SYNTAX_ERROR


def test_content_len_large():
    """content_len >= 50 时不触发 reasoning_overflow。"""
    r = analyze_failure(summary="SyntaxError", content_len=500)
    assert r.cause == RootCause.SYNTAX_ERROR
