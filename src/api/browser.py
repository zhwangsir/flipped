"""阶段② — 浏览器真内核渲染 + DOM 元素抽取（Playwright / 真 Chromium）。

右侧「浏览器」用真浏览器内核渲染目标 URL，返回截图 + 可点击的 DOM 元素框，
供实时看效果 + 选中页面元素追踪（把元素喂回 agent）。

设计取舍：v1 每次请求起一个 headless Chromium（用户显式点「预览」，非实时流），
够用且简单；后续可换常驻浏览器池优化冷启动。
"""
from __future__ import annotations

import base64
import glob
import os
from typing import Any

_VIEWPORT = {"width": 1280, "height": 800}
_NAV_TIMEOUT = 15000  # ms
_MAX_ELEMENTS = 400

# 抽取可见的内容/交互元素 + 其包围盒与简易选择器（供前端叠加可点击热区）。
_EXTRACT_JS = """() => {
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


def _chromium_executable() -> str | None:
    """找缓存里最新的完整 Chromium 可执行文件。

    绕过 playwright 版本号与已下载浏览器 build 不一致的问题（返回 None 则用 playwright 默认）。
    """
    base = os.path.expanduser("~/Library/Caches/ms-playwright")
    # 只匹配完整 chromium（chromium-*），不匹配 chromium_headless_shell-*
    patterns = [
        os.path.join(base, "chromium-*/chrome-*/*.app/Contents/MacOS/*"),  # macOS
        os.path.join(base, "chromium-*/chrome-linux/chrome"),              # Linux
    ]
    found: list[str] = []
    for p in patterns:
        found.extend(glob.glob(p))
    found = [c for c in found if os.path.isfile(c) and "headless_shell" not in c]
    # 版本号降序（chromium-1223 > chromium-1217）
    found.sort(reverse=True)
    return found[0] if found else None


async def render_page(url: str) -> dict[str, Any]:
    """用真 Chromium 渲染 url，返回 {title, screenshot(dataURL), elements, viewport}。"""
    from playwright.async_api import async_playwright

    exe = _chromium_executable()
    async with async_playwright() as pw:
        launch_kwargs: dict[str, Any] = {"headless": True}
        if exe:
            launch_kwargs["executable_path"] = exe
        browser = await pw.chromium.launch(**launch_kwargs)
        try:
            page = await browser.new_page(viewport=_VIEWPORT)
            await page.goto(url, wait_until="domcontentloaded", timeout=_NAV_TIMEOUT)
            try:
                await page.wait_for_load_state("networkidle", timeout=3000)
            except Exception:
                pass  # 有些页面永不 idle（轮询/长连接），忽略
            shot = await page.screenshot(type="jpeg", quality=70, full_page=False)
            elements = await page.evaluate(_EXTRACT_JS)
            title = await page.title()
        finally:
            await browser.close()

    return {
        "url": url,
        "title": title,
        "screenshot": "data:image/jpeg;base64," + base64.b64encode(shot).decode(),
        "elements": elements,
        "viewport": _VIEWPORT,
    }
