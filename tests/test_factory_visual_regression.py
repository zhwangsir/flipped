"""M134.2 · visual_regression 接入 factory_loop verifier 的确定性单测。

验证 default_orchestrator_fn 在 UI 任务 + FLIPPED_USE_VISUAL_REGRESSION=1 时：
1. verifier 被 visual_regression 包装(调用时触发 visual 校验)
2. 未设置环境变量时,verifier 不含 visual_regression
3. import 失败时 fail-open 退回原 verifier
4. 视觉回归是 warning 级:不阻断 verify,但结果追加到反馈
"""
from __future__ import annotations

import os
import sys
import tempfile
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest  # noqa: E402

from driving.factory_loop import (  # noqa: E402
    FactoryState,
    FactoryStatus,
    FactoryTask,
    default_orchestrator_fn,
)


@pytest.fixture
def tmp_cwd():
    with tempfile.TemporaryDirectory() as td:
        yield td


def _make_ui_state(cwd: str) -> FactoryState:
    """UI 任务需要 design_context 非空(_looks_like_ui_task 判定条件)。"""
    return FactoryState(
        factory_id="f-visual",
        product_goal="demo",
        cwd=cwd,
        status=FactoryStatus.running,
        roadmap=[],
        design_context="dark mode landing page",  # 触发 UI 判定
        repo_map_cache="cached",  # 跳过 repo_map 扫描
    )


def _make_ui_task() -> FactoryTask:
    return FactoryTask(
        description="创建 landing page hero 区域",
        verify_cmd=["true"],
        max_attempts=1,
    )


def _stub_drive_capture_verifier(captured: dict):
    """mock drive_orchestrated,捕获 verifier 并调用它验证行为。"""

    def fake_drive(**kwargs):
        captured.update(kwargs)
        # 调用 verifier 看它是否含 visual 校验；verifier 内部若抛异常(如 a11y 渲染服务
        # 不在线)也记录下来，避免异常导致 verifier_result 未赋值而误判为"未装配 verifier"。
        verifier = kwargs.get("verifier")
        if verifier:
            try:
                ok, msg = verifier(["true"], "/tmp")
                captured["verifier_result"] = (ok, msg)
            except Exception as exc:  # noqa: BLE001
                captured["verifier_result"] = (False, f"<verifier raised: {exc!r}>")
        return {
            "verified": True,
            "stop_reason": "completed",
            "iteration": 1,
            "history": [],
            "last_obs": {},
        }

    return fake_drive


# ---------- 1. opt-in 启用时注入 ----------


def test_visual_regression_injected_when_enabled(tmp_cwd, monkeypatch):
    """FLIPPED_USE_VISUAL_REGRESSION=1 + UI 任务时,verifier 被 visual 包装。"""
    monkeypatch.setenv("FLIPPED_USE_VISUAL_REGRESSION", "1")
    state = _make_ui_state(tmp_cwd)
    task = _make_ui_task()
    captured: dict = {}

    # mock visual_regression 避免依赖真 Playwright
    mock_visual_verify = MagicMock(return_value=(True, "视觉回归通过(diff=2.3%)"))
    mock_make_visual = MagicMock(return_value=mock_visual_verify)
    # mock a11y/design_lint 组合层,让 visual 包一个离线 True verifier(避免 a11y 真实启动 Chromium)
    mock_base_verify = MagicMock(return_value=(True, "design ok"))
    mock_combined = MagicMock(return_value=mock_base_verify)
    mock_combined_a11y = MagicMock(return_value=mock_base_verify)

    with patch("driving.factory_loop.drive_orchestrated", side_effect=_stub_drive_capture_verifier(captured)):
        with patch("driving.visual_regression.make_visual_verifier", mock_make_visual):
            with patch("driving.a11y_lint.combined_verifier_with_a11y", mock_combined_a11y):
                with patch("driving.design_lint.combined_verifier", mock_combined):
                    default_orchestrator_fn(task, state)

    assert "verifier" in captured, "应装配 verifier"
    assert "verifier_result" in captured, "verifier 应被调用"
    ok, msg = captured["verifier_result"]
    assert "[visual]" in msg, "verifier 输出应包含 [visual] 标记"
    mock_make_visual.assert_called_once(), "make_visual_verifier 应被调用"
    mock_visual_verify.assert_called_once(), "visual verifier 应被调用"


# ---------- 2. 默认关闭 ----------


def test_visual_regression_not_injected_by_default(tmp_cwd, monkeypatch):
    """未设置 FLIPPED_USE_VISUAL_REGRESSION 时,verifier 不含 visual 校验。"""
    monkeypatch.delenv("FLIPPED_USE_VISUAL_REGRESSION", raising=False)
    state = _make_ui_state(tmp_cwd)
    task = _make_ui_task()
    captured: dict = {}

    mock_make_visual = MagicMock()

    with patch("driving.factory_loop.drive_orchestrated", side_effect=_stub_drive_capture_verifier(captured)):
        with patch("driving.visual_regression.make_visual_verifier", mock_make_visual):
            default_orchestrator_fn(task, state)

    assert "verifier_result" in captured
    ok, msg = captured["verifier_result"]
    assert "[visual]" not in msg, "默认关闭时不应有 [visual] 标记"
    mock_make_visual.assert_not_called(), "默认关闭时不应调用 make_visual_verifier"


# ---------- 3. fail-open ----------


def test_visual_regression_import_failure_fails_open(tmp_cwd, monkeypatch):
    """visual_regression import 失败时,退回原 verifier,任务仍能跑。"""
    monkeypatch.setenv("FLIPPED_USE_VISUAL_REGRESSION", "1")
    state = _make_ui_state(tmp_cwd)
    task = _make_ui_task()
    captured: dict = {}

    with patch("driving.factory_loop.drive_orchestrated", side_effect=_stub_drive_capture_verifier(captured)):
        # 模拟 import 失败
        with patch.dict("sys.modules", {"driving.visual_regression": None}):
            result = default_orchestrator_fn(task, state)

    assert result.verified is True, "import 失败不应阻塞任务"


# ---------- 4. warning 级不阻断 ----------


def test_visual_regression_is_warning_level(tmp_cwd, monkeypatch):
    """视觉回归失败时 verify 仍通过(warning 级),但结果追加到反馈。"""
    monkeypatch.setenv("FLIPPED_USE_VISUAL_REGRESSION", "1")
    state = _make_ui_state(tmp_cwd)
    task = _make_ui_task()
    captured: dict = {}

    # mock visual 返回失败(差异过大)
    mock_visual_verify = MagicMock(return_value=(False, "视觉回归失败(diff=35.2% > 5%)"))
    mock_make_visual = MagicMock(return_value=mock_visual_verify)

    # mock design_lint/a11y/design_quality 组合,让 visual 的上一层 verifier 返回 True
    # (隔离 visual 层的影响,专注验证"visual 失败不改变整体 ok")
    mock_base_verify = MagicMock(return_value=(True, "design ok"))
    mock_combined = MagicMock(return_value=mock_base_verify)
    mock_combined_a11y = MagicMock(return_value=mock_base_verify)
    # _wrap_with_design_quality 是 factory_loop 内部函数,直接 patch 它让 visual 包一个 True verifier
    mock_wrap = MagicMock(side_effect=lambda v: v)

    with patch("driving.factory_loop.drive_orchestrated", side_effect=_stub_drive_capture_verifier(captured)):
        with patch("driving.visual_regression.make_visual_verifier", mock_make_visual):
            with patch("driving.a11y_lint.combined_verifier_with_a11y", mock_combined_a11y):
                with patch("driving.design_lint.combined_verifier", mock_combined):
                    with patch("driving.factory_loop._wrap_with_design_quality", mock_wrap):
                        default_orchestrator_fn(task, state)

    ok, msg = captured["verifier_result"]
    assert ok is True, "视觉回归失败不应阻断 verify(warning 级)"
    assert "[visual]" in msg and "视觉回归失败" in msg, "视觉结果应追加到反馈"


# ---------- 5. 非 UI 任务不注入 ----------


def test_visual_regression_skipped_for_non_ui_task(tmp_cwd, monkeypatch):
    """非 UI 任务(design_context 为空)即使开启开关也不注入 visual。"""
    monkeypatch.setenv("FLIPPED_USE_VISUAL_REGRESSION", "1")
    state = FactoryState(
        factory_id="f-visual-non-ui",
        product_goal="demo",
        cwd=tmp_cwd,
        status=FactoryStatus.running,
        roadmap=[],
        design_context="",  # 空 → 非 UI 任务
        repo_map_cache="cached",
    )
    task = FactoryTask(description="写一个 Python 函数", verify_cmd=["true"], max_attempts=1)
    captured: dict = {}

    mock_make_visual = MagicMock()

    with patch("driving.factory_loop.drive_orchestrated", side_effect=_stub_drive_capture_verifier(captured)):
        with patch("driving.visual_regression.make_visual_verifier", mock_make_visual):
            default_orchestrator_fn(task, state)

    mock_make_visual.assert_not_called(), "非 UI 任务不应触发 visual_regression"
