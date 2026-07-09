"""视觉回归快照对比单元测试（M13）。"""
from __future__ import annotations

import io
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from driving.visual_regression import (
    VisualDiffResult,
    capture_screenshot,
    compare_images,
    visual_regression_check,
    make_visual_verifier,
    _baseline_path,
    _viewport_hash,
)


def _write(cwd: Path, name: str, content: str) -> Path:
    p = cwd / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return p


def _make_png(color=(255, 0, 0), size=(100, 100)) -> bytes:
    """生成纯色 PNG。"""
    from PIL import Image
    img = Image.new("RGB", size, color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# ---------- compare_images 单测 ----------

def test_compare_identical_images():
    """完全相同的图 → diff=0%。"""
    png = _make_png((255, 0, 0))
    r = compare_images(png, png)
    assert r.checked
    assert r.diff_pct == 0.0
    assert r.passed


def test_compare_different_images():
    """完全不同的颜色 → diff 接近 100%。"""
    a = _make_png((255, 0, 0))
    b = _make_png((0, 255, 0))
    r = compare_images(a, b)
    assert r.checked
    assert r.diff_pct > 0.9
    assert not r.passed  # 100% 差异 > 5% 阈值


def test_compare_similar_images():
    """微小差异 → diff 低，通过。"""
    from PIL import Image, ImageDraw
    a = Image.new("RGB", (100, 100), (255, 0, 0))
    b = Image.new("RGB", (100, 100), (255, 0, 0))
    # 在 b 上画一个小点（1% 面积）
    draw = ImageDraw.Draw(b)
    draw.rectangle([0, 0, 10, 10], fill=(0, 0, 255))  # 1% 面积
    buf_a, buf_b = io.BytesIO(), io.BytesIO()
    a.save(buf_a, format="PNG")
    b.save(buf_b, format="PNG")
    r = compare_images(buf_a.getvalue(), buf_b.getvalue())
    assert r.checked
    assert r.diff_pct < 0.05  # ~1% 差异
    assert r.passed


def test_compare_different_sizes():
    """尺寸不同 → 裁剪到较小尺寸对比。"""
    a = _make_png((255, 0, 0), size=(100, 100))
    b = _make_png((0, 255, 0), size=(50, 50))
    r = compare_images(a, b)
    assert r.checked
    assert not r.passed  # 颜色完全不同


def test_compare_invalid_png():
    """无效 PNG → 跳过。"""
    r = compare_images(b"not a png", b"also not")
    assert not r.checked
    assert "解析" in r.skip_reason or "Pillow" in r.skip_reason


# ---------- capture_screenshot 单测 ----------

@pytest.fixture
def playwright_available():
    try:
        from playwright.sync_api import sync_playwright
        p = sync_playwright().start()
        b = p.chromium.launch(headless=True)
        b.close()
        p.stop()
    except Exception as e:
        pytest.skip(f"Playwright 不可用: {type(e).__name__}")


def test_capture_screenshot_no_html():
    """无 HTML → 返回 None。"""
    with tempfile.TemporaryDirectory() as d:
        png = capture_screenshot(d)
        assert png is None


def test_capture_screenshot_returns_png(playwright_available):
    """有 HTML → 返回 PNG bytes。"""
    with tempfile.TemporaryDirectory() as d:
        _write(Path(d), "index.html", """
            <!DOCTYPE html><html><body><h1>Hello</h1></body></html>
        """)
        png = capture_screenshot(d)
        assert png is not None
        assert len(png) > 100
        assert png[:4] == b'\x89PNG'  # PNG magic bytes


# ---------- visual_regression_check 单测 ----------

def test_visual_regression_first_run_saves_baseline(playwright_available, tmp_path):
    """首次运行 → 保存基线，passed=True。"""
    _write(tmp_path, "index.html", "<!DOCTYPE html><html><body><h1>Test</h1></body></html>")
    with patch("driving.visual_regression._BASELINE_DIR", tmp_path / "baselines"):
        r = visual_regression_check(tmp_path)
    assert r.checked
    assert r.screenshot_saved
    assert r.passed
    assert "基线已保存" in r.message or "基线" in r.summary()


def test_visual_regression_same_html_passes(playwright_available, tmp_path):
    """相同 HTML 二次运行 → diff=0，通过。"""
    _write(tmp_path, "index.html", "<!DOCTYPE html><html><body><h1>Test</h1></body></html>")
    with patch("driving.visual_regression._BASELINE_DIR", tmp_path / "baselines"):
        # 首次：保存基线
        visual_regression_check(tmp_path)
        # 二次：对比
        r = visual_regression_check(tmp_path)
    assert r.checked
    assert r.baseline_exists
    assert r.passed
    assert r.diff_pct == 0.0


def test_visual_regression_different_html_fails(playwright_available, tmp_path):
    """不同 HTML → 差异大，不通过。"""
    _write(tmp_path, "index.html", """
        <!DOCTYPE html><html><body style="background:#FF0000"><h1>Red</h1></body></html>
    """)
    with patch("driving.visual_regression._BASELINE_DIR", tmp_path / "baselines"):
        # 首次：保存基线
        visual_regression_check(tmp_path)
        # 改 HTML
        _write(tmp_path, "index.html", """
            <!DOCTYPE html><html><body style="background:#00FF00"><h1>Green</h1></body></html>
        """)
        r = visual_regression_check(tmp_path)
    assert r.checked
    assert not r.passed  # 完全不同颜色
    assert r.diff_pct > 0.5


def test_visual_regression_no_html_skips():
    """无 HTML → 跳过。"""
    with tempfile.TemporaryDirectory() as d:
        r = visual_regression_check(d)
        assert not r.checked
        assert "截图" in r.skip_reason or "HTML" in r.skip_reason
        assert r.passed


def test_visual_regression_update_baseline(playwright_available, tmp_path):
    """update_baseline=True → 强制更新基线。"""
    _write(tmp_path, "index.html", "<!DOCTYPE html><html><body><h1>Test</h1></body></html>")
    with patch("driving.visual_regression._BASELINE_DIR", tmp_path / "baselines"):
        r = visual_regression_check(tmp_path, update_baseline=True)
        assert r.screenshot_saved


# ---------- verifier 接口 ----------

def test_make_visual_verifier_no_html():
    """无 HTML → verifier 返回 passed=True。"""
    with tempfile.TemporaryDirectory() as d:
        v = make_visual_verifier()
        ok, msg = v(["true"], d)
        assert ok
        assert "跳过" in msg or "visual" in msg.lower()


def test_make_visual_verifier_with_html(playwright_available, tmp_path):
    """有 HTML → verifier 执行截图+对比。"""
    _write(tmp_path, "index.html", "<!DOCTYPE html><html><body><h1>Test</h1></body></html>")
    with patch("driving.visual_regression._BASELINE_DIR", tmp_path / "baselines"):
        v = make_visual_verifier()
        ok, msg = v(["true"], tmp_path)
        assert ok
        assert "visual" in msg.lower() or "基线" in msg


# ---------- 辅助函数 ----------

def test_viewport_hash_deterministic():
    """相同 cwd+viewport → 相同 hash。"""
    h1 = _viewport_hash("/tmp/test", (1280, 720))
    h2 = _viewport_hash("/tmp/test", (1280, 720))
    assert h1 == h2


def test_viewport_hash_different():
    """不同 cwd → 不同 hash。"""
    h1 = _viewport_hash("/tmp/a", (1280, 720))
    h2 = _viewport_hash("/tmp/b", (1280, 720))
    assert h1 != h2


def test_baseline_path_format():
    """基线路径格式正确。"""
    p = _baseline_path("/tmp/test", (1280, 720))
    assert p.suffix == ".png"
    assert "visual_baselines" in str(p)


def test_result_summary():
    """summary 文本格式。"""
    r = VisualDiffResult(passed=True, cwd="/tmp", checked=False, skip_reason="no html")
    assert "跳过" in r.summary()
    r2 = VisualDiffResult(passed=True, cwd="/tmp", checked=True, screenshot_saved=True, baseline_exists=False)
    assert "基线已保存" in r2.summary()
    r3 = VisualDiffResult(passed=True, cwd="/tmp", checked=True, diff_pct=0.01)
    assert "通过" in r3.summary()
