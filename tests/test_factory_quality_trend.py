"""M135-B · 质量趋势打分与 API 的确定性单测。

验证：
1. task 完成时 quality_history 被追加(grade_quality 打分)
2. grade_quality 异常时 fail-open(不阻塞任务)
3. quality_history 持久化 roundtrip
4. API 返回正确结构(空数据/有数据两种情况)
"""
from __future__ import annotations

import os
import sys
import tempfile
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest  # noqa: E402

from driving.factory_loop import (  # noqa: E402
    FactoryState,
    FactoryStatus,
    FactoryTask,
    _record_quality_score,
    load_factory_state,
    save_factory_state,
)


@pytest.fixture
def tmp_cwd():
    with tempfile.TemporaryDirectory() as td:
        yield td


def _make_state(cwd: str) -> FactoryState:
    return FactoryState(
        factory_id="f-quality",
        product_goal="demo",
        cwd=cwd,
        status=FactoryStatus.running,
        roadmap=[],
        repo_map_cache="cached",  # 跳过 repo_map 扫描
    )


def _make_task() -> FactoryTask:
    return FactoryTask(description="写一个函数", verify_cmd=["true"], max_attempts=1)


def _stub_drive_result() -> dict:
    return {
        "verified": True,
        "stop_reason": "completed",
        "iteration": 1,
        "history": [],
        "last_obs": {},
    }


# ---------- 1. task 完成时打分 ----------


def test_quality_score_appended_on_task_done(tmp_cwd):
    """_record_quality_score 被调时,quality_history 追加一条含 grade/overall 的记录。"""
    state = _make_state(tmp_cwd)
    task = _make_task()

    _record_quality_score(task, state)

    assert len(state.quality_history) == 1, "应追加一条质量记录"
    entry = state.quality_history[0]
    assert entry["task_id"] == task.id
    assert "timestamp" in entry
    assert "score" in entry
    score = entry["score"]
    assert "overall" in score and "grade" in score
    assert score["functionality"] == 85.0, "verified=True 时 functionality=85"
    assert score["grade"] in ("S", "A", "B", "C")


# ---------- 2. fail-open ----------


def test_quality_score_failure_does_not_block_task(tmp_cwd):
    """grade_quality 异常时,fail-open 不追加记录也不抛异常。"""
    state = _make_state(tmp_cwd)
    task = _make_task()

    with patch("driving.quality_grading.grade_quality", side_effect=RuntimeError("boom")):
        _record_quality_score(task, state)  # 不应抛异常

    assert len(state.quality_history) == 0, "fail-open 不追加记录"


# ---------- 3. 持久化 roundtrip ----------


def test_quality_history_survives_save_load(tmp_cwd, tmp_path):
    """quality_history 字段随 FactoryState 持久化(save/load roundtrip)。"""
    db = tmp_path / "factory.db"
    state = _make_state(tmp_cwd)
    state.quality_history.append({
        "task_id": "t1",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "score": {
            "functionality": 85.0,
            "code_quality": 60.0,
            "design": 72.0,
            "maintainability": 60.0,
            "performance": 60.0,
            "grade": "B",
            "overall": 67.5,
            "details": {},
        },
    })
    save_factory_state(state, str(db))

    loaded = load_factory_state("f-quality", str(db))
    assert loaded is not None
    assert len(loaded.quality_history) == 1
    assert loaded.quality_history[0]["task_id"] == "t1"
    assert loaded.quality_history[0]["score"]["overall"] == 67.5


# ---------- 4. API 返回结构 ----------


def test_api_quality_trend_empty(tmp_cwd, tmp_path):
    """空 quality_history 时,API 返回 insufficient_data。"""
    from api.factory import get_factory_quality_trend
    import asyncio

    db = tmp_path / "factory.db"
    state = _make_state(tmp_cwd)
    save_factory_state(state, str(db))

    with patch("api.factory.FACTORY_DB", str(db)):
        result = asyncio.run(get_factory_quality_trend("f-quality"))

    assert result["factory_id"] == "f-quality"
    assert result["history"] == []
    assert result["trend"]["direction"] in ("insufficient_data", "unknown")


def test_api_quality_trend_with_data(tmp_cwd, tmp_path):
    """有多条 quality_history 时,API 返回趋势分析 + 完整历史。"""
    from api.factory import get_factory_quality_trend
    import asyncio

    db = tmp_path / "factory.db"
    state = _make_state(tmp_cwd)
    # 造 3 条递增分数,模拟 improving 趋势
    for i, overall in enumerate([60.0, 68.0, 76.0]):
        state.quality_history.append({
            "task_id": f"t{i+1}",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "score": {
                "functionality": 85.0,
                "code_quality": 60.0,
                "design": overall,
                "maintainability": 60.0,
                "performance": 60.0,
                "grade": "B" if overall < 75 else "A",
                "overall": overall,
                "details": {},
            },
        })
    save_factory_state(state, str(db))

    with patch("api.factory.FACTORY_DB", str(db)):
        result = asyncio.run(get_factory_quality_trend("f-quality"))

    assert result["factory_id"] == "f-quality"
    assert len(result["history"]) == 3
    trend = result["trend"]
    assert "direction" in trend
    assert trend["direction"] in ("improving", "stable", "degrading")
    assert "latest_grade" in trend
    assert trend["latest_overall"] == 76.0
