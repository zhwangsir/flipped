"""M105 · 失败知识库测试。

失败模式形成知识库，下次遇到同类问题自动预警 + 注入规避策略。
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import MagicMock

import pytest

import driving.failure_kb as fb_module
import driving.gold_memory as gm_module
from driving.failure_kb import (
    FailureEntry,
    _cosine_similarity,
    _embed,
    _enable_wal,
    _row_to_entry,
    build_warning_from_history,
    get_all_failures,
    get_failure_stats,
    query_similar_failures,
    record_failure,
    run_clustering_analysis,
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

    def test_record_failure_returns_none_on_connect_exception(self, monkeypatch, tmp_path):
        """record_failure 的 fail-open：connect 抛异常时返回 None（覆盖 L198-199）。"""
        def _raise(_path, **_kw):
            raise sqlite3.OperationalError("connect boom")

        monkeypatch.setattr(fb_module, "connect", _raise)
        result = record_failure(
            task_description="any task",
            design_style="auto",
            cause="x",
            error_detail="e",
            stop_reason="failed",
            iterations=1,
            resolved=False,
            db_path=str(tmp_path / "x.db"),
        )
        assert result is None


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


class TestEmbedFallback:
    """_embed 在 gold_memory 异常时 fail-open 返回 []。"""

    def test_embed_returns_empty_on_gold_memory_exception(self, monkeypatch):
        def _raise(_text):
            raise RuntimeError("gold_memory boom")

        monkeypatch.setattr(gm_module, "_embed", _raise)
        assert _embed("anything") == []

    def test_embed_returns_empty_on_import_error(self, monkeypatch):
        # 模拟 gold_memory 模块自身不可用：把 _embed 设为触发 ImportError 的 sentinel
        import builtins

        real_import = builtins.__import__

        def _fail_import(name, *args, **kwargs):
            if name == "driving.gold_memory":
                raise ImportError("simulated missing module")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", _fail_import)
        assert _embed("test") == []


class TestCosineSimilarity:
    """_cosine_similarity 的 fallback 路径（gold_memory 不可用时走纯数学实现）。"""

    def test_fallback_normal_vectors(self, monkeypatch):
        def _raise(_a, _b):
            raise RuntimeError("gold_memory boom")

        monkeypatch.setattr(gm_module, "_cosine_similarity", _raise)
        a = [1.0, 0.0, 0.0]
        b = [1.0, 0.0, 0.0]
        assert _cosine_similarity(a, b) == pytest.approx(1.0)

    def test_fallback_orthogonal_vectors(self, monkeypatch):
        def _raise(_a, _b):
            raise RuntimeError("gold_memory boom")

        monkeypatch.setattr(gm_module, "_cosine_similarity", _raise)
        a = [1.0, 0.0]
        b = [0.0, 1.0]
        assert _cosine_similarity(a, b) == pytest.approx(0.0)

    def test_fallback_empty_vectors(self, monkeypatch):
        def _raise(_a, _b):
            raise RuntimeError("gold_memory boom")

        monkeypatch.setattr(gm_module, "_cosine_similarity", _raise)
        assert _cosine_similarity([], []) == 0.0

    def test_fallback_length_mismatch(self, monkeypatch):
        def _raise(_a, _b):
            raise RuntimeError("gold_memory boom")

        monkeypatch.setattr(gm_module, "_cosine_similarity", _raise)
        assert _cosine_similarity([1.0, 2.0], [1.0]) == 0.0

    def test_fallback_zero_norm(self, monkeypatch):
        def _raise(_a, _b):
            raise RuntimeError("gold_memory boom")

        monkeypatch.setattr(gm_module, "_cosine_similarity", _raise)
        # 零向量 → 范数为 0 → 返回 0.0
        assert _cosine_similarity([0.0, 0.0], [1.0, 1.0]) == 0.0

    def test_uses_gold_memory_when_available(self, monkeypatch):
        # gold_memory 正常时走 gold_memory 实现
        captured = {}

        def _spy(a, b):
            captured["called"] = True
            captured["a"] = a
            captured["b"] = b
            return 0.42

        monkeypatch.setattr(gm_module, "_cosine_similarity", _spy)
        result = _cosine_similarity([1.0], [1.0])
        assert result == 0.42
        assert captured.get("called") is True


class TestEnableWal:
    """_enable_wal 异常 fail-open + 缓存。"""

    def test_enable_wal_swallows_exception(self, monkeypatch, tmp_path):
        db_path = str(tmp_path / "x.db")

        def _raise(_path, **_kw):
            raise sqlite3.OperationalError("simulated WAL failure")

        monkeypatch.setattr(fb_module, "connect", _raise)
        # 不抛异常即通过
        _enable_wal(db_path)
        # 失败时不应加入缓存集合
        assert db_path not in fb_module._wal_initialized

    def test_enable_wal_caches_success(self, monkeypatch, tmp_path):
        db_path = str(tmp_path / "y.db")
        call_count = {"n": 0}

        class _FakeConn:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def execute(self, _sql):
                call_count["n"] += 1

        def _connect(_path, **_kw):
            return _FakeConn()

        monkeypatch.setattr(fb_module, "connect", _connect)
        # 清掉可能存在的缓存
        fb_module._wal_initialized.discard(db_path)
        _enable_wal(db_path)
        first_count = call_count["n"]
        assert db_path in fb_module._wal_initialized
        # 第二次调用应跳过（缓存命中）
        _enable_wal(db_path)
        assert call_count["n"] == first_count


class TestQuerySimilarFailuresFallback:
    """query_similar_failures 的 fallback 与异常分支。"""

    def test_keyword_fallback_when_no_query_vec(self, monkeypatch, tmp_path):
        # embed 返回空 → 走关键词匹配 fallback
        monkeypatch.setattr(fb_module, "_embed", lambda _t: [])
        db = str(tmp_path / "f.db")
        record_failure(
            "css styling layout issue",
            "dark",
            cause="css_error",
            error_detail="flex broken",
            stop_reason="verify_failed",
            iterations=1,
            resolved=False,
            db_path=db,
        )
        record_failure(
            "completely different topic about database",
            "dark",
            cause="db_error",
            error_detail="connection refused",
            stop_reason="verify_failed",
            iterations=1,
            resolved=False,
            db_path=db,
        )
        # 查询包含 css 关键词 → 应匹配到第一条
        results = query_similar_failures("css styling", db_path=db)
        assert len(results) >= 1
        assert any("css" in r.task_description for r in results)

    def test_keyword_fallback_no_overlap_returns_empty(self, monkeypatch, tmp_path):
        monkeypatch.setattr(fb_module, "_embed", lambda _t: [])
        db = str(tmp_path / "f.db")
        record_failure(
            "alpha topic",
            "dark",
            cause="x",
            error_detail="e",
            stop_reason="failed",
            iterations=1,
            resolved=False,
            db_path=db,
        )
        # 完全不重叠的关键词
        results = query_similar_failures("zzz qqq", db_path=db)
        assert results == []

    def test_query_exception_returns_empty(self, monkeypatch, tmp_path):
        def _raise(_path, **_kw):
            raise sqlite3.OperationalError("connect boom")

        monkeypatch.setattr(fb_module, "connect", _raise)
        results = query_similar_failures("anything", db_path=str(tmp_path / "x.db"))
        assert results == []


class TestGetFailureStatsException:
    def test_stats_exception_returns_empty_stats(self, monkeypatch, tmp_path):
        def _raise(_path, **_kw):
            raise sqlite3.OperationalError("connect boom")

        monkeypatch.setattr(fb_module, "connect", _raise)
        stats = get_failure_stats(db_path=str(tmp_path / "x.db"))
        assert isinstance(stats, FailureStats)
        assert stats.total_failures == 0
        assert stats.resolved_count == 0
        assert stats.unresolved_count == 0
        assert stats.by_cause == {}
        assert stats.top_causes == []


class TestBuildWarningException:
    def test_warning_exception_returns_empty_string(self, monkeypatch, tmp_path):
        def _raise(_desc, _style, **_kw):
            raise RuntimeError("query boom")

        monkeypatch.setattr(fb_module, "query_similar_failures", _raise)
        result = build_warning_from_history("any", "auto", db_path=str(tmp_path / "x.db"))
        assert result == ""

    def test_warning_includes_unresolved_failure(self, monkeypatch, tmp_path):
        # 强制走关键词 fallback，确保有匹配结果
        monkeypatch.setattr(fb_module, "_embed", lambda _t: [])
        db = str(tmp_path / "f.db")
        record_failure(
            "build landing page broken",
            "film_atelier",
            cause="syntax_error",
            error_detail="Unclosed div tag",
            stop_reason="verify_failed",
            iterations=2,
            resolved=False,
            resolution="",
            db_path=db,
        )
        warning = build_warning_from_history("build landing page", "film_atelier", db_path=db)
        assert isinstance(warning, str)
        assert "历史教训" in warning
        assert "未解决" in warning


class TestGetAllFailures:
    """get_all_failures 行为测试。

    D-0015 修复后：SQL 用 ORDER BY timestamp DESC（与 schema 一致），
    函数能正确返回数据；fail-open 仅在真实异常时返回 []。
    """

    def test_returns_empty_on_fresh_db(self, tmp_path):
        db = str(tmp_path / "f.db")
        # 全新 db，无记录 → 返回 []
        assert get_all_failures(db_path=db) == []

    def test_returns_recorded_failure(self, tmp_path):
        db = str(tmp_path / "f.db")
        record_failure(
            "task one",
            "auto",
            cause="x",
            error_detail="e",
            stop_reason="failed",
            iterations=1,
            resolved=False,
            db_path=db,
        )
        result = get_all_failures(db_path=db)
        assert len(result) == 1
        assert result[0].task_description == "task one"
        assert result[0].cause == "x"
        assert result[0].resolved is False

    def test_with_resolved_filter_true(self, tmp_path):
        db = str(tmp_path / "f.db")
        record_failure(
            "task one",
            "auto",
            cause="x",
            error_detail="e",
            stop_reason="failed",
            iterations=1,
            resolved=True,
            db_path=db,
        )
        record_failure(
            "task two",
            "auto",
            cause="y",
            error_detail="e2",
            stop_reason="failed",
            iterations=1,
            resolved=False,
            db_path=db,
        )
        result = get_all_failures(db_path=db, resolved=True)
        assert len(result) == 1
        assert result[0].task_description == "task one"
        assert result[0].resolved is True

    def test_with_resolved_filter_false(self, tmp_path):
        db = str(tmp_path / "f.db")
        record_failure(
            "task one",
            "auto",
            cause="x",
            error_detail="e",
            stop_reason="failed",
            iterations=1,
            resolved=True,
            db_path=db,
        )
        record_failure(
            "task two",
            "auto",
            cause="y",
            error_detail="e2",
            stop_reason="failed",
            iterations=1,
            resolved=False,
            db_path=db,
        )
        result = get_all_failures(db_path=db, resolved=False)
        assert len(result) == 1
        assert result[0].task_description == "task two"
        assert result[0].resolved is False

    def test_with_limit(self, tmp_path):
        db = str(tmp_path / "f.db")
        for i in range(3):
            record_failure(
                f"task {i}",
                "auto",
                cause="x",
                error_detail=f"e{i}",
                stop_reason="failed",
                iterations=1,
                resolved=False,
                db_path=db,
            )
        result = get_all_failures(db_path=db, limit=2)
        assert len(result) == 2

    def test_orders_by_timestamp_desc_newest_first(self, tmp_path):
        """D-0015 回归守卫：验证 ORDER BY timestamp DESC 真正生效。

        旧 bug：列名写成 created_at → OperationalError → fail-open 返回 []。
        修复后应按 timestamp 倒序返回（最近写入的在前）。
        """
        db = str(tmp_path / "f.db")
        # 写 3 条，每条间隔足够区分 timestamp 字符串顺序
        for i in range(3):
            record_failure(
                f"task {i}",
                "auto",
                cause="x",
                error_detail=f"e{i}",
                stop_reason="failed",
                iterations=1,
                resolved=False,
                db_path=db,
            )
        result = get_all_failures(db_path=db)
        assert len(result) == 3
        # timestamp 倒序：后写入的 timestamp 字符串更大，应排在前
        timestamps = [entry.timestamp for entry in result]
        assert timestamps == sorted(timestamps, reverse=True)

    def test_exception_returns_empty(self, monkeypatch, tmp_path):
        def _raise(_path, **_kw):
            raise sqlite3.OperationalError("connect boom")

        monkeypatch.setattr(fb_module, "connect", _raise)
        assert get_all_failures(db_path=str(tmp_path / "x.db")) == []

    def test_d0015_end_to_end_clustering_works(self, tmp_path):
        """D-0015 端到端验证：写入真实数据 → get_all_failures 返回非空
        → run_clustering_analysis 返回 has_data=True。

        旧 bug 下 get_all_failures 永远返回 []，导致 run_clustering_analysis
        永远 has_data=False，聚类分析功能实际不可用。
        """
        db = str(tmp_path / "f.db")
        # 写入 2 条同类失败（syntax_error），触发聚类
        for i in range(2):
            record_failure(
                f"task {i}",
                "auto",
                cause="syntax_error",
                error_detail=f"missing bracket line {i}",
                stop_reason="failed",
                iterations=2,
                resolved=False,
                db_path=db,
            )
        # 1 条不同类
        record_failure(
            "task timeout",
            "auto",
            cause="timeout",
            error_detail="request timed out",
            stop_reason="failed",
            iterations=1,
            resolved=False,
            db_path=db,
        )

        entries = get_all_failures(db_path=db)
        assert len(entries) == 3, f"D-0015 修复失效：get_all_failures 返回 {len(entries)} 条"

        report = run_clustering_analysis(db_path=db)
        assert report["has_data"] is True, "D-0015 修复失效：聚类分析仍报 has_data=False"
        assert report["total_failures"] == 3


class TestRunClusteringAnalysis:
    """run_clustering_analysis 三条路径：无数据 / 有数据 / 异常。"""

    def test_no_data_returns_empty_report(self, tmp_path):
        db = str(tmp_path / "f.db")
        report = run_clustering_analysis(db_path=db)
        assert report["has_data"] is False
        assert report["total_failures"] == 0
        assert report["stats"] == {}
        assert report["systemic_failures"] == []
        assert report["suggestions"] == []

    def test_has_data_when_real_failure_recorded(self, tmp_path):
        """D-0015 回归守卫：写入真实数据后，run_clustering_analysis 应 has_data=True。

        旧 bug：get_all_failures 的 SQL 列名错误（created_at vs timestamp）
        导致永远抛 OperationalError 被 fail-open 返回 []，进而
        run_clustering_analysis 永远 has_data=False，聚类分析功能实际不可用。
        修复后该链路应正常工作。
        """
        db = str(tmp_path / "f.db")
        record_failure(
            "task one",
            "auto",
            cause="syntax_error",
            error_detail="e",
            stop_reason="failed",
            iterations=1,
            resolved=False,
            db_path=db,
        )
        report = run_clustering_analysis(db_path=db)
        assert report["has_data"] is True
        assert report["total_failures"] == 1

    def test_with_data_returns_full_report(self, monkeypatch, tmp_path):
        # monkeypatch get_all_failures 返回非空，触发 has_data=True 分支
        fake_entries = [
            FailureEntry(
                failure_id="f1",
                task_description="task A",
                design_style="auto",
                cause="syntax_error",
                error_detail="missing bracket",
                stop_reason="failed",
                iterations=2,
                resolved=False,
                resolution="",
                timestamp="2024-01-01T00:00:00+00:00",
            ),
            FailureEntry(
                failure_id="f2",
                task_description="task B",
                design_style="auto",
                cause="syntax_error",
                error_detail="missing bracket line 5",
                stop_reason="failed",
                iterations=3,
                resolved=False,
                resolution="",
                timestamp="2024-01-02T00:00:00+00:00",
            ),
            FailureEntry(
                failure_id="f3",
                task_description="task C",
                design_style="auto",
                cause="timeout",
                error_detail="request timed out",
                stop_reason="failed",
                iterations=1,
                resolved=False,
                resolution="",
                timestamp="2024-01-03T00:00:00+00:00",
            ),
        ]
        monkeypatch.setattr(fb_module, "get_all_failures", lambda **_kw: fake_entries)
        report = run_clustering_analysis(db_path=str(tmp_path / "x.db"))
        assert report["has_data"] is True
        assert report["total_failures"] == 3
        assert "stats" in report
        assert isinstance(report["systemic_failures"], list)
        assert isinstance(report["suggestions"], list)

    def test_with_data_include_resolved(self, monkeypatch, tmp_path):
        fake_entries = [
            FailureEntry(
                failure_id="f1",
                task_description="task A",
                design_style="auto",
                cause="syntax_error",
                error_detail="missing bracket",
                stop_reason="failed",
                iterations=2,
                resolved=True,
                resolution="fixed",
                timestamp="2024-01-01T00:00:00+00:00",
            ),
        ]
        monkeypatch.setattr(fb_module, "get_all_failures", lambda **_kw: fake_entries)
        # include_resolved=True → 走 None 分支
        report = run_clustering_analysis(db_path=str(tmp_path / "x.db"), include_resolved=True)
        assert report["has_data"] is True

    def test_exception_returns_error_report(self, monkeypatch, tmp_path):
        def _raise(**_kw):
            raise RuntimeError("get_all_failures boom")

        monkeypatch.setattr(fb_module, "get_all_failures", _raise)
        report = run_clustering_analysis(db_path=str(tmp_path / "x.db"))
        assert report["has_data"] is False
        assert report["total_failures"] == 0
        assert report["error"] == "clustering analysis failed"

    def test_exception_on_import_returns_error_report(self, monkeypatch, tmp_path):
        # 让 from driving.failure_clustering import ... 抛 ImportError
        import builtins

        real_import = builtins.__import__

        def _fail_import(name, *args, **kwargs):
            if name == "driving.failure_clustering":
                raise ImportError("simulated missing module")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", _fail_import)
        report = run_clustering_analysis(db_path=str(tmp_path / "x.db"))
        assert report["has_data"] is False
        assert report["error"] == "clustering analysis failed"


class TestRowToEntry:
    """_row_to_entry 边界：空 vector / 有 vector。"""

    def test_row_with_empty_vector(self):
        row = {
            "failure_id": "f1",
            "task_description": "t",
            "design_style": "auto",
            "cause": "x",
            "error_detail": "e",
            "stop_reason": "failed",
            "iterations": 1,
            "resolved": 0,
            "resolution": "",
            "timestamp": "2024",
            "task_description_vector": "",
        }
        mock_row = MagicMock()
        mock_row.__getitem__ = MagicMock(side_effect=lambda key: row[key])
        entry = _row_to_entry(mock_row)
        assert entry.failure_id == "f1"
        assert entry.task_description_vector == []
        assert entry.resolved is False

    def test_row_with_vector(self):
        row = {
            "failure_id": "f2",
            "task_description": "t",
            "design_style": "auto",
            "cause": "x",
            "error_detail": "e",
            "stop_reason": "failed",
            "iterations": 2,
            "resolved": 1,
            "resolution": "fixed",
            "timestamp": "2024",
            "task_description_vector": "[0.1, 0.2, 0.3]",
        }
        mock_row = MagicMock()
        mock_row.__getitem__ = MagicMock(side_effect=lambda key: row[key])
        entry = _row_to_entry(mock_row)
        assert entry.failure_id == "f2"
        assert entry.task_description_vector == [0.1, 0.2, 0.3]
        assert entry.resolved is True
