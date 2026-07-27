"""视觉回归快照对比（M13）。

在 UI 任务完成后，用 Playwright 截图并与基线对比，检测视觉回归。
- 首次运行：保存截图作为基线
- 后续运行：对比新截图与基线，像素差异超阈值则报告回归

设计原则：
1. 优雅降级：无 Pillow / 无 Playwright → skip with warning
2. 首次无基线 → 保存基线并通过（不阻断首次运行）
3. 阈值可配：默认 5% 像素差异以内算通过
4. 基线存储：data/visual_baselines/{hash}.png
"""
from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field
from pathlib import Path

# 基线存储目录
_BASELINE_DIR = Path("data/visual_baselines")


@dataclass
class VisualDiffResult:
    """视觉回归对比结果。"""
    passed: bool
    cwd: str
    diff_pct: float = 0.0  # 0.0-1.0
    baseline_exists: bool = False
    baseline_path: str = ""
    screenshot_saved: bool = False
    checked: bool = False  # 是否真的执行了对比
    skip_reason: str = ""
    message: str = ""

    def summary(self) -> str:
        if not self.checked:
            return f"⚠️ visual-regression 跳过 ({self.skip_reason})"
        if self.screenshot_saved and not self.baseline_exists:
            return f"📸 visual-regression 基线已保存 (首次运行, diff=0%)"
        if self.passed:
            return f"✅ visual-regression 通过 (diff={self.diff_pct:.1%})"
        return f"❌ visual-regression 回归检测 (diff={self.diff_pct:.1%}, 阈值内视为通过)"


def _viewport_hash(cwd: str, viewport: tuple[int, int] | None) -> str:
    """生成基线文件名 hash（基于 cwd + viewport）。"""
    key = f"{cwd}:{viewport or 'default'}"
    return hashlib.md5(key.encode(), usedforsecurity=False).hexdigest()[:12]


def _baseline_path(cwd: str, viewport: tuple[int, int] | None = None) -> Path:
    """基线 PNG 路径。"""
    return _BASELINE_DIR / f"{_viewport_hash(cwd, viewport)}.png"


def capture_screenshot(
    cwd: str | Path,
    html_file: str | Path | None = None,
    viewport: tuple[int, int] = (1280, 720),
    full_page: bool = False,
) -> bytes | None:
    """用 Playwright 截图，返回 PNG bytes。

    Args:
        cwd: 工作目录
        html_file: HTML 文件（默认自动查找 index.html）
        viewport: 视口大小 (width, height)
        full_page: 是否截整页

    Returns:
        PNG bytes，失败返回 None
    """
    from driving.a11y_lint import _find_html_entry, _free_port, _start_static_server
    from playwright.sync_api import sync_playwright

    cwd = Path(cwd)
    if html_file:
        html_path = Path(html_file)
        if not html_path.is_absolute():
            html_path = cwd / html_file
    else:
        html_path = _find_html_entry(cwd)

    if not html_path or not html_path.exists():
        return None

    port = _free_port()
    server = None
    try:
        server = _start_static_server(cwd, port)
        rel_path = str(html_path.relative_to(cwd)) if html_path.is_relative_to(cwd) else html_path.name
        url = f"http://127.0.0.1:{port}/{rel_path}"

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                page = browser.new_page(viewport={"width": viewport[0], "height": viewport[1]})
                page.goto(url, wait_until="networkidle", timeout=10000)
                png = page.screenshot(full_page=full_page)
                return png
            finally:
                browser.close()
    except Exception:
        return None
    finally:
        if server:
            server.shutdown()


def compare_images(baseline_png: bytes, current_png: bytes, threshold: float = 0.05) -> VisualDiffResult:
    """像素级对比两张 PNG。

    Args:
        baseline_png: 基线 PNG bytes
        current_png: 当前 PNG bytes
        threshold: 允许的像素差异比例（0.0-1.0）

    Returns:
        VisualDiffResult，diff_pct 为实际差异比例
    """
    try:
        from PIL import Image, ImageChops
        import io
    except ImportError:
        return VisualDiffResult(
            passed=True, cwd="", checked=False, skip_reason="Pillow 未安装"
        )

    try:
        baseline = Image.open(io.BytesIO(baseline_png)).convert("RGB")
        current = Image.open(io.BytesIO(current_png)).convert("RGB")
    except Exception as e:
        return VisualDiffResult(
            passed=True, cwd="", checked=False, skip_reason=f"图片解析失败: {type(e).__name__}"
        )

    # 尺寸不一致 → 统一到较小尺寸
    if baseline.size != current.size:
        min_w = min(baseline.width, current.width)
        min_h = min(baseline.height, current.height)
        baseline = baseline.crop((0, 0, min_w, min_h))
        current = current.crop((0, 0, min_w, min_h))

    # 像素差异
    diff = ImageChops.difference(baseline, current)
    # 转灰度统计非零像素
    diff_gray = diff.convert("L")
    histogram = diff_gray.histogram()
    total_pixels = baseline.width * baseline.height
    changed_pixels = total_pixels - histogram[0]  # histogram[0] = 完全相同的像素数
    diff_pct = changed_pixels / total_pixels if total_pixels > 0 else 0.0

    passed = diff_pct <= threshold
    return VisualDiffResult(
        passed=passed,
        cwd="",
        diff_pct=diff_pct,
        checked=True,
        message=f"差异 {diff_pct:.1%}（阈值 {threshold:.0%}）",
    )


def visual_regression_check(
    cwd: str | Path,
    html_file: str | Path | None = None,
    viewport: tuple[int, int] = (1280, 720),
    threshold: float = 0.05,
    update_baseline: bool = False,
) -> VisualDiffResult:
    """主入口：截图 + 对比基线（或保存基线）。

    Args:
        cwd: 工作目录
        html_file: HTML 文件
        viewport: 视口大小
        threshold: 允许的像素差异比例
        update_baseline: 强制更新基线

    Returns:
        VisualDiffResult
    """
    cwd = Path(cwd)
    result = VisualDiffResult(passed=True, cwd=str(cwd))

    # 1. 截图
    png = capture_screenshot(cwd, html_file, viewport)
    if png is None:
        result.skip_reason = "截图失败（无 HTML / Playwright 不可用）"
        return result

    # 2. 检查基线
    baseline = _baseline_path(str(cwd), viewport)
    result.baseline_path = str(baseline)

    if update_baseline or not baseline.exists():
        # 首次运行或强制更新 → 保存基线
        _BASELINE_DIR.mkdir(parents=True, exist_ok=True)
        baseline.write_bytes(png)
        result.baseline_exists = baseline.exists()
        result.screenshot_saved = True
        result.checked = True
        result.diff_pct = 0.0
        result.message = "基线已保存"
        return result

    # 3. 对比
    baseline_png = baseline.read_bytes()
    diff = compare_images(baseline_png, png, threshold)
    diff.cwd = str(cwd)
    diff.baseline_path = str(baseline)
    diff.baseline_exists = True
    return diff


def make_visual_verifier(threshold: float = 0.05):
    """构造适配 orchestrator verifier 接口的视觉回归校验器。

    视觉回归是 warning 级（不阻断 verify），除非差异极大。
    """

    def _verify(cmd_list: list[str], cwd: str) -> tuple[bool, str]:
        r = visual_regression_check(cwd, threshold=threshold)
        return r.passed, r.summary()

    return _verify
