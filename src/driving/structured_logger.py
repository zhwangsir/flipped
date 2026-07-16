"""P3-2 · 结构化日志。

为循环引擎每步留下审计轨迹，支持 JSON 格式输出，便于后续追溯。

日志级别：
    TRACE < DEBUG < INFO < WARN < ERROR < FATAL

每条日志携带：
    timestamp, level, module, function, event, payload, trace_id
"""
from __future__ import annotations

import json
import logging
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, TextIO


class LogLevel(str, Enum):
    trace = "TRACE"
    debug = "DEBUG"
    info = "INFO"
    warn = "WARN"
    error = "ERROR"
    fatal = "FATAL"


_LEVEL_PRIORITY = {
    LogLevel.trace: 0,
    LogLevel.debug: 1,
    LogLevel.info: 2,
    LogLevel.warn: 3,
    LogLevel.error: 4,
    LogLevel.fatal: 5,
}


@dataclass
class LogEntry:
    """单条结构化日志。"""
    timestamp: str
    level: str
    module: str
    function: str
    event: str
    payload: dict[str, Any] = field(default_factory=dict)
    trace_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "level": self.level,
            "module": self.module,
            "function": self.function,
            "event": self.event,
            "payload": self.payload,
            "trace_id": self.trace_id,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, default=str)


@dataclass
class StructuredLogger:
    """结构化日志记录器。

    stream: 输出流，默认 stderr。
    min_level: 最低输出级别，低于此级别不输出。
    trace_id: 追踪 ID，贯穿整个任务生命周期。
    """
    stream: TextIO = field(default_factory=lambda: sys.stderr)
    min_level: LogLevel = LogLevel.info
    trace_id: str = ""
    entries: list[LogEntry] = field(default_factory=list)
    module_name: str = ""

    def _emit(self, level: LogLevel, event: str, payload: dict[str, Any], function: str = "") -> LogEntry:
        entry = LogEntry(
            timestamp=datetime.now(timezone.utc).isoformat(),
            level=level.value,
            module=self.module_name,
            function=function,
            event=event,
            payload=payload,
            trace_id=self.trace_id,
        )
        self.entries.append(entry)
        if _LEVEL_PRIORITY[level] >= _LEVEL_PRIORITY[self.min_level]:
            self.stream.write(entry.to_json() + "\n")
            self.stream.flush()
        return entry

    def trace(self, event: str, payload: dict[str, Any] | None = None, *, function: str = "") -> LogEntry:
        return self._emit(LogLevel.trace, event, payload or {}, function)

    def debug(self, event: str, payload: dict[str, Any] | None = None, *, function: str = "") -> LogEntry:
        return self._emit(LogLevel.debug, event, payload or {}, function)

    def info(self, event: str, payload: dict[str, Any] | None = None, *, function: str = "") -> LogEntry:
        return self._emit(LogLevel.info, event, payload or {}, function)

    def warn(self, event: str, payload: dict[str, Any] | None = None, *, function: str = "") -> LogEntry:
        return self._emit(LogLevel.warn, event, payload or {}, function)

    def error(self, event: str, payload: dict[str, Any] | None = None, *, function: str = "") -> LogEntry:
        return self._emit(LogLevel.error, event, payload or {}, function)

    def fatal(self, event: str, payload: dict[str, Any] | None = None, *, function: str = "") -> LogEntry:
        return self._emit(LogLevel.fatal, event, payload or {}, function)

    def get_entries(self, *, level: LogLevel | None = None) -> list[LogEntry]:
        if level is None:
            return list(self.entries)
        return [e for e in self.entries if e.level == level.value]

    def to_dict(self) -> dict[str, Any]:
        return {
            "module": self.module_name,
            "trace_id": self.trace_id,
            "total_entries": len(self.entries),
            "entries": [e.to_dict() for e in self.entries],
        }


def make_logger(module_name: str = "", *, trace_id: str = "", min_level: LogLevel = LogLevel.info) -> StructuredLogger:
    """便捷工厂函数。"""
    return StructuredLogger(
        module_name=module_name,
        trace_id=trace_id,
        min_level=min_level,
        stream=open(sys.stderr.fileno(), "w", closefd=False),
    )
