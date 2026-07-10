"""无障碍真实渲染检测（M11.3）。

把 design_lint 的"正则文本扫描"升级为"Playwright 真实渲染 + axe-core WCAG 扫描"。
axe-core 是 W3C 推荐的 a11y 检测库，扫描真实 DOM 能发现正则无法检测的问题：
- 缺少 alt 文本、aria 标签
- 颜色对比度不足（真实计算后而非 hex 模式匹配）
- 键盘不可达的交互元素
- 表单缺少 label 关联
- heading 层级跳跃

设计原则：
1. **优雅降级**：Playwright/axe.min.js 不可用时不阻塞 verify，只给 warning。
2. **只看真实渲染**：用 Chromium headless 加载 HTML，注入 axe-core JS 执行 axe.run()。
3. **severity 映射**：axe 的 critical/serious → error；moderate/minor → warning。
4. **单 HTML 文件优先**：UI 产物通常是单个 index.html，直接 file:// 加载即可。
   如果有相对资源（CSS/JS/img），启动本地 HTTP 服务器避免 CORS。

集成方式：
- make_a11y_verifier()：适配 orchestrator 的 verifier 接口
- combined_verifier_with_a11y(base_verifier, style)：base + design + a11y 三重校验
"""
from __future__ import annotations

import html
import os
import socket
from dataclasses import dataclass, field
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from threading import Thread

# axe-core JS 缓存路径
_AXE_JS_CACHE = Path("data/axe.min.js")
_AXE_JS_URL = "https://cdn.jsdelivr.net/npm/axe-core@4.10.0/axe.min.js"

# axe-core 严重度映射
_SEVERITY_MAP = {
    "critical": "error",
    "serious": "error",
    "moderate": "warning",
    "minor": "warning",
}


@dataclass
class A11yViolation:
    rule: str  # axe rule id, e.g. "color-contrast", "image-alt"
    severity: str  # error / warning
    detail: str
    element: str = ""  # axe 报告的元素选择器


@dataclass
class A11yLintResult:
    passed: bool
    cwd: str
    html_file: str = ""
    checked: bool = False  # 是否真的执行了 axe 扫描
    skip_reason: str = ""  # 未执行的原因
    violations: list[A11yViolation] = field(default_factory=list)

    def summary(self) -> str:
        if not self.checked:
            return f"⚠️ a11y 跳过 ({self.skip_reason})"
        errors = sum(1 for v in self.violations if v.severity == "error")
        warnings = sum(1 for v in self.violations if v.severity == "warning")
        if self.passed:
            return f"✅ a11y 通过 (warnings={warnings})"
        return f"❌ a11y 未通过 (errors={errors}, warnings={warnings})"


def _ensure_axe_js() -> str | None:
    """确保 axe.min.js 存在；缓存命中直接返回，否则尝试下载。

    无网络时返回 None（调用方优雅降级）。
    """
    if _AXE_JS_CACHE.exists() and _AXE_JS_CACHE.stat().st_size > 10000:
        return _AXE_JS_CACHE.read_text(encoding="utf-8")
    # 尝试下载
    try:
        import urllib.request

        req = urllib.request.Request(_AXE_JS_URL, headers={"User-Agent": "curl/8"})
        data = urllib.request.urlopen(req, timeout=10).read()
        _AXE_JS_CACHE.parent.mkdir(parents=True, exist_ok=True)
        _AXE_JS_CACHE.write_bytes(data)
        return data.decode("utf-8", errors="ignore")
    except Exception:
        return None


def _find_html_entry(cwd: Path) -> Path | None:
    """找到 UI 入口 HTML 文件。"""
    for name in ("index.html", "index.htm"):
        p = cwd / name
        if p.exists():
            return p
    # 兜底：任意 html
    for p in cwd.glob("*.html"):
        return p
    return None


def _free_port() -> int:
    """获取一个可用端口。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _start_static_server(cwd: Path, port: int) -> HTTPServer:
    """启动一个简单的静态文件服务器（用于加载有相对资源的 HTML）。"""

    class _Handler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(cwd), **kwargs)

        def log_message(self, *args, **kwargs):  # noqa: ARG002
            pass  # 静默日志

    server = HTTPServer(("127.0.0.1", port), _Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def scan_a11y(cwd: str | Path, html_file: str | Path | None = None, timeout_ms: int = 15000) -> A11yLintResult:
    """对目录里的 HTML 执行 axe-core 无障碍扫描。

    Args:
        cwd: 工作目录
        html_file: 指定 HTML 文件（默认自动查找 index.html）
        timeout_ms: axe.run() 超时（毫秒）

    Returns:
        A11yLintResult，passed=True 表示无 error 级违规
    """
    cwd = Path(cwd)
    result = A11yLintResult(passed=True, cwd=str(cwd))

    # 1. 找 HTML 入口
    if html_file:
        html_path = Path(html_file) if not str(html_file).startswith("/") else cwd / html_file
        if not html_path.is_absolute():
            html_path = cwd / html_file
    else:
        html_path = _find_html_entry(cwd)

    if not html_path or not html_path.exists():
        result.skip_reason = "未找到 HTML 入口文件（index.html）"
        return result

    result.html_file = str(html_path.relative_to(cwd)) if html_path.is_relative_to(cwd) else str(html_path)

    # 2. 确保 axe.min.js
    axe_js = _ensure_axe_js()
    if not axe_js:
        result.skip_reason = "axe.min.js 不可用（无网络下载）"
        return result

    # 3. Playwright 渲染 + axe 扫描
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        result.skip_reason = "playwright 未安装"
        return result

    # 启动本地 HTTP 服务器（避免相对资源 CORS / file:// 限制）
    port = _free_port()
    server = None
    try:
        server = _start_static_server(cwd, port)
        url = f"http://127.0.0.1:{port}/{result.html_file}"

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                page = browser.new_page()
                page.goto(url, wait_until="networkidle", timeout=timeout_ms)
                # 注入 axe-core
                page.evaluate(axe_js)
                # 运行 axe.run()，只取 violations
                axe_results = page.evaluate(
                    """async () => {
                        const results = await axe.run(document, {
                            runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'] },
                            resultTypes: ['violations']
                        });
                        return results.violations.map(v => ({
                            id: v.id,
                            impact: v.impact,
                            description: v.description,
                            help: v.help,
                            tags: v.tags,
                            nodes: v.nodes.map(n => ({
                                target: n.target,
                                html: n.html
                            }))
                        }));
                    }""",
                )
            finally:
                browser.close()

        # 解析结果
        for v in axe_results or []:
            severity = _SEVERITY_MAP.get(v.get("impact", "minor"), "warning")
            element = ""
            nodes = v.get("nodes") or []
            if nodes:
                target = nodes[0].get("target")
                if isinstance(target, list) and target:
                    element = str(target[0])
                elif target:
                    element = str(target)
            detail = v.get("help") or v.get("description") or v.get("id", "unknown")
            result.violations.append(A11yViolation(
                rule=v.get("id", "unknown"),
                severity=severity,
                detail=f"{detail}" + (f" (元素: {element})" if element else ""),
                element=element,
            ))

        result.checked = True
        has_errors = any(v.severity == "error" for v in result.violations)
        result.passed = not has_errors
    except Exception as e:
        result.skip_reason = f"Playwright/axe 执行失败: {type(e).__name__}: {str(e)[:120]}"
    finally:
        if server:
            server.shutdown()

    return result


def make_a11y_verifier():
    """构造适配 orchestrator verifier 接口的 a11y 校验器。

    返回的函数签名: (cmd_list, cwd) -> (ok, msg)
    a11y 违规只产生 warning（不阻断 verify），除非有 error 级违规。
    失败时 msg 包含具体违规规则和元素，方便 worker 精确修复。
    """

    def _verify(cmd_list: list[str], cwd: str) -> tuple[bool, str]:
        r = scan_a11y(cwd)
        if r.passed:
            return True, r.summary()
        # 包含具体违规细节，让 worker 知道修什么
        details = "; ".join(
            f"{v.rule}({v.element}): {v.detail[:80]}"
            for v in r.violations
            if v.severity == "error"
        )
        msg = r.summary()
        if details:
            msg += f" | 违规: {details}"
        return False, msg

    return _verify


def combined_verifier_with_a11y(base_verifier, style: str = "auto"):
    """三重校验：base(verify_cmd) + design-lint + a11y。

    用法（在 factory_loop 里）：
        verifier = combined_verifier_with_a11y(base_verifier, state.design_style)
    """
    from driving.design_lint import make_design_verifier

    design_verifier = make_design_verifier(style)
    a11y_verifier = make_a11y_verifier()

    def _verify(cmd_list: list[str], cwd: str) -> tuple[bool, str]:
        ok1, msg1 = base_verifier(cmd_list, cwd)
        ok2, msg2 = design_verifier(cmd_list, cwd)
        ok3, msg3 = a11y_verifier(cmd_list, cwd)
        if not ok1:
            return False, f"verify: {msg1}"
        if not ok2:
            return False, f"design-lint: {msg2}"
        if not ok3:
            return False, f"a11y: {msg3}"
        return True, f"{msg1}; {msg2}; {msg3}"

    return _verify
