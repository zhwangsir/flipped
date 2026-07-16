"""P3-2 · 结构化日志测试。"""
from __future__ import annotations

import io
import json

from driving.structured_logger import (
    LogLevel,
    LogEntry,
    StructuredLogger,
    make_logger,
)


class TestLogLevel:
    def test_priority_order(self):
        from driving.structured_logger import _LEVEL_PRIORITY
        assert _LEVEL_PRIORITY[LogLevel.trace] < _LEVEL_PRIORITY[LogLevel.debug]
        assert _LEVEL_PRIORITY[LogLevel.debug] < _LEVEL_PRIORITY[LogLevel.info]
        assert _LEVEL_PRIORITY[LogLevel.info] < _LEVEL_PRIORITY[LogLevel.warn]
        assert _LEVEL_PRIORITY[LogLevel.warn] < _LEVEL_PRIORITY[LogLevel.error]
        assert _LEVEL_PRIORITY[LogLevel.error] < _LEVEL_PRIORITY[LogLevel.fatal]


class TestLogEntry:
    def test_to_dict(self):
        e = LogEntry(
            timestamp="2026-01-01T00:00:00Z",
            level="INFO",
            module="test",
            function="run",
            event="started",
            payload={"task": "build"},
        )
        d = e.to_dict()
        assert d["level"] == "INFO"
        assert d["event"] == "started"
        assert d["payload"]["task"] == "build"

    def test_to_json(self):
        e = LogEntry(
            timestamp="2026-01-01T00:00:00Z",
            level="INFO",
            module="test",
            function="run",
            event="done",
        )
        j = json.loads(e.to_json())
        assert j["event"] == "done"


class TestStructuredLogger:
    def test_info_logs_to_stream(self):
        buf = io.StringIO()
        logger = StructuredLogger(stream=buf, min_level=LogLevel.info, module_name="m")
        logger.info("test_event", {"key": "val"})
        output = buf.getvalue()
        assert "test_event" in output
        parsed = json.loads(output.strip())
        assert parsed["event"] == "test_event"
        assert parsed["payload"]["key"] == "val"

    def test_trace_filtered_below_min_level(self):
        buf = io.StringIO()
        logger = StructuredLogger(stream=buf, min_level=LogLevel.info)
        logger.trace("should_not_appear")
        assert buf.getvalue() == ""

    def test_all_levels_emitted(self):
        buf = io.StringIO()
        logger = StructuredLogger(stream=buf, min_level=LogLevel.trace)
        logger.trace("t")
        logger.debug("d")
        logger.info("i")
        logger.warn("w")
        logger.error("e")
        logger.fatal("f")
        lines = [l for l in buf.getvalue().strip().split("\n") if l]
        assert len(lines) == 6

    def test_entries_stored_in_memory(self):
        logger = StructuredLogger(min_level=LogLevel.info)
        logger.info("event1")
        logger.warn("event2")
        assert len(logger.entries) == 2

    def test_get_entries_by_level(self):
        logger = StructuredLogger(min_level=LogLevel.trace)
        logger.info("a")
        logger.error("b")
        errors = logger.get_entries(level=LogLevel.error)
        assert len(errors) == 1
        assert errors[0].event == "b"

    def test_trace_id_propagates(self):
        logger = StructuredLogger(trace_id="abc-123", min_level=LogLevel.info)
        logger.info("test")
        assert logger.entries[0].trace_id == "abc-123"


class TestMakeLogger:
    def test_factory(self):
        logger = make_logger("test_module", trace_id="xyz", min_level=LogLevel.debug)
        assert logger.module_name == "test_module"
        assert logger.trace_id == "xyz"
