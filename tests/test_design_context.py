"""设计系统注入机制测试（M10.1）。

验证 design_context 能生成结构化的设计简报，
包含具体 hex 值、字体、动效、组件状态、响应式、无障碍要求。
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))


def test_load_design_system_returns_content():
    from driving.design_context import load_design_system
    doc = load_design_system()
    assert isinstance(doc, str)
    assert len(doc) > 100  # 非空
    assert "设计系统" in doc or "UI" in doc


def test_list_styles_has_eleven():
    from driving.design_context import list_styles
    styles = list_styles()
    assert len(styles) == 11
    for s in ("minimalism", "dark", "glassmorphism", "bento", "cyberpunk", "film_atelier"):
        assert s in styles


def test_infer_style_for_product_types():
    from driving.design_context import infer_style
    assert infer_style("AI 开发工厂") == "dark"
    assert infer_style("terminal emulator") == "dark"
    assert infer_style("landing page for SaaS") == "bento"
    assert infer_style("dashboard admin panel") == "dark"
    assert infer_style("game UI") == "cyberpunk"
    assert infer_style("organic food brand") == "organic"
    assert infer_style("3D immersive showcase") == "immersive"
    assert infer_style("unknown product") == "dark"  # 默认


def test_build_design_brief_dark_contains_hex_and_specs():
    from driving.design_context import build_design_brief
    brief = build_design_brief("dark")
    # 包具体 hex 值
    assert "#0A84FF" in brief
    assert "#0D0D12" in brief
    # 包字体
    assert "Inter" in brief
    # 包设计原则
    assert "surface" in brief.lower() or "elevated" in brief.lower()
    # 包组件状态
    assert "hover" in brief
    assert "focus" in brief
    assert "disabled" in brief
    # 包响应式
    assert "768px" in brief
    assert "1024px" in brief
    # 包无障碍
    assert "WCAG" in brief
    assert "4.5:1" in brief
    # 包 CSS variables 要求
    assert "CSS variables" in brief or "--color-" in brief


def test_build_design_brief_auto_infers_style():
    from driving.design_context import build_design_brief
    brief = build_design_brief("auto", product_type="developer tool")
    # 应推断为 dark
    assert "Dark Mode" in brief or "dark" in brief.lower()
    assert "#0A84FF" in brief


def test_build_design_brief_with_extra_constraints():
    from driving.design_context import build_design_brief
    brief = build_design_brief("minimalism", constraints="必须支持暗色模式切换")
    assert "必须支持暗色模式切换" in brief


def test_build_design_brief_invalid_style_falls_back():
    from driving.design_context import build_design_brief
    brief = build_design_brief("nonexistent_style", product_type="dashboard")
    # 应回退到推断的风格
    assert "#0A84FF" in brief  # dark 风格的 accent


def test_build_design_brief_cyberpunk_has_neon():
    from driving.design_context import build_design_brief
    brief = build_design_brief("cyberpunk")
    assert "#00FFF5" in brief  # neon cyan
    assert "#FF0080" in brief  # neon pink
    assert "JetBrains Mono" in brief


def test_build_design_brief_immersive_has_3d():
    from driving.design_context import build_design_brief
    brief = build_design_brief("immersive")
    assert "perspective" in brief
    assert "parallax" in brief
    assert "translateZ" in brief


# ---------- M19: Film Atelier 风格 + 设计质量校验器 ----------


def test_film_atelier_style_exists():
    """Film Atelier 暗房编辑台风格——用户偏好的设计方向。"""
    from driving.design_context import build_design_brief
    brief = build_design_brief("film_atelier")
    assert "#C9A96E" in brief  # accent
    assert "#0D0D12" in brief  # bg
    assert "#E8E6E1" in brief  # text
    assert "Playfair" in brief  # 衬线标题
    assert "暗房" in brief or "atelier" in brief.lower() or "退居幕后" in brief
    # 禁止项
    assert "彩虹" in brief or "rainbow" in brief.lower()
    assert "粒子" in brief


def test_infer_style_film_atelier():
    """infer_style 应匹配 Film Atelier 关键词。"""
    from driving.design_context import infer_style
    assert infer_style("Film Atelier 暗房风格") == "film_atelier"
    assert infer_style("film_atelier design") == "film_atelier"
    assert infer_style("暗房编辑台") == "film_atelier"


def test_build_design_brief_compact_film_atelier():
    """精简版 brief 也包含 film_atelier 的 hex 值。"""
    from driving.design_context import build_design_brief_compact
    brief = build_design_brief_compact("film_atelier")
    assert "#C9A96E" in brief  # accent
    assert "#0D0D12" in brief  # bg
    assert "#E8E6E1" in brief  # text


def test_lint_design_quality_good_html():
    """良好 HTML 文件应无违规。"""
    import tempfile
    import os
    from driving.design_context import lint_design_quality

    good_html = """<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
:root { --color-accent: #0A84FF; --color-bg: #0D0D12; --color-text: #F5F5F5; }
body { transition: opacity 0.3s ease; transform: translateY(0); }
</style>
</head>
<body>
<header><nav>Logo</nav></header>
<main><section><h1>Title</h1></section></main>
<footer>Copyright</footer>
</body>
</html>"""

    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(good_html)
        violations = lint_design_quality(td)

    # 不应有 error 级别违规
    errors = [v for v in violations if v["severity"] == "error"]
    assert errors == [], f"不应有 error 违规: {errors}"


def test_lint_design_quality_missing_viewport():
    """缺少 viewport 应报 error。"""
    import tempfile
    import os
    from driving.design_context import lint_design_quality

    bad_html = """<html><head></head><body>
<header>Header</header><main><section>Content</section></main><footer>Footer</footer>
</body></html>"""

    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(bad_html)
        violations = lint_design_quality(td)

    viewport_violations = [v for v in violations if v["rule"] == "meta_viewport"]
    assert len(viewport_violations) == 1
    assert viewport_violations[0]["severity"] == "error"


def test_lint_design_quality_missing_alt():
    """img 缺少 alt 应报 error。"""
    import tempfile
    import os
    from driving.design_context import lint_design_quality

    html_with_img = """<html lang="en"><head><meta name="viewport" content="width=device-width"></head>
<body><header>Header</header><main><section>
<img src="photo.jpg" width="100">
</section></main><footer>Footer</footer></body></html>"""

    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html_with_img)
        violations = lint_design_quality(td)

    alt_violations = [v for v in violations if v["rule"] == "img_alt_missing"]
    assert len(alt_violations) == 1
    assert alt_violations[0]["severity"] == "error"


def test_lint_design_quality_bad_transition():
    """transition 使用非 transform/opacity 属性应报 warning。"""
    import tempfile
    import os
    from driving.design_context import lint_design_quality

    html_bad_transition = """<html lang="en"><head>
<meta name="viewport" content="width=device-width">
<style>.card { transition: margin 0.3s ease; }</style>
</head><body><header>H</header><main><section>S</section></main><footer>F</footer>
</body></html>"""

    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html_bad_transition)
        violations = lint_design_quality(td)

    perf_violations = [v for v in violations if v["rule"] == "animation_performance"]
    assert len(perf_violations) == 1
    assert perf_violations[0]["severity"] == "warning"


def test_lint_design_quality_empty_dir():
    """空目录应返回空列表。"""
    import tempfile
    from driving.design_context import lint_design_quality

    with tempfile.TemporaryDirectory() as td:
        violations = lint_design_quality(td)
    assert violations == []
