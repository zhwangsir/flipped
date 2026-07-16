"""P3-4 · 错误场景自动化修复测试。"""
from __future__ import annotations

import pytest

from driving.auto_repair import (
    AutoRepairEngine,
    RepairStrategy,
    RepairAction,
    RepairResult,
)
from driving.errors import ConfigurationError, ComparisonError


class TestRepairStrategy:
    def test_strategy_enum(self):
        assert RepairStrategy.fill_default == "fill_default"
        assert RepairStrategy.manual_required == "manual_required"


class TestAutoRepairEngine:
    def test_detect_and_classify(self):
        engine = AutoRepairEngine()
        exc = ConfigurationError("bad param", context={"key": "x"})
        record = engine.detect_and_classify(exc)
        assert record.error_type == "ConfigurationError"
        assert record.context["key"] == "x"

    def test_match_strategy_for_config_error(self):
        engine = AutoRepairEngine()
        record = engine.detect_and_classify(ConfigurationError("bad"))
        strategy = engine.match_strategy(record)
        assert strategy == RepairStrategy.inject_safe_value

    def test_match_strategy_for_comparison_error(self):
        engine = AutoRepairEngine()
        record = engine.detect_and_classify(ComparisonError("dim missing"))
        strategy = engine.match_strategy(record)
        assert strategy == RepairStrategy.align_dimensions

    def test_match_strategy_unrecoverable(self):
        engine = AutoRepairEngine()
        from driving.errors import AutoRepairError
        record = engine.detect_and_classify(AutoRepairError("can't fix"))
        strategy = engine.match_strategy(record)
        assert strategy == RepairStrategy.manual_required

    def test_fill_default_fixes_missing_key(self):
        engine = AutoRepairEngine()
        exc = ComparisonError("dim missing", context={"dimension": "design"})
        data = {"correctness": 90, "completeness": 85}
        fixed, actions = engine.apply_fix(engine.detect_and_classify(exc), data)
        assert "design" in fixed
        assert fixed["design"] == 50.0
        assert len(actions) == 1

    def test_clamp_range_fixes_overflow(self):
        engine = AutoRepairEngine()
        from driving.errors import ErrorRecord
        record = ErrorRecord(error_type="IndexError", message="out of range")
        data = {"score": 150.0, "score2": -10.0}
        fixed, actions = engine.apply_fix(record, data, strategy=RepairStrategy.clamp_range)
        assert fixed["score"] == 100.0
        assert fixed["score2"] == 0.0
        assert len(actions) == 2

    def test_align_dimensions(self):
        engine = AutoRepairEngine()
        record = engine.detect_and_classify(
            ComparisonError("missing dims", context={"dimensions": ["a", "b", "c"]})
        )
        data = {"a": 90}
        fixed, actions = engine.apply_fix(record, data)
        assert "b" in fixed and "c" in fixed
        assert fixed["b"] == 50.0

    def test_repair_full_flow_success(self):
        engine = AutoRepairEngine()
        exc = ComparisonError("dim missing", context={"dimension": "design"})
        data = {"correctness": 90, "completeness": 85}

        def validate(d):
            for k in ["correctness", "completeness", "design"]:
                if k not in d:
                    raise ValueError(f"missing {k}")

        result = engine.repair(exc, data, validate_fn=validate)
        assert result.success is True
        assert result.attempts >= 1
        assert len(result.actions) >= 1

    def test_repair_manual_required_raises(self):
        from driving.errors import AutoRepairError
        engine = AutoRepairEngine()
        exc = AutoRepairError("unrecoverable")
        result = engine.repair(exc, {})
        assert result.success is False

    def test_repair_with_verify_failure_then_success(self):
        engine = AutoRepairEngine(max_attempts=3)
        exc = ComparisonError("missing", context={"dimension": "x"})

        call_count = [0]
        def validate(d):
            call_count[0] += 1
            if call_count[0] < 2:
                raise ValueError("still bad")
            # Second attempt passes

        result = engine.repair(exc, {"a": 1}, validate_fn=validate)
        assert result.attempts >= 1

    def test_get_stats_empty(self):
        engine = AutoRepairEngine()
        stats = engine.get_stats()
        assert stats["total_repairs"] == 0

    def test_get_stats_after_repairs(self):
        engine = AutoRepairEngine()
        exc = ComparisonError("missing", context={"dimension": "x"})
        engine.repair(exc, {"a": 1})
        stats = engine.get_stats()
        assert stats["total_repairs"] == 1
        assert stats["success_rate"] > 0


class TestRepairResult:
    def test_to_dict(self):
        r = RepairResult(success=True, attempts=2)
        d = r.to_dict()
        assert d["success"] is True
        assert d["attempts"] == 2
