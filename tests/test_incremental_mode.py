"""M103 · 增量改进模式测试。

verify 失败后，基于现有产物做精准修复，而非从头重写。
核心：失败 → RCA 分析 → 增量修复 prompt → 写回原文件 → 再验证
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from driving.incremental_mode import (
    IncrementalContext,
    detect_existing_artifacts,
    build_incremental_prompt,
    apply_patch_to_file,
    should_use_incremental,
    MAX_INCREMENTAL_ROUNDS,
)


class TestDetectExistingArtifacts:
    def test_empty_dir_returns_empty(self, tmp_path):
        artifacts = detect_existing_artifacts(str(tmp_path))
        assert artifacts == {}

    def test_detects_html_file(self, tmp_path):
        (tmp_path / "index.html").write_text("<html></html>")
        artifacts = detect_existing_artifacts(str(tmp_path))
        assert "index.html" in artifacts
        assert artifacts["index.html"] == "<html></html>"

    def test_skips_large_files(self, tmp_path):
        large = "x" * 50000
        (tmp_path / "big.html").write_text(large)
        artifacts = detect_existing_artifacts(str(tmp_path), max_size_kb=10)
        assert "big.html" not in artifacts

    def test_skips_non_source_files(self, tmp_path):
        (tmp_path / "test.db").write_text("data")
        (tmp_path / "image.png").write_text("binary")
        artifacts = detect_existing_artifacts(str(tmp_path))
        assert "test.db" not in artifacts
        assert "image.png" not in artifacts

    def test_nested_files_relative_path(self, tmp_path):
        sub = tmp_path / "css"
        sub.mkdir()
        (sub / "style.css").write_text("body {}")
        artifacts = detect_existing_artifacts(str(tmp_path))
        assert "css/style.css" in artifacts


class TestBuildIncrementalPrompt:
    def test_includes_file_content(self, tmp_path):
        (tmp_path / "index.html").write_text("<html><body></body></html>")
        ctx = IncrementalContext(
            cwd=str(tmp_path),
            failure_output="ReferenceError: foo is not defined",
            rca_cause="missing_import",
            rca_suggestion="添加 foo 函数定义",
            round_num=1,
        )
        prompt = build_incremental_prompt(ctx, "修复 localStorage 功能")
        assert "index.html" in prompt
        assert "ReferenceError" in prompt
        assert "missing_import" in prompt
        assert "添加 foo 函数定义" in prompt

    def test_round_num_appears_in_prompt(self, tmp_path):
        ctx = IncrementalContext(
            cwd=str(tmp_path),
            failure_output="error",
            rca_cause="syntax_error",
            rca_suggestion="修复语法",
            round_num=2,
        )
        prompt = build_incremental_prompt(ctx, "任务")
        assert "第 2 轮" in prompt

    def test_no_rca_still_works(self, tmp_path):
        ctx = IncrementalContext(
            cwd=str(tmp_path),
            failure_output="test failed",
            round_num=1,
        )
        prompt = build_incremental_prompt(ctx, "修复 bug")
        assert "test failed" in prompt
        assert "修复" in prompt


class TestApplyPatchToFile:
    def test_full_replacement(self, tmp_path):
        f = tmp_path / "app.js"
        f.write_text("old content")
        ok = apply_patch_to_file(str(tmp_path), "app.js", "new content")
        assert ok is True
        assert f.read_text() == "new content"

    def test_creates_new_file(self, tmp_path):
        ok = apply_patch_to_file(str(tmp_path), "new.js", "console.log('hi')")
        assert ok is True
        assert (tmp_path / "new.js").read_text() == "console.log('hi')"

    def test_nested_path_creates_dirs(self, tmp_path):
        ok = apply_patch_to_file(str(tmp_path), "a/b/c.js", "x")
        assert ok is True
        assert (tmp_path / "a" / "b" / "c.js").exists()

    def test_empty_content_returns_false(self, tmp_path):
        ok = apply_patch_to_file(str(tmp_path), "x.js", "")
        assert ok is False


class TestShouldUseIncremental:
    def test_first_round_no_incremental(self):
        assert should_use_incremental(iteration=0, has_artifacts=True) is False

    def test_with_artifacts_and_failure_uses_incremental(self):
        assert should_use_incremental(iteration=1, has_artifacts=True) is True

    def test_no_artifacts_no_incremental(self):
        assert should_use_incremental(iteration=1, has_artifacts=False) is False

    def test_under_max_rounds(self):
        assert should_use_incremental(
            iteration=MAX_INCREMENTAL_ROUNDS - 1, has_artifacts=True
        ) is True

    def test_over_max_rounds_falls_back(self):
        assert should_use_incremental(
            iteration=MAX_INCREMENTAL_ROUNDS + 1, has_artifacts=True
        ) is False


class TestIncrementalContext:
    def test_defaults(self):
        ctx = IncrementalContext(cwd="/tmp", failure_output="err", round_num=1)
        assert ctx.rca_cause == ""
        assert ctx.rca_suggestion == ""
        assert ctx.max_rounds == MAX_INCREMENTAL_ROUNDS

    def test_is_final_round(self):
        ctx = IncrementalContext(
            cwd="/tmp",
            failure_output="err",
            round_num=MAX_INCREMENTAL_ROUNDS,
            max_rounds=MAX_INCREMENTAL_ROUNDS,
        )
        assert ctx.is_final_round() is True

    def test_not_final_round(self):
        ctx = IncrementalContext(cwd="/tmp", failure_output="err", round_num=1)
        assert ctx.is_final_round() is False
