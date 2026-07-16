"""M105 · 失败知识库测试。

失败模式形成知识库，下次遇到同类问题自动预警 + 注入规避策略。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from driving.failure_kb import (
    FailureEntry,
    record_failure,
    query_similar_failures,
    get_failure_stats,
    build_warning_from_history,
    FailureStats,
)


class TestRecordFailure:
    def test_record_basic_failure(self, tmp_path):
        db = str(tmp_path / "failures.db")
        entry = record_failure(
            task_description="build landing page with dark mode",
            design_style="film_atelier",
            cause="syntax_error",
            error_detail="Uncaught SyntaxError: Unexpected token",
            stop_reason="verify_failed",
            iterations=2,
            resolved=False,
            db_path=db,
        )
        assert entry is not None
        assert entry.failure_id != ""
        assert entry.cause == "syntax_error"
        assert entry.resolved is False

    def test_record_resolved_failure(self, tmp_path):
        db = str(tmp_path / "failures.db")
        entry = record_failure(
            task_description="fix button alignment",
            design_style="dark",
            cause="css_mismatch",
            error_detail="Button not centered",
            stop_reason="verify_failed",
            iterations=3,
            resolved=True,
            resolution="Added display: flex + justify-content: center",
            db_path=db,
        )
        assert entry.resolved is True
        assert "flex" in entry.resolution

    def test_empty_db_query_returns_empty(self, tmp_path):
        db = str(tmp_path / "failures.db")
        results = query_similar_failures("any task", db_path=db)
        assert results == []


class TestQuerySimilarFailures:
    def test_finds_similar_by_description(self, tmp_path):
        db = str(tmp_path / "failures.db")
        record_failure(
            "build dark landing page with hero section",
            "dark",
            cause="syntax_error",
            error_detail="Missing closing tag",
            stop_reason="verify_failed",
            iterations=1,
            resolved=False,
            db_path=db,
        )
        record_failure(
            "create pricing table component",
            "dark",
            cause="missing_import",
            error_detail="React not defined",
            stop_reason="verify_failed",
            iterations=2,
            resolved=True,
            resolution="import React from 'react'",
            db_path=db,
        )

        results = query_similar_failures("dark landing page hero", db_path=db)
        assert len(results) >= 1

    def test_query_limits_results(self, tmp_path):
        db = str(tmp_path / "failures.db")
        for i in range(10):
            record_failure(
                f"task {i} about css styling",
                "dark",
                cause="css_error",
                error_detail=f"error {i}",
                stop_reason="verify_failed",
                iterations=1,
                resolved=False,
                db_path=db,
            )

        results = query_similar_failures("css styling", db_path=db, max_results=3)
        assert len(results) <= 3


class TestFailureStats:
    def test_stats_aggregates_by_cause(self, tmp_path):
        db = str(tmp_path / "failures.db")
        causes = ["syntax_error", "syntax_error", "missing_import", "timeout", "syntax_error"]
        for i, cause in enumerate(causes):
            record_failure(
                f"task {i}",
                "auto",
                cause=cause,
                error_detail=f"error {i}",
                stop_reason="failed",
                iterations=1,
                resolved=(i % 2 == 0),
                db_path=db,
            )

        stats = get_failure_stats(db_path=db)
        assert stats.total_failures == 5
        assert "syntax_error" in stats.by_cause
        assert stats.by_cause["syntax_error"] == 3

    def test_stats_empty_db(self, tmp_path):
        db = str(tmp_path / "failures.db")
        stats = get_failure_stats(db_path=db)
        assert stats.total_failures == 0
        assert stats.by_cause == {}


class TestBuildWarning:
    def test_warning_includes_history(self, tmp_path):
        db = str(tmp_path / "failures.db")
        record_failure(
            "build landing page",
            "film_atelier",
            cause="syntax_error",
            error_detail="Unclosed div tag",
            stop_reason="verify_failed",
            iterations=2,
            resolved=True,
            resolution="Check HTML tag nesting",
            db_path=db,
        )

        warning = build_warning_from_history(
            "build landing page with dark mode",
            "film_atelier",
            db_path=db,
        )
        assert isinstance(warning, str)
        assert len(warning) > 0

    def test_no_history_returns_empty_string(self, tmp_path):
        db = str(tmp_path / "failures.db")
        warning = build_warning_from_history(
            "completely new task",
            "auto",
            db_path=db,
        )
        assert warning == ""


class TestFailureEntryDataclass:
    def test_entry_has_expected_fields(self):
        entry = FailureEntry(
            failure_id="f1",
            task_description="test",
            design_style="auto",
            cause="unknown",
            error_detail="something broke",
            stop_reason="failed",
            iterations=1,
            resolved=False,
            resolution="",
            timestamp="2024-01-01T00:00:00+00:00",
        )
        assert entry.failure_id == "f1"
        assert entry.cause == "unknown"
        assert entry.resolved is False
