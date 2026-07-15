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


def test_design_violation_required_hex_exact():
    """required_hex_exact 违规 → design_violation，fix_suggestion 含 hex 提示。"""
    r = analyze_failure(
        summary="design-lint: ❌ 未通过 | [error]required_hex_exact:hex缺失:#0d0d12,#f5f5f5。必须用这些精确值",
    )
    assert r.cause == RootCause.DESIGN_VIOLATION
    assert "hex" in r.fix_suggestion.lower()


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


# ---- M91.1 RCA + Gold Memory 语义检索集成 ----

import tempfile

from driving.gold_memory import query_similar_failures, record_task_result
from driving.factory_loop import FactoryTask, FactoryState, TaskResult
from driving.rca import analyze_failure_with_memory, reset_failure_counter


def _make_task(desc: str = "实现登录页面", verify_cmd: list[str] | None = None) -> FactoryTask:
    return FactoryTask(
        id="t1", description=desc,
        verify_cmd=verify_cmd or ["pytest", "tests/"],
    )


def _make_state() -> FactoryState:
    return FactoryState(factory_id="f1", product_goal="G", cwd="/tmp", roadmap=[])


def _make_result(task: FactoryTask, success: bool, stop_reason: str = "verified",
                 summary: str = "") -> TaskResult:
    return TaskResult(
        task=task, verified=success, stop_reason=stop_reason,
        iteration=1, summary=summary,
    )


def test_query_similar_failures_returns_only_failures():
    """query_similar_failures 只返回失败记录,不含成功的。

    Gold Memory 表 UNIQUE(task_signature, design_style, verify_cmd),
    用相同 description(同签名)+ 不同 verify_cmd 创建多条记录。
    测试环境无 sentence-transformers,走签名 fallback 精确匹配。
    """
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db = f.name
    try:
        state = _make_state()
        desc = "实现登录页面"
        # 1 成功(verify_cmd=npm test)
        task_ok = _make_task(desc, ["npm", "test"])
        record_task_result(task_ok, state, _make_result(task_ok, True, "verified", "ok"), db_path=db)
        # 2 失败(不同 verify_cmd 避免 UNIQUE 覆盖)
        task_f1 = _make_task(desc, ["pytest", "-x"])
        task_f2 = _make_task(desc, ["make", "test"])
        record_task_result(task_f1, state, _make_result(task_f1, False, "verify_failed", "assertion error"), db_path=db)
        record_task_result(task_f2, state, _make_result(task_f2, False, "worker_error", "timeout"), db_path=db)

        failures = query_similar_failures(desc, db_path=db, limit=5)
        assert len(failures) == 2, f"应返回 2 条失败, 实 {len(failures)}"
        assert all(not f.success for f in failures)
        reasons = {f.stop_reason for f in failures}
        assert "verify_failed" in reasons
        assert "worker_error" in reasons
    finally:
        Path(db).unlink(missing_ok=True)


def test_query_similar_failures_empty_db():
    """空库返回空列表。"""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db = f.name
    try:
        failures = query_similar_failures("不存在的任务", db_path=db)
        assert failures == []
    finally:
        Path(db).unlink(missing_ok=True)


def test_analyze_failure_with_memory_enhances_hint():
    """有历史失败时,RcaResult.history_hint 非空。"""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db = f.name
    try:
        task = _make_task("创建登录表单", ["pytest", "-x"])
        state = _make_state()
        # 记录一条历史失败:语法错误
        record_task_result(
            task, state,
            _make_result(task, False, "verify_failed", "SyntaxError: unexpected indent"),
            db_path=db,
        )

        r = analyze_failure_with_memory(
            stop_reason="verify_failed",
            summary="SyntaxError: unexpected indent (line 3)",
            task_description="创建登录表单",
            db_path=db,
        )
        assert r.cause == RootCause.SYNTAX_ERROR
        assert r.history_hint, "有历史失败时 history_hint 应非空"
        assert "SyntaxError" in r.history_hint or "语法" in r.history_hint
    finally:
        Path(db).unlink(missing_ok=True)


def test_analyze_failure_with_memory_no_history():
    """无历史失败时,history_hint 为空字符串。"""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db = f.name
    try:
        r = analyze_failure_with_memory(
            stop_reason="verify_failed",
            summary="AssertionError",
            task_description="全新任务没有历史",
            db_path=db,
        )
        assert r.cause == RootCause.VERIFY_MISMATCH
        assert r.history_hint == ""
    finally:
        Path(db).unlink(missing_ok=True)


def test_to_feedback_includes_history_hint():
    """to_feedback 包含 history_hint。"""
    r = RcaResult(
        cause=RootCause.SYNTAX_ERROR,
        confidence=0.85,
        fix_suggestion="检查缩进",
        history_hint="历史类似失败: SyntaxError (2次)",
    )
    fb = r.to_feedback()
    assert "历史" in fb or "history" in fb.lower()


# ---- M91.2 RCA 失败模式频率统计 ----

from driving.rca import get_failure_counter


def test_failure_counter_consecutive():
    """连续同类失败计数递增。"""
    reset_failure_counter()
    analyze_failure(summary="SyntaxError: line 1")
    analyze_failure(summary="SyntaxError: line 2")
    analyze_failure(summary="SyntaxError: line 3")
    assert get_failure_counter().get(RootCause.SYNTAX_ERROR, 0) == 3


def test_failure_counter_reset_on_different_cause():
    """不同根因重置计数。"""
    reset_failure_counter()
    analyze_failure(summary="SyntaxError")
    analyze_failure(summary="SyntaxError")
    assert get_failure_counter().get(RootCause.SYNTAX_ERROR, 0) == 2
    analyze_failure(summary="ConnectionError: refused")  # 不同根因
    assert get_failure_counter().get(RootCause.SYNTAX_ERROR, 0) == 0
    assert get_failure_counter().get(RootCause.INFRA_FAILURE, 0) == 1


def test_failure_counter_escalation():
    """连续 3 次同类失败后,fix_suggestion 追加升级策略。"""
    reset_failure_counter()
    r1 = analyze_failure(summary="SyntaxError: line 1")
    r2 = analyze_failure(summary="SyntaxError: line 2")
    r3 = analyze_failure(summary="SyntaxError: line 3")
    assert "换策略" in r3.fix_suggestion or "升级" in r3.fix_suggestion or "换模型" in r3.fix_suggestion, \
        "连续 3 次应升级建议"
    # 前 2 次不应有升级
    assert "换策略" not in r1.fix_suggestion
    assert "换策略" not in r2.fix_suggestion


def test_failure_counter_reset_function():
    """reset_failure_counter() 清空计数。"""
    reset_failure_counter()
    analyze_failure(summary="SyntaxError")
    analyze_failure(summary="SyntaxError")
    assert get_failure_counter().get(RootCause.SYNTAX_ERROR, 0) == 2
    reset_failure_counter()
    assert get_failure_counter() == {}


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
