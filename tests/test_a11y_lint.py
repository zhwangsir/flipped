"""a11y_lint 单元测试（M11.3）。

覆盖：
1. 真实渲染：Playwright + axe-core 扫描无障碍违规
2. 优雅降级：无 HTML / 无 axe.min.js / 无 Playwright 时不崩溃
3. combined_verifier_with_a11y 三重校验
4. severity 映射
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from driving.a11y_lint import (
    A11yLintResult,
    A11yViolation,
    scan_a11y,
    make_a11y_verifier,
    combined_verifier_with_a11y,
    _SEVERITY_MAP,
    _ensure_axe_js,
)


def _write(cwd: Path, name: str, content: str) -> Path:
    p = cwd / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return p


# ---------- 优雅降级测试 ----------

def test_no_html_skips():
    """目录里没有 HTML → 跳过 a11y。"""
    with tempfile.TemporaryDirectory() as d:
        r = scan_a11y(d)
        assert not r.checked
        assert "HTML" in r.skip_reason or "index" in r.skip_reason
        assert r.passed  # 跳过算通过


def test_no_axe_js_skips(tmp_path):
    """axe.min.js 不可用 → 优雅跳过。"""
    _write(tmp_path, "index.html", "<html><body><h1>hi</h1></body></html>")
    with patch("driving.a11y_lint._ensure_axe_js", return_value=None):
        r = scan_a11y(tmp_path)
    assert not r.checked
    assert "axe" in r.skip_reason.lower()
    assert r.passed


def test_no_playwright_skips(tmp_path):
    """Playwright 未安装 → 优雅跳过。"""
    _write(tmp_path, "index.html", "<html><body><h1>hi</h1></body></html>")
    with patch("driving.a11y_lint._ensure_axe_js", return_value="var axe = {}; axe.run = ()=>[];"), \
         patch("builtins.__import__", side_effect=lambda *a, **k: (_ for _ in ()).throw(ImportError("no playwright")) if "playwright" in str(a[0]) else __import__(*a, **k)):
        r = scan_a11y(tmp_path)
    assert not r.checked
    assert "playwright" in r.skip_reason.lower() or "执行失败" in r.skip_reason or "axe" in r.skip_reason.lower()


# ---------- severity 映射 ----------

def test_severity_map():
    assert _SEVERITY_MAP["critical"] == "error"
    assert _SEVERITY_MAP["serious"] == "error"
    assert _SEVERITY_MAP["moderate"] == "warning"
    assert _SEVERITY_MAP["minor"] == "warning"


def test_result_summary():
    r = A11yLintResult(passed=True, cwd="/tmp", checked=False, skip_reason="no html")
    assert "跳过" in r.summary()
    r2 = A11yLintResult(passed=True, cwd="/tmp", checked=True, violations=[])
    assert "a11y 通过" in r2.summary()
    r3 = A11yLintResult(passed=False, cwd="/tmp", checked=True, violations=[
        A11yViolation(rule="color-contrast", severity="error", detail="bad contrast")
    ])
    assert "a11y 未通过" in r3.summary()


# ---------- verifier 接口 ----------

def test_make_a11y_verifier_no_html():
    """无 HTML 时 verifier 返回 passed=True。"""
    with tempfile.TemporaryDirectory() as d:
        v = make_a11y_verifier()
        ok, msg = v(["true"], d)
        assert ok
        assert "跳过" in msg or "a11y" in msg


def test_combined_verifier_with_a11y_accessible_html(axe_available, playwright_available):
    """三重校验：合规 HTML 通过 base + design-lint + a11y。"""
    with tempfile.TemporaryDirectory() as d:
        _write(Path(d), "index.html", """
            <!DOCTYPE html>
            <html lang="zh">
            <head><title>Test</title></head>
            <body style="background:#0D0D12;color:#F5F5F5">
              <main>
                <h1>标题</h1>
                <p>内容</p>
              </main>
              <style>button:hover{color:#0A84FF}@media(max-width:768px){body{}}</style>
            </body></html>
        """)
        base = lambda cmd, cwd: (True, "ok")
        v = combined_verifier_with_a11y(base, "dark")
        ok, msg = v(["true"], d)
        assert ok, msg
        assert "ok" in msg
        assert "design-lint" in msg
        assert "a11y" in msg


# ---------- 真实渲染测试（需要 Playwright + axe.min.js） ----------

@pytest.fixture
def axe_available():
    """检查 axe.min.js 是否可用，不可用时 skip。"""
    js = _ensure_axe_js()
    if not js:
        pytest.skip("axe.min.js 不可用（无网络下载）")
    return js


@pytest.fixture
def playwright_available():
    """检查 Playwright 是否可用。"""
    try:
        from playwright.sync_api import sync_playwright
        p = sync_playwright().start()
        b = p.chromium.launch(headless=True)
        b.close()
        p.stop()
    except Exception as e:
        pytest.skip(f"Playwright/Chromium 不可用: {type(e).__name__}")


def test_scan_a11y_clean_html(axe_available, playwright_available):
    """无障碍合规的 HTML → passed=True，无 error 级违规。"""
    with tempfile.TemporaryDirectory() as d:
        _write(Path(d), "index.html", """
            <!DOCTYPE html>
            <html lang="zh">
            <head><title>Test</title></head>
            <body>
                <main>
                    <h1>标题</h1>
                    <p>这是一段内容。</p>
                    <button type="button">点击</button>
                    <img src="data:image/gif;base64,R0lGODlhAQABAAAAACw=" alt="描述">
                </main>
            </body>
            </html>
        """)
        r = scan_a11y(d)
        assert r.checked
        # 可能有一些 minor warning（如 button 无 aria-label），但不应有 error
        errors = [v for v in r.violations if v.severity == "error"]
        assert len(errors) == 0, [f"{v.rule}: {v.detail}" for v in errors]


def test_scan_a11y_missing_alt(axe_available, playwright_available):
    """图片缺少 alt → axe-core 报 image-alt 违规（critical/serious）。"""
    with tempfile.TemporaryDirectory() as d:
        _write(Path(d), "index.html", """
            <!DOCTYPE html>
            <html lang="zh">
            <head><title>Test</title></head>
            <body>
                <main>
                    <h1>标题</h1>
                    <img src="data:image/gif;base64,R0lGODlhAQABAAAAACw=">
                </main>
            </body>
            </html>
        """)
        r = scan_a11y(d)
        assert r.checked
        # image-alt 是 critical/serious 级
        has_image_alt = any(v.rule == "image-alt" for v in r.violations)
        assert has_image_alt, "应该检测到 image-alt 违规"
        assert not r.passed  # 有 error 级违规


def test_scan_a11y_specified_html_file(axe_available, playwright_available):
    """可以指定 HTML 文件路径。"""
    with tempfile.TemporaryDirectory() as d:
        _write(Path(d), "page.html", """
            <!DOCTYPE html>
            <html lang="en">
            <head><title>Page</title></head>
            <body><h1>Page</h1></body>
            </html>
        """)
        r = scan_a11y(d, html_file="page.html")
        assert r.checked
        assert "page.html" in r.html_file


def test_ensure_axe_js_cache(axe_available):
    """_ensure_axe_js 缓存命中时返回内容。"""
    js = _ensure_axe_js()
    assert js is not None
    assert len(js) > 1000
