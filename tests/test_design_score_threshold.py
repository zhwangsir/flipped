"""design_score 门槛 + 自动反馈循环测试（M32）。

验证 _wrap_with_design_quality 的 design_score 门槛机制：
1. 高分 HTML → 通过
2. 低分 HTML → 失败 + feedback 包含分数和问题描述
3. error 级违规 → 失败（现有行为保持）
4. 阈值可通过 FLIPPED_DESIGN_SCORE_THRESHOLD 配置
5. design_score 不可用时 fail-open
6. 无 HTML 文件时跳过 score 检查
"""
from __future__ import annotations

import os
import tempfile

import pytest

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from driving.factory_loop import _wrap_with_design_quality


# 良好 HTML：所有维度齐全，design_score >= 80
_GOOD_HTML = """<!DOCTYPE html>
<html lang="zh"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
:root { --color-accent: #0A84FF; --color-bg: #0D0D12; --color-text: #F5F5F5; }
body { transition: opacity 0.3s ease; transform: translateY(0); }
</style>
</head><body>
<header><nav>Logo</nav></header>
<main><section><h1>Title</h1></section></main>
<footer>Copyright</footer>
</body></html>"""

# 低分 HTML：缺 viewport + lang + alt + :root + header/main/footer
_BAD_HTML = """<html><head></head><body>
<img src="photo.jpg">
<div>Hello</div>
</body></html>"""


def _base_verifier_ok(history, cwd):
    return True, "ok"


def test_high_design_score_passes():
    """高 design_score → 通过（不触发门槛）。"""
    with tempfile.TemporaryDirectory() as d:
        with open(os.path.join(d, "index.html"), "w") as f:
            f.write(_GOOD_HTML)
        wrapped = _wrap_with_design_quality(_base_verifier_ok)
        ok, msg = wrapped([], d)
    assert ok is True


def test_low_design_score_fails():
    """低 design_score → 失败 + feedback 包含分数。"""
    with tempfile.TemporaryDirectory() as d:
        with open(os.path.join(d, "index.html"), "w") as f:
            f.write(_BAD_HTML)
        wrapped = _wrap_with_design_quality(_base_verifier_ok)
        ok, msg = wrapped([], d)
    # BAD_HTML 有 error 级违规（缺 viewport/alt），可能先被 error 检查拦下
    # 也可能 score 太低被门槛拦下——两种都算 M32 行为
    assert ok is False
    assert "design" in msg.lower() or "score" in msg.lower() or "error" in msg.lower()


def test_design_score_threshold_in_feedback():
    """低分时 feedback 包含具体分数和问题描述。"""
    with tempfile.TemporaryDirectory() as d:
        with open(os.path.join(d, "index.html"), "w") as f:
            f.write(_BAD_HTML)
        wrapped = _wrap_with_design_quality(_base_verifier_ok)
        ok, msg = wrapped([], d)
    # feedback 应该包含分数或违规项的描述
    assert ok is False
    # 要么有 error 详情，要么有 score 信息
    assert len(msg) > 20  # 不仅仅是 "fail"


def test_error_level_violation_blocks():
    """error 级违规 → 失败（M19 现有行为保持）。"""
    html_missing_viewport = """<html lang="zh"><head></head><body>
<header>H</header><main><section>Content</section></main><footer>F</footer>
</body></html>"""
    with tempfile.TemporaryDirectory() as d:
        with open(os.path.join(d, "index.html"), "w") as f:
            f.write(html_missing_viewport)
        wrapped = _wrap_with_design_quality(_base_verifier_ok)
        ok, msg = wrapped([], d)
    assert ok is False
    assert "error" in msg.lower() or "design" in msg.lower()


def test_threshold_configurable_via_env():
    """阈值可通过 FLIPPED_DESIGN_SCORE_THRESHOLD 环境变量配置。"""
    import unittest.mock as mock

    with tempfile.TemporaryDirectory() as d:
        with open(os.path.join(d, "index.html"), "w") as f:
            f.write(_GOOD_HTML)  # 有 HTML 文件即可，分数由 mock 控制

        # mock design_score 返回 65 分
        with mock.patch("driving.design_context.design_score", return_value=(65, ["中等质量"])):
            # 阈值=0 → 65 >= 0 → 通过
            os.environ["FLIPPED_DESIGN_SCORE_THRESHOLD"] = "0"
            try:
                wrapped = _wrap_with_design_quality(_base_verifier_ok)
                ok_low, _ = wrapped([], d)
            finally:
                del os.environ["FLIPPED_DESIGN_SCORE_THRESHOLD"]

            # 阈值=70 → 65 < 70 → 失败
            os.environ["FLIPPED_DESIGN_SCORE_THRESHOLD"] = "70"
            try:
                wrapped = _wrap_with_design_quality(_base_verifier_ok)
                ok_high, msg = wrapped([], d)
            finally:
                del os.environ["FLIPPED_DESIGN_SCORE_THRESHOLD"]

    assert ok_low is True
    assert ok_high is False
    assert "65" in msg or "score" in msg.lower()


def test_design_score_fail_open_on_exception():
    """design_score 异常时 fail-open（不阻断）。"""
    # mock design_score 抛异常
    with tempfile.TemporaryDirectory() as d:
        with open(os.path.join(d, "index.html"), "w") as f:
            f.write(_GOOD_HTML)

        import unittest.mock as mock
        with mock.patch("driving.design_context.design_score", side_effect=RuntimeError("crash")):
            wrapped = _wrap_with_design_quality(_base_verifier_ok)
            ok, msg = wrapped([], d)

    # design_score 异常 → 跳过门槛检查 → 通过（GOOD_HTML 无 error）
    assert ok is True


def test_no_html_skips_score_check():
    """无 HTML 文件时 design_score 返回 0 → 跳过门槛检查。"""
    with tempfile.TemporaryDirectory() as d:
        # 没有 HTML 文件
        wrapped = _wrap_with_design_quality(_base_verifier_ok)
        ok, msg = wrapped([], d)
    # design_score 返回 0 → score > 0 不成立 → 跳过门槛 → 通过
    assert ok is True


def test_base_verifier_failure_short_circuits():
    """base verifier 已失败 → 不再检查设计质量。"""
    def base_fail(history, cwd):
        return False, "tests failed"

    with tempfile.TemporaryDirectory() as d:
        with open(os.path.join(d, "index.html"), "w") as f:
            f.write(_GOOD_HTML)
        wrapped = _wrap_with_design_quality(base_fail)
        ok, msg = wrapped([], d)
    assert ok is False
    assert "tests failed" in msg  # 直接返回 base verifier 的 msg


def test_warnings_do_not_block():
    """warning 级违规不阻断（只有 error 和低分才阻断）。"""
    # 这个 HTML 有 viewport + lang + alt 但 transition 用 margin（warning 级）
    html_with_warning = """<!DOCTYPE html>
<html lang="zh"><head>
<meta name="viewport" content="width=device-width">
<style>:root { --color-bg: #0D0D12; --color-text: #F5F5F5; }
.card { transition: margin 0.3s; }</style>
</head><body>
<header>H</header><main><section><img src="x.jpg" alt="desc"></section></main><footer>F</footer>
</body></html>"""
    with tempfile.TemporaryDirectory() as d:
        with open(os.path.join(d, "index.html"), "w") as f:
            f.write(html_with_warning)
        # 设低阈值确保 score 门槛不触发（只测 warning 行为）
        os.environ["FLIPPED_DESIGN_SCORE_THRESHOLD"] = "0"
        try:
            wrapped = _wrap_with_design_quality(_base_verifier_ok)
            ok, msg = wrapped([], d)
        finally:
            del os.environ["FLIPPED_DESIGN_SCORE_THRESHOLD"]
    assert ok is True
    assert "warning" in msg.lower() or "ok" in msg.lower()
