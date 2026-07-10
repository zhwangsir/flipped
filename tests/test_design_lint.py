"""design_lint 单元测试（M10.4-A）。

覆盖核心校验规则：必含颜色、禁止命名色、响应式断点、组件状态、入口文件、组合 verifier。
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from driving.design_lint import (
    DesignLintResult,
    Violation,
    lint_dir,
    make_design_verifier,
    combined_verifier,
    _normalize_hex,
    _critical_hexes,
)


def _write(cwd: Path, name: str, content: str) -> Path:
    p = cwd / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return p


def test_empty_dir_passes():
    """空目录无 UI 代码 → passed=True（无可校验内容）。"""
    with tempfile.TemporaryDirectory() as d:
        r = lint_dir(d, "dark")
        assert r.passed
        assert r.checked_files == 0


def test_dark_html_with_design_colors_passes():
    """HTML 含 dark 风格的 accent #0A84FF 和 bg #0D0D12 → 通过。"""
    with tempfile.TemporaryDirectory() as d:
        _write(Path(d), "index.html", """
            <html><body style="background:#0D0D12;color:#F5F5F5">
              <button style="background:#0A84FF" onmouseover="this.style.opacity=0.8">OK</button>
              <style>
                button:hover { background: #1A6FE3; }
                @media (max-width: 768px) { body { font-size: 14px; } }
              </style>
            </body></html>
        """)
        r = lint_dir(d, "dark")
        assert r.passed, [v.detail for v in r.violations]


def test_named_colors_triggers_warning():
    """使用 color: blue → warning（不是 error，passed 仍 True）。"""
    with tempfile.TemporaryDirectory() as d:
        _write(Path(d), "index.html", """
            <html><body style="color:blue;background:#0D0D12">
            <style>
              body { color: #F5F5F5; }
              .btn { background: #0A84FF; }
              .btn:hover { color: red; }
              @media (max-width: 768px) { body {} }
            </style>
            </body></html>
        """)
        r = lint_dir(d, "dark")
        # 命名色是 warning 级，passed 仍 True（找到全部关键 hex 满足强制规则）
        assert r.passed
        warnings = [v for v in r.violations if v.rule == "no_named_colors"]
        assert len(warnings) >= 1


def test_missing_entry_file_triggers_error():
    """有 UI 文件但无 index.html 入口 → error。"""
    with tempfile.TemporaryDirectory() as d:
        _write(Path(d), "components/Header.css", "body { color: #0A84FF; } button:hover {} @media (max-width:768px){}")
        r = lint_dir(d, "dark")
        assert not r.passed
        assert any(v.rule == "entry_file" for v in r.violations)


def test_missing_responsive_triggers_warning():
    """无 @media 和 Tailwind 断点 → warning。"""
    with tempfile.TemporaryDirectory() as d:
        _write(Path(d), "index.html", """
            <html><body style="background:#0D0D12;color:#F5F5F5">
              <button style="background:#0A84FF" class="hover:bg-blue-500">OK</button>
            </body></html>
        """)
        # hover:bg-blue-500 不被识别为 md:/lg:，但 hover: 被识别为状态
        r = lint_dir(d, "dark")
        # 应该有 responsive_breakpoints warning
        has_resp_warning = any(v.rule == "responsive_breakpoints" for v in r.violations)
        assert has_resp_warning


def test_missing_component_states_triggers_warning():
    """无 hover/focus/active → warning。"""
    with tempfile.TemporaryDirectory() as d:
        _write(Path(d), "index.html", """
            <html><body style="background:#0D0D12;color:#F5F5F5">
              <div style="color:#0A84FF">Static content</div>
              <style>@media (max-width:768px){body{}}</style>
            </body></html>
        """)
        r = lint_dir(d, "dark")
        assert any(v.rule == "component_states" for v in r.violations)


def test_no_design_colors_triggers_warning():
    """有 hex 但不匹配设计系统要求 → warning。"""
    with tempfile.TemporaryDirectory() as d:
        _write(Path(d), "index.html", """
            <html><body style="background:#123456;color:#ABCDEF">
              <style>div:hover { color: #FEDCBA; } @media (max-width:768px){body{}}</style>
            </body></html>
        """)
        r = lint_dir(d, "dark")
        # 设计系统要求的颜色（dark 风格：#0A84FF/#0D0D12/#1A1A2E/#1E1E2E/#F5F5F5/#9E9E9E）都没出现
        assert any(v.rule == "design_colors" for v in r.violations)


def test_tailwind_classes_recognized():
    """Tailwind md:/lg: 和 hover:/focus: 应被识别。"""
    with tempfile.TemporaryDirectory() as d:
        _write(Path(d), "index.html", """
            <html><body class="bg-[#0D0D12] text-[#F5F5F5]">
              <button class="bg-[#0A84FF] hover:bg-blue-600 md:text-lg lg:w-1/2">OK</button>
            </body></html>
        """)
        r = lint_dir(d, "dark")
        # 应该没有 responsive_breakpoints 和 component_states warning
        assert not any(v.rule == "responsive_breakpoints" for v in r.violations)
        assert not any(v.rule == "component_states" for v in r.violations)


def test_normalize_hex_3digit():
    """#abc → #aabbcc。"""
    assert _normalize_hex("#abc") == "#aabbcc"
    assert _normalize_hex("#0A84FF") == "#0a84ff"
    assert _normalize_hex("#0a84ff") == "#0a84ff"


def test_auto_style_inference():
    """style=auto 时根据 cwd 名字推断。"""
    with tempfile.TemporaryDirectory() as d:
        # 把目录改成包含 "dashboard" 的名字
        cwd = Path(d) / "my-dashboard"
        cwd.mkdir()
        _write(cwd, "index.html", """
            <html><body style="background:#0D0D12;color:#F5F5F5">
              <style>button:hover { color: #0A84FF; } @media (max-width:768px){body{}}</style>
            </body></html>
        """)
        r = lint_dir(cwd, "auto")
        # dashboard → dark 风格
        assert r.style == "dark"


def test_make_design_verifier():
    """make_design_verifier 返回的回调符合 verifier 接口。"""
    with tempfile.TemporaryDirectory() as d:
        _write(Path(d), "index.html", """
            <html><body style="background:#0D0D12;color:#F5F5F5">
              <style>button:hover { color: #0A84FF; } @media (max-width:768px){body{}}</style>
            </body></html>
        """)
        v = make_design_verifier("dark")
        ok, msg = v(["true"], d)
        assert ok
        assert "design-lint" in msg


def test_make_design_verifier_includes_violation_details():
    """失败时 msg 包含违规详情（hex 值缺失等），让 worker 能看到具体问题。"""
    with tempfile.TemporaryDirectory() as d:
        # 故意缺失 #0D0D12 和 #F5F5F5
        _write(Path(d), "index.html", """
            <html><body style="background:#000000;color:#ffffff">
              <style>button:hover { color: #0A84FF; } @media (max-width:768px){body{}}</style>
            </body></html>
        """)
        v = make_design_verifier("dark")
        ok, msg = v(["true"], d)
        assert not ok
        # msg 应包含违规详情，不只是 summary
        assert "required_hex_exact" in msg
        assert "#0d0d12" in msg
        assert "#f5f5f5" in msg


def test_combined_verifier_both_pass():
    """base + design 都通过 → combined 通过。"""
    with tempfile.TemporaryDirectory() as d:
        _write(Path(d), "index.html", """
            <html><body style="background:#0D0D12;color:#F5F5F5">
              <style>button:hover { color: #0A84FF; } @media (max-width:768px){body{}}</style>
            </body></html>
        """)
        base = lambda cmd, cwd: (True, "ok")
        v = combined_verifier(base, "dark")
        ok, msg = v(["true"], d)
        assert ok
        assert "ok" in msg and "design-lint" in msg


def test_combined_verifier_base_fails():
    """base 失败 → combined 失败，即使 design 通过。"""
    with tempfile.TemporaryDirectory() as d:
        _write(Path(d), "index.html", "<html><body style='background:#0D0D12'></body></html>")
        base = lambda cmd, cwd: (False, "tests failed")
        v = combined_verifier(base, "dark")
        ok, msg = v(["pytest"], d)
        assert not ok
        assert "verify" in msg


def test_skips_node_modules():
    """node_modules 里的文件应被跳过。"""
    with tempfile.TemporaryDirectory() as d:
        # 故意在 node_modules 里放带命名色的文件
        _write(Path(d), "node_modules/lib/index.html", "<body style='color:blue'>bad</body>")
        _write(Path(d), "index.html", """
            <html><body style="background:#0D0D12;color:#F5F5F5">
              <style>button:hover { color: #0A84FF; } @media (max-width:768px){body{}}</style>
            </body></html>
        """)
        r = lint_dir(d, "dark")
        # node_modules 里的命名色不应该被报告
        assert r.passed
        assert r.checked_files == 1  # 只有 index.html 被检查


def test_brief_glassmorphism():
    """glassmorphism 风格也能被 lint。"""
    with tempfile.TemporaryDirectory() as d:
        _write(Path(d), "index.html", """
            <html><body style="background:linear-gradient(135deg,#667eea,#764ba2);color:#FFFFFF">
              <div style="backdrop-filter:blur(16px);background:rgba(255,255,255,0.1)"></div>
              <style>.card:hover { transform: translateY(-2px); } @media (max-width:768px){body{}}</style>
            </body></html>
        """)
        r = lint_dir(d, "glassmorphism")
        # glassmorphism 没有 hex 必须色（colors 里是 rgba/gradient），所以设计颜色规则不触发
        assert r.passed


def test_brutalism_style():
    """brutalism 风格：纯黑白配色 + 粗边框。"""
    with tempfile.TemporaryDirectory() as d:
        _write(Path(d), "index.html", """
            <html><body style="background:#FFFFFF;color:#000000;border:3px solid #000">
              <div>BRUTAL</div>
              <style>div:hover { background: #FFFF00; } @media (max-width:768px){body{}}</style>
            </body></html>
        """)
        r = lint_dir(d, "brutalism")
        assert r.passed


# ---------- 规则 2b: required_hex_exact 强制 hex 精确匹配 ----------

def test_critical_hexes_dark():
    """dark 风格的关键 hex = accent #0A84FF + bg #0D0D12 + text #F5F5F5。"""
    hexes = _critical_hexes("dark")
    assert hexes == {"#0a84ff", "#0d0d12", "#f5f5f5"}


def test_critical_hexes_glassmorphism_skips_non_hex():
    """glassmorphism 的 bg='gradient' 不是 hex → 只返回 text #FFFFFF。"""
    hexes = _critical_hexes("glassmorphism")
    assert hexes == {"#ffffff"}


def test_critical_hexes_brutalism():
    """brutalism 无 accent，bg #FFFFFF + text #000000。"""
    hexes = _critical_hexes("brutalism")
    assert hexes == {"#ffffff", "#000000"}


def test_missing_critical_hex_triggers_error():
    """worker 把 #0D0D12 替换成 #000000 → required_hex_exact error，验证阻断。"""
    with tempfile.TemporaryDirectory() as d:
        # 故意用 #000000 替代 #0D0D12，#ffffff 替代 #F5F5F5
        _write(Path(d), "index.html", """
            <html><body style="background:#000000;color:#ffffff">
              <style>
                .btn { background: #0A84FF; }
                .btn:hover { opacity: 0.8; }
                @media (max-width:768px){body{}}
              </style>
            </body></html>
        """)
        r = lint_dir(d, "dark")
        assert not r.passed
        hex_errors = [v for v in r.violations if v.rule == "required_hex_exact"]
        assert len(hex_errors) == 1
        detail = hex_errors[0].detail
        # 缺失的 hex 值在错误信息中（消息格式：hex缺失:#0d0d12,#f5f5f5。...）
        assert "#0d0d12" in detail
        assert "#f5f5f5" in detail
        # #0a84ff 存在，不应出现在缺失列表中
        assert "#0a84ff" not in detail


def test_all_critical_hexes_present_passes():
    """全部关键 hex 值都存在 → 无 required_hex_exact 违规。"""
    with tempfile.TemporaryDirectory() as d:
        _write(Path(d), "index.html", """
            <html><body style="background:#0D0D12;color:#F5F5F5">
              <style>
                .btn { background: #0A84FF; }
                .btn:hover { opacity: 0.8; }
                @media (max-width:768px){body{}}
              </style>
            </body></html>
        """)
        r = lint_dir(d, "dark")
        assert r.passed, [v.detail for v in r.violations]
        assert not any(v.rule == "required_hex_exact" for v in r.violations)
