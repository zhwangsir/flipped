"""M109 · 失败模式自动聚类测试。

定期自动聚类相似的失败，识别系统性失败，自动生成改进建议。
"""
from __future__ import annotations

import tempfile
import os
from datetime import datetime, timezone

import pytest

from driving.failure_clustering import (
    FailureCluster,
    cluster_failures,
    identify_systemic_failures,
    generate_improvement_suggestions,
    get_cluster_stats,
)
from driving.failure_kb import record_failure


class TestClusterFailures:
    def test_empty_failures_returns_empty(self):
        clusters = cluster_failures([])
        assert clusters == []

    def test_similar_failures_in_same_cluster(self):
        failures = [
            {"id": "1", "task_description": "build landing page", "cause": "syntax_error",
             "error_detail": "SyntaxError: invalid syntax on line 42"},
            {"id": "2", "task_description": "build dashboard", "cause": "syntax_error",
             "error_detail": "SyntaxError: expected ':' on line 15"},
            {"id": "3", "task_description": "build blog", "cause": "syntax_error",
             "error_detail": "SyntaxError: invalid syntax on line 8"},
        ]
        clusters = cluster_failures(failures)
        assert len(clusters) >= 1
        all_ids = {fid for c in clusters for fid in c.failure_ids}
        assert all_ids >= {"1", "2", "3"}

    def test_different_causes_in_different_clusters(self):
        failures = [
            {"id": "1", "task_description": "task 1", "cause": "syntax_error",
             "error_detail": "SyntaxError on line 1"},
            {"id": "2", "task_description": "task 2", "cause": "verification_failed",
             "error_detail": "verify command returned non-zero"},
            {"id": "3", "task_description": "task 3", "cause": "context_overflow",
             "error_detail": "too many tokens"},
        ]
        clusters = cluster_failures(failures)
        assert len(clusters) >= 2

    def test_cluster_has_summary(self):
        failures = [
            {"id": "1", "task_description": "build landing page", "cause": "syntax_error",
             "error_detail": "SyntaxError: missing colon on line 5"},
            {"id": "2", "task_description": "build dashboard", "cause": "syntax_error",
             "error_detail": "SyntaxError: invalid syntax on line 10"},
        ]
        clusters = cluster_failures(failures)
        assert len(clusters) > 0
        assert clusters[0].summary
        assert len(clusters[0].summary) > 0


class TestIdentifySystemicFailures:
    def test_high_frequency_cluster_is_systemic(self):
        clusters = [
            FailureCluster(
                cluster_id="c1",
                failure_ids=[f"f{i}" for i in range(20)],
                cause_category="syntax_error",
                summary="20 syntax errors",
                frequency=20,
                percentage=80.0,
            ),
        ]
        systemic = identify_systemic_failures(clusters, total_failures=25)
        assert len(systemic) >= 1
        assert systemic[0].cluster_id == "c1"

    def test_low_frequency_not_systemic(self):
        clusters = [
            FailureCluster(
                cluster_id="c1",
                failure_ids=["f1"],
                cause_category="syntax_error",
                summary="1 syntax error",
                frequency=1,
                percentage=4.0,
            ),
        ]
        systemic = identify_systemic_failures(clusters, total_failures=25)
        assert len(systemic) == 0


class TestGenerateImprovementSuggestions:
    def test_syntax_error_suggestion(self):
        clusters = [
            FailureCluster(
                cluster_id="c1",
                failure_ids=["f1", "f2", "f3"],
                cause_category="syntax_error",
                summary="multiple syntax errors",
                frequency=3,
                percentage=30.0,
            ),
        ]
        suggestions = generate_improvement_suggestions(clusters, total_failures=10)
        assert len(suggestions) > 0
        text = " ".join(suggestions)
        assert len(text) > 0

    def test_empty_clusters_no_suggestions(self):
        suggestions = generate_improvement_suggestions([], total_failures=0)
        assert suggestions == []


class TestGetClusterStats:
    def test_stats_returns_expected_fields(self):
        clusters = [
            FailureCluster(
                cluster_id="c1",
                failure_ids=["f1", "f2"],
                cause_category="syntax_error",
                summary="syntax errors",
                frequency=2,
                percentage=40.0,
            ),
            FailureCluster(
                cluster_id="c2",
                failure_ids=["f3"],
                cause_category="verification_failed",
                summary="verify failures",
                frequency=1,
                percentage=20.0,
            ),
        ]
        stats = get_cluster_stats(clusters, total_failures=5)
        assert stats["total_clusters"] == 2
        assert stats["total_failures"] == 5
        assert stats["clustered_failures"] == 3
        assert "top_clusters" in stats
        assert len(stats["top_clusters"]) == 2

    def test_empty_stats(self):
        stats = get_cluster_stats([], total_failures=0)
        assert stats["total_clusters"] == 0
        assert stats["total_failures"] == 0
