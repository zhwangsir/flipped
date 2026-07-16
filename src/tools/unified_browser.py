"""统一浏览器工具 — 内置 Playwright 浏览器，支持渲染、交互、测试、搜索。

开箱即用：无需外部服务、无需配置，安装依赖后直接可用。

核心能力：
1. browser_render()    — 渲染页面，返回截图 + DOM 元素
2. browser_click()     — 点击页面元素
3. browser_type()      — 在输入框中输入文本
4. browser_navigate()  — 导航到新 URL
5. browser_search()    — 通过浏览器搜索（支持 DuckDuckGo、Bing）

用于开发 web 项目时直接操控内置浏览器进行测试。
搜索功能可被 tools.web_search 调用（SEARCH_MODE=browser）。
"""
from __future__ import annotations

import asyncio
import base64
import glob
import os
from typing import Any

_VIEWPORT = {"width": 1280, "height": 800}
_NAV_TIMEOUT = 30000
_MAX_ELEMENTS = 400

_SEARCH_ENGINES = {
    "duckduckgo": {
        "url": "https://duckduckgo.com",
        "query_selector": 'input[name="q"]',
        "results_selector": "article[data-layout='organic']",
        "title_selector": "h2, .result__title",
        "url_selector": "a.result__a, .result__url",
        "snippet_selector": ".result__snippet",
    },
    "bing": {
        "url": "https://www.bing.com",
        "query_selector": 'input[name="q"]',
        "results_selector": ".b_algo",
        "title_selector": "h2",
        "url_selector": "a",
        "snippet_selector": ".b_caption p",
    },
}

_DEFAULT_SEARCH_ENGINE = "duckduckgo"


def _chromium_executable() -> str | None:
    """找缓存里最新的完整 Chromium 可执行文件。"""
    base = os.path.expanduser("~/Library/Caches/ms-playwright")
    patterns = [
        os.path.join(base, "chromium-*/chrome-*/*.app/Contents/MacOS/*"),
        os.path.join(base, "chromium-*/chrome-linux/chrome"),
    ]
    found: list[str] = []
    for p in patterns:
        found.extend(glob.glob(p))
    found = [c for c in found if os.path.isfile(c) and "headless_shell" not in c]
    found.sort(reverse=True)
    return found[0] if found else None


async def _get_browser_context(headless: bool = True):
    """获取 Playwright 浏览器上下文。"""
    from playwright.async_api import async_playwright

    exe = _chromium_executable()
    async with async_playwright() as pw:
        launch_kwargs: dict[str, Any] = {"headless": headless}
        if exe:
            launch_kwargs["executable_path"] = exe
        browser = await pw.chromium.launch(**launch_kwargs)
        try:
            yield browser
        finally:
            await browser.close()


async def browser_render_async(url: str, headless: bool = True) -> dict[str, Any]:
    """渲染页面，返回 {title, screenshot(dataURL), elements, viewport}。"""
    async for browser in _get_browser_context(headless):
        page = await browser.new_page(viewport=_VIEWPORT)
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=_NAV_TIMEOUT)
            try:
                await page.wait_for_load_state("networkidle", timeout=3000)
            except Exception:
                pass
            shot = await page.screenshot(type="jpeg", quality=70, full_page=False)
            elements = await _extract_elements(page)
            title = await page.title()
        finally:
            await page.close()

    return {
        "url": url,
        "title": title,
        "screenshot": "data:image/jpeg;base64," + base64.b64encode(shot).decode(),
        "elements": elements,
        "viewport": _VIEWPORT,
    }


def browser_render(url: str, headless: bool = True, timeout: float = 30.0) -> dict[str, Any]:
    """同步包装：渲染页面，返回 {title, screenshot, elements, viewport}。"""
    try:
        return asyncio.run(asyncio.wait_for(
            browser_render_async(url, headless),
            timeout=timeout,
        ))
    except asyncio.TimeoutError:
        raise RuntimeError(f"渲染超时({timeout}s)") from None
    except Exception as e:
        raise RuntimeError(f"渲染失败: {type(e).__name__}: {e}") from e


async def _extract_elements(page) -> list[dict]:
    """抽取可见的交互元素及其包围盒。"""
    extract_js = """() => {
      const cssName = (s) => (window.CSS && CSS.escape) ? CSS.escape(s) : s;
      const sel = (el) => {
        if (el.id) return '#' + cssName(el.id);
        let s = el.tagName.toLowerCase();
        if (el.classList && el.classList.length)
          s += '.' + [...el.classList].slice(0, 2).map(cssName).join('.');
        return s;
      };
      const out = [];
      const nodes = document.querySelectorAll(
        'h1,h2,h3,h4,p,a,button,input,textarea,select,img,[role=button],li,label'
      );
      for (const el of nodes) {
        const r = el.getBoundingClientRect();
        if (r.width < 4 || r.height < 4) continue;
        if (r.bottom < 0 || r.top > window.innerHeight) continue;
        const st = getComputedStyle(el);
        if (st.visibility === 'hidden' || st.display === 'none' || +st.opacity === 0) continue;
        out.push({
          tag: el.tagName.toLowerCase(),
          selector: sel(el),
          text: (el.innerText || el.value || el.alt || '').trim().slice(0, 80),
          box: { x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height) },
        });
        if (out.length >= %d) break;
      }
      return out;
    }""" % _MAX_ELEMENTS
    return await page.evaluate(extract_js)


async def browser_click_async(url: str, selector: str) -> dict[str, Any]:
    """打开页面并点击指定元素。"""
    async for browser in _get_browser_context(headless=True):
        page = await browser.new_page(viewport=_VIEWPORT)
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=_NAV_TIMEOUT)
            await page.click(selector)
            try:
                await page.wait_for_load_state("networkidle", timeout=3000)
            except Exception:
                pass
            shot = await page.screenshot(type="jpeg", quality=70, full_page=False)
            elements = await _extract_elements(page)
            title = await page.title()
        finally:
            await page.close()

    return {
        "url": url,
        "title": title,
        "screenshot": "data:image/jpeg;base64," + base64.b64encode(shot).decode(),
        "elements": elements,
        "viewport": _VIEWPORT,
    }


def browser_click(url: str, selector: str, timeout: float = 30.0) -> dict[str, Any]:
    """同步包装：打开页面并点击指定元素。"""
    try:
        return asyncio.run(asyncio.wait_for(
            browser_click_async(url, selector),
            timeout=timeout,
        ))
    except asyncio.TimeoutError:
        raise RuntimeError(f"操作超时({timeout}s)") from None
    except Exception as e:
        raise RuntimeError(f"操作失败: {type(e).__name__}: {e}") from e


async def browser_type_async(url: str, selector: str, text: str) -> dict[str, Any]:
    """打开页面并在指定元素中输入文本。"""
    async for browser in _get_browser_context(headless=True):
        page = await browser.new_page(viewport=_VIEWPORT)
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=_NAV_TIMEOUT)
            await page.fill(selector, text)
            shot = await page.screenshot(type="jpeg", quality=70, full_page=False)
            elements = await _extract_elements(page)
            title = await page.title()
        finally:
            await page.close()

    return {
        "url": url,
        "title": title,
        "screenshot": "data:image/jpeg;base64," + base64.b64encode(shot).decode(),
        "elements": elements,
        "viewport": _VIEWPORT,
    }


def browser_type(url: str, selector: str, text: str, timeout: float = 30.0) -> dict[str, Any]:
    """同步包装：打开页面并在指定元素中输入文本。"""
    try:
        return asyncio.run(asyncio.wait_for(
            browser_type_async(url, selector, text),
            timeout=timeout,
        ))
    except asyncio.TimeoutError:
        raise RuntimeError(f"操作超时({timeout}s)") from None
    except Exception as e:
        raise RuntimeError(f"操作失败: {type(e).__name__}: {e}") from e


async def browser_navigate_async(url: str) -> dict[str, Any]:
    """导航到新 URL，返回页面状态。"""
    async for browser in _get_browser_context(headless=True):
        page = await browser.new_page(viewport=_VIEWPORT)
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=_NAV_TIMEOUT)
            try:
                await page.wait_for_load_state("networkidle", timeout=3000)
            except Exception:
                pass
            shot = await page.screenshot(type="jpeg", quality=70, full_page=False)
            elements = await _extract_elements(page)
            title = await page.title()
            current_url = page.url
        finally:
            await page.close()

    return {
        "url": current_url,
        "title": title,
        "screenshot": "data:image/jpeg;base64," + base64.b64encode(shot).decode(),
        "elements": elements,
        "viewport": _VIEWPORT,
    }


def browser_navigate(url: str, timeout: float = 30.0) -> dict[str, Any]:
    """同步包装：导航到新 URL，返回页面状态。"""
    try:
        return asyncio.run(asyncio.wait_for(
            browser_navigate_async(url),
            timeout=timeout,
        ))
    except asyncio.TimeoutError:
        raise RuntimeError(f"导航超时({timeout}s)") from None
    except Exception as e:
        raise RuntimeError(f"导航失败: {type(e).__name__}: {e}") from e


async def browser_evaluate_async(url: str, js_code: str) -> Any:
    """打开页面并执行 JavaScript 代码，返回结果。"""
    async for browser in _get_browser_context(headless=True):
        page = await browser.new_page(viewport=_VIEWPORT)
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=_NAV_TIMEOUT)
            result = await page.evaluate(js_code)
        finally:
            await page.close()

    return result


def browser_evaluate(url: str, js_code: str, timeout: float = 30.0) -> Any:
    """同步包装：打开页面并执行 JavaScript 代码。"""
    try:
        return asyncio.run(asyncio.wait_for(
            browser_evaluate_async(url, js_code),
            timeout=timeout,
        ))
    except asyncio.TimeoutError:
        raise RuntimeError(f"执行超时({timeout}s)") from None
    except Exception as e:
        raise RuntimeError(f"执行失败: {type(e).__name__}: {e}") from e


async def browser_search_async(
    query: str,
    max_results: int = 5,
    engine: str = _DEFAULT_SEARCH_ENGINE,
) -> list[dict]:
    """通过浏览器搜索，返回 [{title, url, snippet}]。"""
    engine_config = _SEARCH_ENGINES.get(engine) or _SEARCH_ENGINES[_DEFAULT_SEARCH_ENGINE]

    async for browser in _get_browser_context(headless=True):
        page = await browser.new_page(viewport=_VIEWPORT)
        try:
            await page.goto(engine_config["url"], wait_until="domcontentloaded", timeout=_NAV_TIMEOUT)
            await page.fill(engine_config["query_selector"], query)
            await page.press(engine_config["query_selector"], "Enter")
            try:
                await page.wait_for_load_state("networkidle", timeout=5000)
            except Exception:
                pass

            await page.wait_for_selector(engine_config["results_selector"], timeout=10000)

            results = await page.evaluate("""(selector, titleSel, urlSel, snippetSel, maxResults) => {
                const items = Array.from(document.querySelectorAll(selector));
                return items.slice(0, maxResults).map(item => {
                    const titleEl = item.querySelector(titleSel);
                    const urlEl = item.querySelector(urlSel);
                    const snippetEl = item.querySelector(snippetSel);
                    return {
                        title: titleEl ? titleEl.innerText.trim() : '',
                        url: urlEl ? urlEl.href || urlEl.innerText.trim() : '',
                        snippet: snippetEl ? snippetEl.innerText.trim() : '',
                    };
                }).filter(r => r.url && r.title);
            }""", engine_config["results_selector"], engine_config["title_selector"],
               engine_config["url_selector"], engine_config["snippet_selector"], max_results)
        finally:
            await page.close()

    return results


def browser_search(
    query: str,
    max_results: int = 5,
    engine: str = _DEFAULT_SEARCH_ENGINE,
    timeout: float = 60.0,
) -> list[dict]:
    """同步包装：通过浏览器搜索，返回 [{title, url, snippet}]。

    开箱即用：使用内置 Playwright 浏览器访问搜索引擎。
    支持引擎：duckduckgo（默认）、bing。

    注意：浏览器搜索启动较慢（需启动 Chromium），但结果更真实、全面。
    快速搜索请使用 tools.web_search（API 模式）。
    """
    if not query or not query.strip():
        raise ValueError("query 不能为空")

    try:
        return asyncio.run(asyncio.wait_for(
            browser_search_async(query.strip(), max_results, engine),
            timeout=timeout,
        ))
    except asyncio.TimeoutError:
        raise RuntimeError(f"搜索超时({timeout}s)") from None
    except Exception as e:
        raise RuntimeError(f"搜索失败: {type(e).__name__}: {e}") from e


if __name__ == "__main__":
    import sys
    url = sys.argv[1] if len(sys.argv) > 1 else "https://example.com"
    result = browser_render(url)
    print(f"URL: {result['url']}")
    print(f"Title: {result['title']}")
    print(f"Elements: {len(result['elements'])}")
    print("Browser tool: OK")
