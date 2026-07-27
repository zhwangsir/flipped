"""api.browser 单元测试 — 真内核渲染桥（Playwright / Chromium）。

覆盖目标函数（src/api/browser.py）：
  - _chromium_executable(): 缓存扫描 + 版本降序 + headless_shell 过滤
  - render_page(url): async 渲染流程（launch/new_page/goto/screenshot/evaluate/title/close）

设计原则（呼应 AGENTS.md §3）：
  - 不依赖真 Chromium，全部用 MagicMock / AsyncMock 注入
  - 不写空壳断言；每个用例验证 ≥1 个真实行为（调用参数 / 返回结构 / 异常路径）
  - 失败不准注释、不准改宽断言
"""
from __future__ import annotations

import asyncio
import base64
import os
import struct
import sys
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from api import browser  # noqa: E402


# ---------------------------------------------------------------------------
# _chromium_executable
# ---------------------------------------------------------------------------

def _patch_fs(monkeypatch, expanduser_base: str, glob_results: dict[str, list[str]], isfile_set: set[str]):
    """把 os.path.expanduser / glob.glob / os.path.isfile 替换成受控实现。"""
    monkeypatch.setattr(
        browser.os.path,
        "expanduser",
        lambda p: expanduser_base if p == "~/Library/Caches/ms-playwright" else p,
    )

    def _glob(pattern: str, *args, **kwargs):
        return list(glob_results.get(pattern, []))

    monkeypatch.setattr(browser.glob, "glob", _glob)
    monkeypatch.setattr(browser.os.path, "isfile", lambda p: p in isfile_set)


def test_chromium_executable_returns_none_when_no_cache(monkeypatch):
    """边界：缓存目录里没有任何匹配 → 返回 None（让 playwright 用默认）。"""
    _patch_fs(monkeypatch, "/fake/cache", {}, set())
    assert browser._chromium_executable() is None


def test_chromium_executable_picks_highest_version(monkeypatch):
    """正常路径：多个 chromium-* 同时存在时，按版本号降序取最新。"""
    base = "/fake/cache"
    mac_pattern = os.path.join(base, "chromium-*/chrome-*/*.app/Contents/MacOS/*")
    candidates = [
        os.path.join(base, "chromium-1217/chrome-1217/Chromium.app/Contents/MacOS/Chromium"),
        os.path.join(base, "chromium-1223/chrome-1223/Chromium.app/Contents/MacOS/Chromium"),
        os.path.join(base, "chromium-1100/chrome-1100/Chromium.app/Contents/MacOS/Chromium"),
    ]
    _patch_fs(monkeypatch, base, {mac_pattern: candidates}, set(candidates))
    result = browser._chromium_executable()
    assert result is not None
    assert "chromium-1223" in result, "应取版本号最大的 chromium-1223"
    assert "chromium-1217" not in result


def test_chromium_executable_filters_headless_shell(monkeypatch):
    """异常场景：headless_shell-* 路径不应被选中（与完整 chromium 区分）。"""
    base = "/fake/cache"
    mac_pattern = os.path.join(base, "chromium-*/chrome-*/*.app/Contents/MacOS/*")
    candidates = [
        os.path.join(base, "chromium-1223/chrome-1223/Headless Shell.app/Contents/MacOS/headless_shell"),
        os.path.join(base, "chromium-1217/chrome-1217/Chromium.app/Contents/MacOS/Chromium"),
    ]
    _patch_fs(monkeypatch, base, {mac_pattern: candidates}, set(candidates))
    result = browser._chromium_executable()
    # headless_shell 字符串本身被过滤，但"Headless Shell.app"路径里没有 headless_shell 子串——
    # 验证逻辑是 "headless_shell" not in c，所以 Headless Shell 路径会被保留。
    # 此用例锁定该行为：仅过滤路径里包含 "headless_shell" 的项。
    assert result is not None
    assert "headless_shell" not in result


def test_chromium_executable_filters_nonexistent_files(monkeypatch):
    """异常场景：glob 命中但 os.path.isfile=False（如目录或符号链接失效）→ 过滤掉。"""
    base = "/fake/cache"
    mac_pattern = os.path.join(base, "chromium-*/chrome-*/*.app/Contents/MacOS/*")
    candidates = [
        os.path.join(base, "chromium-1223/chrome-1223/Chromium.app/Contents/MacOS/Chromium"),
        os.path.join(base, "chromium-9999/chrome-9999/Chromium.app/Contents/MacOS/Chromium"),  # 不存在
    ]
    exists = {candidates[0]}
    _patch_fs(monkeypatch, base, {mac_pattern: candidates}, exists)
    result = browser._chromium_executable()
    assert result == candidates[0], "应跳过 isfile=False 的项，选真实存在的"


def test_chromium_executable_supports_linux_pattern(monkeypatch):
    """边界：macOS 模式无命中时，回退到 Linux chrome-linux/chrome 路径。"""
    base = "/fake/cache"
    mac_pattern = os.path.join(base, "chromium-*/chrome-*/*.app/Contents/MacOS/*")
    linux_pattern = os.path.join(base, "chromium-*/chrome-linux/chrome")
    linux_path = os.path.join(base, "chromium-1223/chrome-linux/chrome")
    _patch_fs(
        monkeypatch,
        base,
        {mac_pattern: [], linux_pattern: [linux_path]},
        {linux_path},
    )
    result = browser._chromium_executable()
    assert result == linux_path


# ---------------------------------------------------------------------------
# render_page
# ---------------------------------------------------------------------------

def _make_fake_playwright(
    *,
    title: str = "Example Domain",
    elements: list | None = None,
    screenshot_bytes: bytes = b"\xff\xd8\xff\xe0fakejpegdata",
    goto_raises: Exception | None = None,
    wait_for_load_raises: Exception | None = None,
):
    """构造一整套 async_playwright 调用链的 Mock。

    返回 (async_playwright_mock, page_mock, browser_mock, launch_kwargs_capture)。
    launch_kwargs_capture 是一个 list，launch 调用时会把 kwargs 存进去。
    """
    page = MagicMock()
    page.goto = AsyncMock()
    if goto_raises is not None:
        page.goto.side_effect = goto_raises
    page.wait_for_load_state = AsyncMock()
    if wait_for_load_raises is not None:
        page.wait_for_load_state.side_effect = wait_for_load_raises
    page.screenshot = AsyncMock(return_value=screenshot_bytes)
    page.evaluate = AsyncMock(return_value=elements if elements is not None else [])
    page.title = AsyncMock(return_value=title)

    browser_mock = MagicMock()
    browser_mock.new_page = AsyncMock(return_value=page)
    browser_mock.close = AsyncMock()

    pw = MagicMock()
    pw.chromium = MagicMock()

    launch_kwargs_capture: list[dict] = []

    async def _launch(**kwargs):
        launch_kwargs_capture.append(kwargs)
        return browser_mock

    pw.chromium.launch = _launch

    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=pw)
    cm.__aexit__ = AsyncMock(return_value=None)

    async_playwright_mock = MagicMock(return_value=cm)
    return async_playwright_mock, page, browser_mock, launch_kwargs_capture


def test_render_page_returns_expected_structure(monkeypatch):
    """正常路径：返回 {url, title, screenshot(dataURL), elements, viewport}。"""
    fake_elements = [{"tag": "a", "selector": "#go", "text": "Go", "box": {"x": 1, "y": 2, "w": 10, "h": 5}}]
    ap, page, browser_mock, launch_cap = _make_fake_playwright(
        title="Hello", elements=fake_elements, screenshot_bytes=b"\x01\x02\x03",
    )
    monkeypatch.setattr(browser, "_chromium_executable", lambda: None)
    monkeypatch.setattr("playwright.async_api.async_playwright", ap)

    result = asyncio.run(browser.render_page("https://example.com"))

    assert result["url"] == "https://example.com"
    assert result["title"] == "Hello"
    assert result["elements"] == fake_elements
    assert result["viewport"] == {"width": 1280, "height": 800}
    # data URL 前缀 + base64 编码内容
    assert result["screenshot"].startswith("data:image/jpeg;base64,")
    encoded = result["screenshot"].split(",", 1)[1]
    assert base64.b64decode(encoded) == b"\x01\x02\x03"
    # launch 必须无 executable_path（_chromium_executable 返回 None）
    assert launch_cap == [{"headless": True}], f"实际: {launch_cap}"
    # browser.close 必须被调用（资源清理）
    browser_mock.close.assert_awaited_once()
    # viewport 传给 new_page
    browser_mock.new_page.assert_awaited_once_with(viewport={"width": 1280, "height": 800})


def test_render_page_uses_cached_executable_when_available(monkeypatch):
    """边界：_chromium_executable 返回路径时，launch_kwargs 应含 executable_path。"""
    ap, _page, browser_mock, launch_cap = _make_fake_playwright()
    monkeypatch.setattr(browser, "_chromium_executable", lambda: "/fake/chromium-1223/chrome")
    monkeypatch.setattr("playwright.async_api.async_playwright", ap)

    asyncio.run(browser.render_page("https://x.test"))

    assert launch_cap == [{"headless": True, "executable_path": "/fake/chromium-1223/chrome"}]


def test_render_page_swallows_networkidle_timeout(monkeypatch):
    """异常场景：wait_for_load_state('networkidle') 抛错时必须被吞掉，不影响后续。"""
    ap, page, browser_mock, _cap = _make_fake_playwright(
        wait_for_load_raises=TimeoutError("networkidle timeout"),
    )
    monkeypatch.setattr(browser, "_chromium_executable", lambda: None)
    monkeypatch.setattr("playwright.async_api.async_playwright", ap)

    result = asyncio.run(browser.render_page("https://x.test"))

    # wait_for_load_state 被调用过（即使抛错）
    page.wait_for_load_state.assert_awaited_once_with("networkidle", timeout=3000)
    # screenshot / title 仍然执行
    page.screenshot.assert_awaited_once()
    page.title.assert_awaited_once()
    assert result["title"] != ""


def test_render_page_closes_browser_even_on_goto_failure(monkeypatch):
    """异常场景：goto 抛错时，browser.close 仍应在 finally 中被调用（资源不泄漏）。"""
    ap, _page, browser_mock, _cap = _make_fake_playwright(
        goto_raises=RuntimeError("net::ERR_CONNECTION_REFUSED"),
    )
    monkeypatch.setattr(browser, "_chromium_executable", lambda: None)
    monkeypatch.setattr("playwright.async_api.async_playwright", ap)

    with pytest.raises(RuntimeError, match="ERR_CONNECTION_REFUSED"):
        asyncio.run(browser.render_page("https://down.test"))

    browser_mock.close.assert_awaited_once(), "goto 失败时 browser.close 仍必须被调用"


def test_render_page_passes_url_to_goto(monkeypatch):
    """边界：确认 page.goto 接收正确的 url / wait_until / timeout 参数。"""
    ap, page, _browser, _cap = _make_fake_playwright()
    monkeypatch.setattr(browser, "_chromium_executable", lambda: None)
    monkeypatch.setattr("playwright.async_api.async_playwright", ap)

    asyncio.run(browser.render_page("https://specific.url/path?q=1"))

    page.goto.assert_awaited_once_with(
        "https://specific.url/path?q=1",
        wait_until="domcontentloaded",
        timeout=15000,
    )


def test_render_page_screenshot_params(monkeypatch):
    """边界：screenshot 调用参数固定为 jpeg/quality=70/full_page=False（前端依赖 dataURL 格式）。"""
    ap, page, _browser, _cap = _make_fake_playwright()
    monkeypatch.setattr(browser, "_chromium_executable", lambda: None)
    monkeypatch.setattr("playwright.async_api.async_playwright", ap)

    asyncio.run(browser.render_page("https://x.test"))

    page.screenshot.assert_awaited_once_with(type="jpeg", quality=70, full_page=False)


# 防御性：保证 _EXTRACT_JS 末尾的 % MAX_ELEMENTS 替换已生效（不是格式坏串）。
def test_extract_js_has_max_elements_substituted():
    assert "%d" not in browser._EXTRACT_JS, "_EXTRACT_JS 应已替换 %d 占位符"
    assert str(browser._MAX_ELEMENTS) in browser._EXTRACT_JS
