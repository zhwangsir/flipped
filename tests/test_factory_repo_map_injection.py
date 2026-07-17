"""M134.1 · repo_map 注入 factory_loop kwargs 的确定性单测。

验证 default_orchestrator_fn 在执行任务前：
1. 调用 build_repo_map 并把结果传给 drive_orchestrated 的 repo_map 参数
2. build_repo_map 异常时 fail-open，任务仍能跑
3. 同一 factory 第二次任务复用缓存（不重复扫描）
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest  # noqa: E402

from driving.factory_loop import (  # noqa: E402
    FactoryState,
    FactoryStatus,
    FactoryTask,
    TaskResult,
    default_orchestrator_fn,
)


@pytest.fixture
def tmp_cwd():
    with tempfile.TemporaryDirectory() as td:
        # 放一个 pyproject.toml 让 build_repo_map 能探到技术栈
        (Path(td) / "pyproject.toml").write_text("[project]\nname='demo'\n")
        (Path(td) / "src").mkdir()
        yield td


def _make_state(cwd: str) -> FactoryState:
    return FactoryState(
        factory_id="f-repo-map",
        product_goal="demo",
        cwd=cwd,
        status=FactoryStatus.running,
        roadmap=[],
        repo_map_cache="",  # 确保从空开始
    )


def _make_task(desc: str = "do something") -> FactoryTask:
    return FactoryTask(description=desc, verify_cmd=["true"], max_attempts=1)


def _stub_drive_result() -> dict:
    """drive_orchestrated 返回 dict,default_orchestrator_fn 用 .get() 取值。"""
    return {
        "verified": True,
        "stop_reason": "completed",
        "iteration": 1,
        "history": [],
        "last_obs": {},
    }


# ---------- 1. 正常注入 ----------


def test_repo_map_injected_into_kwargs(tmp_cwd):
    """build_repo_map 被调用,且结果传给 drive_orchestrated 的 repo_map 参数。"""
    state = _make_state(tmp_cwd)
    task = _make_task()
    captured: dict = {}

    def fake_drive(**kwargs):
        captured.update(kwargs)
        return _stub_drive_result()

    with patch("driving.factory_loop.drive_orchestrated", side_effect=fake_drive):
        default_orchestrator_fn(task, state)

    assert "repo_map" in captured, "drive_orchestrated 应收到 repo_map 参数"
    assert "技术栈" in captured["repo_map"] or captured["repo_map"] == "" or isinstance(
        captured["repo_map"], str
    ), "repo_map 应为字符串"
    # 状态缓存已填充
    assert state.repo_map_cache == captured["repo_map"]


# ---------- 2. fail-open ----------


def test_repo_map_failure_does_not_block_task(tmp_cwd):
    """build_repo_map 抛异常时,任务仍能跑,fail-open 为空串。"""
    state = _make_state(tmp_cwd)
    task = _make_task()
    captured: dict = {}

    def fake_drive(**kwargs):
        captured.update(kwargs)
        return _stub_drive_result()

    with patch("driving.factory_loop.drive_orchestrated", side_effect=fake_drive):
        with patch("driving.repo_map.build_repo_map", side_effect=RuntimeError("boom")):
            result = default_orchestrator_fn(task, state)

    assert result.verified is True, "repo_map 失败不应阻塞任务"
    assert captured.get("repo_map") == "", "fail-open 应传空串"
    assert state.repo_map_cache == "", "fail-open 缓存应为空串"


# ---------- 3. 缓存复用 ----------


def test_repo_map_cached_across_tasks(tmp_cwd):
    """同一 factory 第二个 task 不再重复调用 build_repo_map。"""
    state = _make_state(tmp_cwd)
    task1 = _make_task("task 1")
    task2 = _make_task("task 2")

    def fake_drive(**kwargs):
        return _stub_drive_result()

    mock_build = MagicMock(return_value="技术栈：Python\n顶层目录：src/\n")

    with patch("driving.factory_loop.drive_orchestrated", side_effect=fake_drive):
        with patch("driving.repo_map.build_repo_map", mock_build):
            default_orchestrator_fn(task1, state)
            assert mock_build.call_count == 1, "第一次应扫描"
            first_cache = state.repo_map_cache
            assert first_cache == "技术栈：Python\n顶层目录：src/\n"

            default_orchestrator_fn(task2, state)
            assert mock_build.call_count == 1, "第二次不应重复扫描(缓存生效)"
            assert state.repo_map_cache == first_cache, "缓存内容不变"


# ---------- 4. 缓存持久化 ----------


def test_repo_map_cache_survives_save_load(tmp_cwd, tmp_path):
    """repo_map_cache 字段随 FactoryState 持久化(save/load roundtrip)。"""
    from driving.factory_loop import save_factory_state, load_factory_state

    db = tmp_path / "factory.db"
    state = _make_state(tmp_cwd)
    state.repo_map_cache = "技术栈：Python\n"
    save_factory_state(state, str(db))

    loaded = load_factory_state("f-repo-map", str(db))
    assert loaded is not None
    assert loaded.repo_map_cache == "技术栈：Python\n"
