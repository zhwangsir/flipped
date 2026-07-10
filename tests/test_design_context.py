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


# ---------- M20: design_score 评分系统 ----------


def test_design_score_perfect_html():
    """良好 HTML 应得高分。"""
    import tempfile
    import os
    from driving.design_context import design_score

    good_html = """<!DOCTYPE html>
<html lang="zh"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<style>
:root { --color-accent: #0A84FF; --color-bg: #0D0D12; --color-text: #F5F5F5; }
body { transition: opacity 0.3s ease; transform: translateY(0); }
</style>
</head><body>
<header><nav>Logo</nav></header>
<main><section><h1>Title</h1></section></main>
<footer>Copyright</footer>
</body></html>"""

    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(good_html)
        score, notes = design_score(td)

    assert score >= 80, f"良好HTML应得≥80分，实际{score}: {notes}"


def test_design_score_bad_html_low():
    """差 HTML 应得低分。"""
    import tempfile
    import os
    from driving.design_context import design_score

    bad_html = """<html><head></head><body>
<img src="x.jpg">
</body></html>"""

    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(bad_html)
        score, notes = design_score(td)

    assert score < 50, f"差HTML应得<50分，实际{score}: {notes}"


def test_design_score_empty_dir():
    """空目录应得0分。"""
    import tempfile
    from driving.design_context import design_score

    with tempfile.TemporaryDirectory() as td:
        score, notes = design_score(td)

    assert score == 0


# ---------- M22: WCAG 颜色对比度校验 ----------


def test_hex_to_rgb():
    """hex_to_rgb 应正确解析 6 位 hex 颜色。"""
    from driving.design_context import hex_to_rgb
    assert hex_to_rgb("#0A84FF") == (10, 132, 255)
    assert hex_to_rgb("#FFFFFF") == (255, 255, 255)
    assert hex_to_rgb("#000000") == (0, 0, 0)
    assert hex_to_rgb("#0a84ff") == (10, 132, 255)  # 大小写不敏感


def test_relative_luminance():
    """relative_luminance 应符合 WCAG 2.1 公式。"""
    from driving.design_context import relative_luminance
    # 纯白亮度=1
    assert abs(relative_luminance((255, 255, 255)) - 1.0) < 0.001
    # 纯黑亮度=0
    assert abs(relative_luminance((0, 0, 0)) - 0.0) < 0.001


def test_contrast_ratio_black_on_white():
    """黑底白字对比度应为 21:1（WCAG 最大值）。"""
    from driving.design_context import contrast_ratio
    ratio = contrast_ratio("#000000", "#FFFFFF")
    assert abs(ratio - 21.0) < 0.5


def test_contrast_ratio_low_contrast():
    """低对比度颜色对应小于 4.5。"""
    from driving.design_context import contrast_ratio
    # #777777 on #999999 = 低对比度
    ratio = contrast_ratio("#777777", "#999999")
    assert ratio < 4.5


def test_contrast_ratio_good_contrast():
    """高对比度颜色对应大于 4.5。"""
    from driving.design_context import contrast_ratio
    # #F5F5F5 on #0D0D12 = Film Atelier 风格的 text on bg
    ratio = contrast_ratio("#F5F5F5", "#0D0D12")
    assert ratio >= 4.5


def test_check_color_contrast_good():
    """良好对比度的 HTML 应无违规。"""
    import tempfile
    import os
    from driving.design_context import check_color_contrast

    good_html = """<!DOCTYPE html>
<html lang="zh"><head><meta name="viewport" content="width=device-width">
<style>
:root { --color-bg: #0D0D12; --color-text: #F5F5F5; }
body { background-color: #0D0D12; color: #F5F5F5; }
</style></head><body><p>Hello</p></body></html>"""

    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(good_html)
        violations = check_color_contrast(td)

    contrast_violations = [v for v in violations if v["rule"] == "color_contrast"]
    assert contrast_violations == [], f"良好对比度不应有违规: {contrast_violations}"


def test_check_color_contrast_bad():
    """低对比度 HTML 应报违规。"""
    import tempfile
    import os
    from driving.design_context import check_color_contrast

    bad_html = """<!DOCTYPE html>
<html lang="zh"><head><meta name="viewport" content="width=device-width">
<style>
body { background-color: #999999; color: #777777; }
</style></head><body><p>Low contrast text</p></body></html>"""

    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(bad_html)
        violations = check_color_contrast(td)

    contrast_violations = [v for v in violations if v["rule"] == "color_contrast"]
    assert len(contrast_violations) >= 1
    assert contrast_violations[0]["severity"] == "error"
    assert "4.5" in contrast_violations[0]["message"] or "contrast" in contrast_violations[0]["message"].lower()


def test_check_color_contrast_empty_dir():
    """空目录应返回空列表。"""
    import tempfile
    from driving.design_context import check_color_contrast

    with tempfile.TemporaryDirectory() as td:
        violations = check_color_contrast(td)
    assert violations == []


def test_lint_design_quality_includes_contrast():
    """lint_design_quality 应包含颜色对比度检查。"""
    import tempfile
    import os
    from driving.design_context import lint_design_quality

    bad_contrast_html = """<html lang="zh"><head>
<meta name="viewport" content="width=device-width">
<style>body { background: #AAAAAA; color: #999999; }</style>
</head><body><header>H</header><main><section>S</section></main><footer>F</footer>
</body></html>"""

    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(bad_contrast_html)
        violations = lint_design_quality(td)

    contrast_violations = [v for v in violations if v["rule"] == "color_contrast"]
    assert len(contrast_violations) >= 1


def test_design_score_includes_contrast():
    """design_score 应包含颜色对比度维度。"""
    import tempfile
    import os
    from driving.design_context import design_score

    bad_contrast_html = """<!DOCTYPE html>
<html lang="zh"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width">
<style>body { background: #AAAAAA; color: #999999; }</style>
</head><body><header><nav>N</nav></header><main><section><h1>T</h1></section></main><footer>F</footer>
</body></html>"""

    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(bad_contrast_html)
        score, notes = design_score(td)

    # 低对比度应影响分数（notes 应提及对比度问题）
    assert any("对比" in n or "contrast" in n.lower() for n in notes), f"应提及对比度问题: {notes}"


# ---------- M23: 间距网格 + 字体比例校验 ----------


def test_check_spacing_grid_good():
    """遵循 8px 网格的间距应无违规。"""
    import tempfile
    import os
    from driving.design_context import check_spacing_grid

    good_html = """<html lang="zh"><head>
<meta name="viewport" content="width=device-width">
<style>
body { padding: 16px; margin: 0; }
.card { padding: 24px; margin-bottom: 32px; gap: 8px; }
</style></head><body><p>OK</p></body></html>"""

    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(good_html)
        violations = check_spacing_grid(td)

    spacing_violations = [v for v in violations if v["rule"] == "spacing_grid"]
    assert spacing_violations == [], f"8px网格间距不应有违规: {spacing_violations}"


def test_check_spacing_grid_bad():
    """非 8px 网格的间距应报 warning。"""
    import tempfile
    import os
    from driving.design_context import check_spacing_grid

    bad_html = """<html lang="zh"><head>
<meta name="viewport" content="width=device-width">
<style>
body { padding: 13px; margin: 7px; }
.card { padding: 25px; gap: 10px; }
</style></head><body><p>Bad spacing</p></body></html>"""

    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(bad_html)
        violations = check_spacing_grid(td)

    spacing_violations = [v for v in violations if v["rule"] == "spacing_grid"]
    assert len(spacing_violations) >= 1
    assert spacing_violations[0]["severity"] == "warning"


def test_check_spacing_grid_allows_4px():
    """4px 是 8px 网格的半步，应允许。"""
    import tempfile
    import os
    from driving.design_context import check_spacing_grid

    html_4px = """<html lang="zh"><head>
<meta name="viewport" content="width=device-width">
<style>body { padding: 4px; margin: 12px; }</style>
</head><body><p>4px ok</p></body></html>"""

    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html_4px)
        violations = check_spacing_grid(td)

    spacing_violations = [v for v in violations if v["rule"] == "spacing_grid"]
    assert spacing_violations == [], f"4px应允许: {spacing_violations}"


def test_check_spacing_grid_empty_dir():
    """空目录应返回空列表。"""
    import tempfile
    from driving.design_context import check_spacing_grid

    with tempfile.TemporaryDirectory() as td:
        violations = check_spacing_grid(td)
    assert violations == []


def test_check_typography_scale_good():
    """遵循模块化字体比例的 HTML 应无违规。"""
    import tempfile
    import os
    from driving.design_context import check_typography_scale

    good_html = """<html lang="zh"><head>
<meta name="viewport" content="width=device-width">
<style>
body { font-size: 16px; }
h1 { font-size: 48px; }
h2 { font-size: 32px; }
h3 { font-size: 24px; }
small { font-size: 12px; }
</style></head><body><h1>T</h1><p>Body</p></body></html>"""

    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(good_html)
        violations = check_typography_scale(td)

    typo_violations = [v for v in violations if v["rule"] == "typography_scale"]
    assert typo_violations == [], f"良好字体比例不应有违规: {typo_violations}"


def test_check_typography_scale_bad():
    """随机字体大小应报 warning。"""
    import tempfile
    import os
    from driving.design_context import check_typography_scale

    bad_html = """<html lang="zh"><head>
<meta name="viewport" content="width=device-width">
<style>
body { font-size: 16px; }
h1 { font-size: 37px; }
h2 { font-size: 23px; }
p { font-size: 14px; }
</style></head><body><h1>T</h1></body></html>"""

    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(bad_html)
        violations = check_typography_scale(td)

    typo_violations = [v for v in violations if v["rule"] == "typography_scale"]
    assert len(typo_violations) >= 1
    assert typo_violations[0]["severity"] == "warning"


def test_check_typography_scale_empty_dir():
    """空目录应返回空列表。"""
    import tempfile
    from driving.design_context import check_typography_scale

    with tempfile.TemporaryDirectory() as td:
        violations = check_typography_scale(td)
    assert violations == []


def test_lint_design_quality_includes_spacing():
    """lint_design_quality 应包含间距网格检查。"""
    import tempfile
    import os
    from driving.design_context import lint_design_quality

    bad_spacing_html = """<html lang="zh"><head>
<meta name="viewport" content="width=device-width">
<style>body { padding: 13px; }</style>
</head><body><header>H</header><main><section>S</section></main><footer>F</footer>
</body></html>"""

    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(bad_spacing_html)
        violations = lint_design_quality(td)

    spacing_violations = [v for v in violations if v["rule"] == "spacing_grid"]
    assert len(spacing_violations) >= 1


def test_lint_design_quality_includes_typography():
    """lint_design_quality 应包含字体比例检查。"""
    import tempfile
    import os
    from driving.design_context import lint_design_quality

    bad_typo_html = """<html lang="zh"><head>
<meta name="viewport" content="width=device-width">
<style>h1 { font-size: 37px; }</style>
</head><body><header>H</header><main><section><h1>T</h1></section></main><footer>F</footer>
</body></html>"""

    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(bad_typo_html)
        violations = lint_design_quality(td)

    typo_violations = [v for v in violations if v["rule"] == "typography_scale"]
    assert len(typo_violations) >= 1


# ---------- M24: 间距/字体 auto-fix ----------


def test_auto_fix_spacing_grid():
    """非网格间距值应被自动修正为最近网格值。"""
    import tempfile
    import os
    from driving.design_context import auto_fix_spacing_grid

    html = """<html><head><style>
body { padding: 13px; margin: 7px; }
.card { padding: 25px; gap: 10px; }
</style></head><body><p>test</p></body></html>"""

    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        fixed = auto_fix_spacing_grid(td)
        with open(os.path.join(td, "index.html"), "r") as f:
            content = f.read()

    assert fixed is True
    # 13 → 12, 7 → 8, 25 → 24, 10 → 8
    assert "13px" not in content
    assert "12px" in content
    assert "24px" in content
    assert "8px" in content


def test_auto_fix_spacing_grid_no_change():
    """已合规的间距不应被修改。"""
    import tempfile
    import os
    from driving.design_context import auto_fix_spacing_grid

    html = """<html><head><style>
body { padding: 16px; margin: 32px; }
</style></head><body></body></html>"""

    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        fixed = auto_fix_spacing_grid(td)
        with open(os.path.join(td, "index.html"), "r") as f:
            content = f.read()

    assert fixed is False
    assert "16px" in content
    assert "32px" in content


def test_auto_fix_typography_scale():
    """非标准字号应被自动修正为最近标准字号。"""
    import tempfile
    import os
    from driving.design_context import auto_fix_typography_scale

    html = """<html><head><style>
body { font-size: 16px; }
h1 { font-size: 37px; }
h2 { font-size: 23px; }
p { font-size: 14px; }
</style></head><body><h1>T</h1></body></html>"""

    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        fixed = auto_fix_typography_scale(td)
        with open(os.path.join(td, "index.html"), "r") as f:
            content = f.read()

    assert fixed is True
    # 37 → 38, 23 → 24, 14 stays (already in scale)
    assert "37px" not in content
    assert "38px" in content
    assert "24px" in content


def test_auto_fix_typography_scale_no_change():
    """已合规的字号不应被修改。"""
    import tempfile
    import os
    from driving.design_context import auto_fix_typography_scale

    html = """<html><head><style>
body { font-size: 16px; }
h1 { font-size: 48px; }
</style></head><body></body></html>"""

    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        fixed = auto_fix_typography_scale(td)

    assert fixed is False


def test_auto_fix_design_issues_combined():
    """auto_fix_design_issues 应同时修复间距和字体。"""
    import tempfile
    import os
    from driving.design_context import auto_fix_design_issues

    html = """<html><head><style>
body { padding: 13px; font-size: 16px; }
h1 { font-size: 37px; margin-bottom: 25px; }
</style></head><body><h1>T</h1></body></html>"""

    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        fixed = auto_fix_design_issues(td)
        with open(os.path.join(td, "index.html"), "r") as f:
            content = f.read()

    assert fixed is True
    assert "13px" not in content  # spacing fixed
    assert "37px" not in content  # typography fixed


def test_auto_fix_empty_dir():
    """空目录不应报错。"""
    import tempfile
    from driving.design_context import auto_fix_design_issues

    with tempfile.TemporaryDirectory() as td:
        fixed = auto_fix_design_issues(td)
    assert fixed is False
