"""P4-1 · 修复知识库沉淀测试。"""
from __future__ import annotations

import os
import tempfile
import sqlite3

from driving.repair_kb import (
    RepairKnowledge,
    RepairKBStats,
    save_repair_knowledge,
    get_repair_warnings,
    build_repair_warning_text,
    get_repair_kb_stats,
)
from driving.auto_repair import AutoRepairEngine, RepairResult, RepairAction, RepairStrategy
from driving.errors import ComparisonError, ErrorRecord


def _make_db() -> str:
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    conn = sqlite3.connect(path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS failures (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            failure_id TEXT NOT NULL UNIQUE,
            task_description TEXT NOT NULL,
            task_description_vector TEXT NOT NULL DEFAULT '',
            design_style TEXT NOT NULL DEFAULT 'auto',
            cause TEXT NOT NULL DEFAULT 'unknown',
            error_detail TEXT NOT NULL DEFAULT '',
            stop_reason TEXT NOT NULL DEFAULT '',
            iterations INTEGER NOT NULL DEFAULT 1,
            resolved INTEGER NOT NULL DEFAULT 0,
            resolution TEXT NOT NULL DEFAULT '',
            timestamp TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()
    return path


class TestRepairKnowledge:
    def test_to_dict(self):
        k = RepairKnowledge(
            task_description="test",
            error_type="ComparisonError",
            error_message="missing dim",
            repair_strategy="align_dimensions",
            repair_actions=[],
            success=True,
            attempts=2,
            reusable=True,
        )
        d = k.to_dict()
        assert d["error_type"] == "ComparisonError"
        assert d["success"] is True
        assert d["reusable"] is True


class TestSaveRepairKnowledge:
    def test_save_successful_repair(self):
        db_path = _make_db()
        engine = AutoRepairEngine()
        exc = ComparisonError("dim missing", context={"dimension": "design"})
        repair_result = engine.repair(exc, {"correctness": 90})

        knowledge = save_repair_knowledge("test task", repair_result, db_path=db_path)
        assert knowledge is not None
        assert knowledge.task_description == "test task"
        assert knowledge.success is True

    def test_save_none_when_no_error(self):
        db_path = _make_db()
        repair_result = RepairResult(success=True, error_before=None)
        knowledge = save_repair_knowledge("test", repair_result, db_path=db_path)
        assert knowledge is None


class TestGetRepairWarnings:
    def test_empty_warnings(self):
        db_path = _make_db()
        warnings = get_repair_warnings("nonexistent task", db_path=db_path)
        assert isinstance(warnings, list)

    def test_returns_warnings_after_save(self):
        db_path = _make_db()
        engine = AutoRepairEngine()
        exc = ComparisonError("dim missing", context={"dimension": "design"})
        repair_result = engine.repair(exc, {"correctness": 90})

        save_repair_knowledge("build a landing page", repair_result, db_path=db_path)

        warnings = get_repair_warnings("build a landing page", db_path=db_path)
        assert isinstance(warnings, list)


class TestBuildRepairWarningText:
    def test_empty_text(self):
        db_path = _make_db()
        text = build_repair_warning_text("nonexistent", db_path=db_path)
        assert text == ""

    def test_text_after_save(self):
        db_path = _make_db()
        engine = AutoRepairEngine()
        exc = ComparisonError("dim missing", context={"dimension": "design"})
        repair_result = engine.repair(exc, {"correctness": 90})

        save_repair_knowledge("test task desc", repair_result, db_path=db_path)

        text = build_repair_warning_text("test task desc", db_path=db_path)
        assert isinstance(text, str)


class TestRepairKBStats:
    def test_to_dict(self):
        stats = RepairKBStats(
            total_repairs_recorded=10,
            successful_repairs=8,
            failed_repairs=2,
        )
        d = stats.to_dict()
        assert d["total_repairs_recorded"] == 10
        assert d["success_rate"] == 0.8

    def test_get_repair_kb_stats(self):
        db_path = _make_db()
        stats = get_repair_kb_stats(db_path=db_path)
        assert isinstance(stats, RepairKBStats)
        assert stats.total_repairs_recorded >= 0
