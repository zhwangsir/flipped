"""progress_notes 单元测试（M10.4-B）。"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from driving.progress_notes import (
    init_progress,
    load_checklist,
    load_progress_text,
    record_task_done,
    record_task_failed,
    record_round,
    summarize_for_evolution,
    design_brief_from_progress,
    CHECKLIST_FILE,
    PROGRESS_FILE,
)


def test_init_progress_creates_files():
    with tempfile.TemporaryDirectory() as d:
        init_progress(d, "构建暗黑模式 Landing Page", design_style="dark")
        assert (Path(d) / CHECKLIST_FILE).exists()
        assert (Path(d) / PROGRESS_FILE).exists()
        c = load_checklist(d)
        assert c["direction"] == "构建暗黑模式 Landing Page"
        assert c["design_style"] == "dark"
        assert c["features"] == []
        assert c["rounds_completed"] == 0


def test_init_progress_is_idempotent():
    """重复 init 不应覆盖已有数据。"""
    with tempfile.TemporaryDirectory() as d:
        init_progress(d, "方向 A", "dark")
        record_task_done(d, "task-1", "实现 Hero", "ok")
        # 再次 init
        init_progress(d, "方向 B", "minimalism")
        c = load_checklist(d)
        # 数据保留
        assert c["direction"] == "方向 A"
        assert len(c["features"]) == 1


def test_record_task_done_updates_both_files():
    with tempfile.TemporaryDirectory() as d:
        init_progress(d, "方向", "dark")
        record_task_done(d, "task-1", "实现 Hero section", "verified ok", round_num=1)
        c = load_checklist(d)
        assert len(c["features"]) == 1
        feat = c["features"][0]
        assert feat["task_id"] == "task-1"
        assert feat["status"] == "done"
        assert feat["round"] == 1
        # PROGRESS.md 里有这个任务
        text = load_progress_text(d)
        assert "task-1" in text
        assert "Hero section" in text
        assert "✅" in text


def test_record_task_failed():
    with tempfile.TemporaryDirectory() as d:
        init_progress(d, "方向", "dark")
        record_task_failed(d, "task-x", "Pricing 模块", "design-lint 缺响应式", round_num=2)
        c = load_checklist(d)
        assert c["features"][0]["status"] == "failed"
        assert c["features"][0]["round"] == 2
        text = load_progress_text(d)
        assert "❌" in text
        assert "design-lint" in text


def test_record_round_increments():
    with tempfile.TemporaryDirectory() as d:
        init_progress(d, "方向", "dark")
        record_round(d, 1, "第一轮目标", 3, 0, "完成 3 个任务")
        record_round(d, 2, "第二轮目标", 2, 1, "完成 2 个失败 1 个")
        c = load_checklist(d)
        assert c["rounds_completed"] == 2
        text = load_progress_text(d)
        assert "第 1 轮" in text
        assert "第 2 轮" in text
        assert "完成 3 个任务" in text


def test_summarize_for_evolution():
    with tempfile.TemporaryDirectory() as d:
        init_progress(d, "方向", "dark")
        record_task_done(d, "t1", "Hero", round_num=1)
        record_task_done(d, "t2", "Features", round_num=1)
        record_task_failed(d, "t3", "Pricing", "design-lint", round_num=1)
        record_round(d, 1, "目标", 2, 1)
        s = summarize_for_evolution(d)
        assert "已完成轮次: 1" in s
        assert "Hero" in s and "Features" in s
        assert "Pricing" in s  # 失败的也列出来


def test_design_brief_from_progress_extracts_hexes():
    with tempfile.TemporaryDirectory() as d:
        init_progress(d, "方向", "dark")
        # 在 PROGRESS.md 里追加含 hex 的摘要
        record_task_done(d, "t1", "Hero section", "用 #0A84FF 做强调，#0D0D12 做背景")
        brief = design_brief_from_progress(d)
        assert brief is not None
        assert "#0A84FF" in brief
        assert "#0D0D12" in brief


def test_design_brief_from_progress_returns_none_when_no_hexes():
    with tempfile.TemporaryDirectory() as d:
        init_progress(d, "方向", "dark")
        record_task_done(d, "t1", "数据层", "无 UI 代码")
        brief = design_brief_from_progress(d)
        assert brief is None


def test_extract_feature_name_strips_prefix():
    """任务描述的前缀（实现/创建等）被剥掉。"""
    from driving.progress_notes import _extract_feature_name
    assert _extract_feature_name("实现 Hero section 布局") == "Hero section 布局"
    assert _extract_feature_name("创建 Pricing 表格") == "Pricing 表格"
    assert _extract_feature_name("feat: add login page") == "add login page"
    # 无前缀的不动
    assert _extract_feature_name("写一个测试") == "写一个测试"


def test_checklist_is_valid_json():
    """FEATURE_CHECKLIST.json 必须始终是合法 JSON。"""
    with tempfile.TemporaryDirectory() as d:
        init_progress(d, "方向", "dark")
        record_task_done(d, "t1", "Hero", round_num=1)
        record_task_failed(d, "t2", "Pricing", "err", round_num=1)
        record_round(d, 1, "目标", 1, 1)
        # 反复读取都应成功
        for _ in range(3):
            c = load_checklist(d)
            assert isinstance(c, dict)
            assert "features" in c
