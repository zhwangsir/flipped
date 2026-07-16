"""P3-1 · 异常分级体系测试。"""
from __future__ import annotations

import pytest

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


class TestFlippedError:
    def test_base_error_carries_context(self):
        err = FlippedError("something broke", context={"module": "test"})
        assert err.message == "something broke"
        assert err.context["module"] == "test"

    def test_to_dict(self):
        err = ConfigurationError("bad config", context={"key": "target_win_rate"})
        d = err.to_dict()
        assert d["error_type"] == "ConfigurationError"
        assert d["message"] == "bad config"
        assert d["context"]["key"] == "target_win_rate"


class TestExceptionHierarchy:
    def test_all_subclass_flipped_error(self):
        for cls in [ConfigurationError, ValidationError, ComparisonError, LoopError, AutoRepairError]:
            assert issubclass(cls, FlippedError)

    def test_catch_base_catches_all(self):
        for cls in [ConfigurationError, ValidationError, ComparisonError]:
            with pytest.raises(FlippedError):
                raise cls("test")


class TestErrorRecord:
    def test_to_dict(self):
        rec = ErrorRecord(
            error_type="ConfigurationError",
            message="bad value",
            module="self_improvement_loop",
            function="__post_init__",
            recoverable=True,
            suggested_fix="check range",
        )
        d = rec.to_dict()
        assert d["error_type"] == "ConfigurationError"
        assert d["recoverable"] is True


class TestClassifyException:
    def test_classify_flipped_error(self):
        err = ConfigurationError("bad config", context={"param": "x"})
        rec = classify_exception(err)
        assert rec.error_type == "ConfigurationError"
        assert rec.recoverable is True
        assert rec.context["param"] == "x"

    def test_classify_value_error(self):
        rec = classify_exception(ValueError("bad value"))
        assert rec.error_type == "ValueError"
        assert rec.recoverable is True

    def test_classify_key_error(self):
        rec = classify_exception(KeyError("missing_key"))
        assert rec.error_type == "KeyError"
        assert rec.recoverable is True

    def test_classify_type_error(self):
        rec = classify_exception(TypeError("wrong type"))
        assert rec.error_type == "TypeError"
        assert rec.recoverable is True

    def test_classify_unknown_error(self):
        rec = classify_exception(RuntimeError("unknown"))
        assert rec.recoverable is False

    def test_classify_auto_repair_unrecoverable(self):
        err = AutoRepairError("cannot fix")
        rec = classify_exception(err)
        assert rec.recoverable is False
