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

    assert score < 65, f"差HTML应得<65分，实际{score}: {notes}"


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


# ---------- M25: HTML 结构 auto-fix（meta viewport + lang + img alt） ----------


def test_auto_fix_meta_viewport_missing():
    """缺少 meta viewport 应自动注入。"""
    import tempfile
    import os
    from driving.design_context import auto_fix_html_structure

    html = """<html><head><title>Test</title></head>
<body><p>Hello</p></body></html>"""

    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        fixed = auto_fix_html_structure(td)
        with open(os.path.join(td, "index.html"), "r") as f:
            content = f.read()

    assert fixed is True
    assert "viewport" in content.lower()
    assert "width=device-width" in content


def test_auto_fix_meta_viewport_present():
    """已有 meta viewport（且 lang 和 img alt 也齐全）不应修改。"""
    import tempfile
    import os
    from driving.design_context import auto_fix_html_structure

    html = """<html lang="zh"><head>
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Test</title></head><body><p>Hello</p></body></html>"""

    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        fixed = auto_fix_html_structure(td)

    assert fixed is False


def test_auto_fix_html_lang_missing():
    """<html> 缺少 lang 属性应自动添加。"""
    import tempfile
    import os
    from driving.design_context import auto_fix_html_structure

    html = """<html><head>
<meta name="viewport" content="width=device-width">
</head><body><p>Hello</p></body></html>"""

    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        fixed = auto_fix_html_structure(td)
        with open(os.path.join(td, "index.html"), "r") as f:
            content = f.read()

    assert fixed is True
    assert 'lang=' in content


def test_auto_fix_html_lang_present():
    """已有 lang 属性（且 viewport 和 img alt 也齐全）不应修改。"""
    import tempfile
    import os
    from driving.design_context import auto_fix_html_structure

    html = """<html lang="en"><head>
<meta name="viewport" content="width=device-width">
</head><body><p>Hello</p></body></html>"""

    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        fixed = auto_fix_html_structure(td)

    assert fixed is False


def test_auto_fix_img_alt_missing():
    """<img> 缺少 alt 属性应自动添加空 alt。"""
    import tempfile
    import os
    from driving.design_context import auto_fix_html_structure

    html = """<html lang="zh"><head>
<meta name="viewport" content="width=device-width">
</head><body>
<img src="photo.jpg" width="100">
<img src="icon.png" height="20">
</body></html>"""

    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        fixed = auto_fix_html_structure(td)
        with open(os.path.join(td, "index.html"), "r") as f:
            content = f.read()

    assert fixed is True
    # 所有 img 都应有 alt
    import re
    img_tags = re.findall(r"<img\s+[^>]*>", content, re.IGNORECASE)
    for img in img_tags:
        assert "alt=" in img.lower(), f"img 仍缺少 alt: {img}"


def test_auto_fix_img_alt_present():
    """已有 alt 属性的 img 不应修改。"""
    import tempfile
    import os
    from driving.design_context import auto_fix_html_structure

    html = """<html lang="zh"><head>
<meta name="viewport" content="width=device-width">
</head><body>
<img src="photo.jpg" alt="A photo" width="100">
</body></html>"""

    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        fixed = auto_fix_html_structure(td)

    assert fixed is False


def test_auto_fix_html_structure_empty_dir():
    """空目录不应报错。"""
    import tempfile
    from driving.design_context import auto_fix_html_structure

    with tempfile.TemporaryDirectory() as td:
        fixed = auto_fix_html_structure(td)
    assert fixed is False


def test_auto_fix_design_issues_includes_html_structure():
    """auto_fix_design_issues 应同时修复间距+字体+HTML结构。"""
    import tempfile
    import os
    from driving.design_context import auto_fix_design_issues

    html = """<html><head><style>
body { padding: 13px; font-size: 16px; }
h1 { font-size: 37px; }
</style></head><body>
<img src="x.jpg">
</body></html>"""

    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        fixed = auto_fix_design_issues(td)
        with open(os.path.join(td, "index.html"), "r") as f:
            content = f.read()

    assert fixed is True
    assert "viewport" in content.lower()
    assert "lang=" in content
    assert "alt=" in content.lower()
    assert "13px" not in content
    assert "37px" not in content


# ---------- M26: 动画性能 auto-fix（transition 非 transform/opacity 属性移除） ----------


def test_auto_fix_transition_bad_props():
    """transition 中的 margin/padding/left 等属性应被移除，只保留 transform/opacity。"""
    import tempfile
    import os
    from driving.design_context import auto_fix_animation_performance

    html = """<html lang="zh"><head>
<meta name="viewport" content="width=device-width">
<style>
.card { transition: margin 0.3s ease, transform 0.2s, opacity 0.3s; }
.box { transition: padding 0.5s, left 0.3s ease-in; }
</style></head><body><div class="card">C</div></body></html>"""

    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        fixed = auto_fix_animation_performance(td)
        with open(os.path.join(td, "index.html"), "r") as f:
            content = f.read()

    assert fixed is True
    # .card 只保留 transform 和 opacity
    assert "transition: transform 0.2s, opacity 0.3s" in content or \
           "transition: transform 0.2s,opacity 0.3s" in content
    # .box 的 padding/left 都被移除 → 空 transition 应被移除整个属性
    assert "padding 0.5s" not in content
    assert "left 0.3s" not in content


def test_auto_fix_transition_good_no_change():
    """只用 transform/opacity 的 transition 不应修改。"""
    import tempfile
    import os
    from driving.design_context import auto_fix_animation_performance

    html = """<html lang="zh"><head>
<meta name="viewport" content="width=device-width">
<style>
.card { transition: transform 0.3s ease, opacity 0.2s; }
</style></head><body><div class="card">C</div></body></html>"""

    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        fixed = auto_fix_animation_performance(td)

    assert fixed is False


def test_auto_fix_transition_all_bad_removed():
    """全是非 transform/opacity 属性的 transition 应被整个移除。"""
    import tempfile
    import os
    from driving.design_context import auto_fix_animation_performance

    html = """<html lang="zh"><head>
<meta name="viewport" content="width=device-width">
<style>
.box { transition: width 0.3s, height 0.5s; color: red; }
</style></head><body><div class="box">B</div></body></html>"""

    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        fixed = auto_fix_animation_performance(td)
        with open(os.path.join(td, "index.html"), "r") as f:
            content = f.read()

    assert fixed is True
    assert "transition" not in content or "transition: ;" not in content


def test_auto_fix_transition_empty_dir():
    """空目录不应报错。"""
    import tempfile
    from driving.design_context import auto_fix_animation_performance

    with tempfile.TemporaryDirectory() as td:
        fixed = auto_fix_animation_performance(td)
    assert fixed is False


def test_auto_fix_design_issues_includes_animation():
    """auto_fix_design_issues 应同时包含动画性能修复。"""
    import tempfile
    import os
    from driving.design_context import auto_fix_design_issues

    html = """<html><head><style>
body { padding: 13px; }
.card { transition: margin 0.3s; }
</style></head><body><div class="card">C</div></body></html>"""

    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        fixed = auto_fix_design_issues(td)
        with open(os.path.join(td, "index.html"), "r") as f:
            content = f.read()

    assert fixed is True
    assert "margin 0.3s" not in content
    assert "13px" not in content


# ---------- M27: CSS 变量注入 auto-fix ----------


def test_auto_fix_css_variables_missing():
    """有 :root 但缺少 --color-* 变量时应注入默认变量系统。"""
    import tempfile
    import os
    from driving.design_context import auto_fix_css_variables

    html = """<html lang="zh"><head>
<meta name="viewport" content="width=device-width">
<style>
:root { --gap: 16px; }
body { background: #0D0D12; color: #F5F5F5; }
</style></head><body><p>test</p></body></html>"""

    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        fixed = auto_fix_css_variables(td)
        with open(os.path.join(td, "index.html"), "r") as f:
            content = f.read()

    assert fixed is True
    assert "--color-bg" in content
    assert "--color-text" in content
    assert "--color-accent" in content


def test_auto_fix_css_variables_present():
    """已有 --color-* 变量不应修改。"""
    import tempfile
    import os
    from driving.design_context import auto_fix_css_variables

    html = """<html lang="zh"><head>
<meta name="viewport" content="width=device-width">
<style>
:root { --color-bg: #0D0D12; --color-text: #F5F5F5; --color-accent: #0A84FF; }
body { background: var(--color-bg); }
</style></head><body><p>test</p></body></html>"""

    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        fixed = auto_fix_css_variables(td)

    assert fixed is False


def test_auto_fix_css_variables_no_root():
    """没有 :root 时应注入完整的 :root 变量块。"""
    import tempfile
    import os
    from driving.design_context import auto_fix_css_variables

    html = """<html lang="zh"><head>
<meta name="viewport" content="width=device-width">
<style>
body { background: #0D0D12; color: #F5F5F5; }
</style></head><body><p>test</p></body></html>"""

    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        fixed = auto_fix_css_variables(td)
        with open(os.path.join(td, "index.html"), "r") as f:
            content = f.read()

    assert fixed is True
    assert ":root" in content
    assert "--color-bg" in content
    assert "--color-text" in content


def test_auto_fix_css_variables_empty_dir():
    """空目录不应报错。"""
    import tempfile
    from driving.design_context import auto_fix_css_variables

    with tempfile.TemporaryDirectory() as td:
        fixed = auto_fix_css_variables(td)
    assert fixed is False


def test_auto_fix_design_issues_includes_css_variables():
    """auto_fix_design_issues 应同时包含 CSS 变量注入。"""
    import tempfile
    import os
    from driving.design_context import auto_fix_design_issues

    html = """<html><head><style>
:root { --gap: 16px; }
body { padding: 13px; }
</style></head><body><p>test</p></body></html>"""

    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        fixed = auto_fix_design_issues(td)
        with open(os.path.join(td, "index.html"), "r") as f:
            content = f.read()

    assert fixed is True
    assert "--color-bg" in content
    assert "13px" not in content


# ---------- M28: auto-fix 有效性验证（auto-fix 前后 design_score 对比） ----------


def test_auto_fix_improves_design_score():
    """auto_fix_design_issues 应显著提升 design_score。"""
    import tempfile
    import os
    from driving.design_context import design_score, auto_fix_design_issues

    # 极差 HTML：缺 viewport/lang/CSS变量/img alt/动画性能差/间距差
    bad_html = """<html><head><style>
body { padding: 13px; margin: 7px; font-size: 16px; }
h1 { font-size: 37px; }
.card { transition: margin 0.3s, width 0.5s; }
:root { --gap: 16px; }
</style></head><body>
<img src="photo.jpg" width="100">
<div class="card">Card</div>
</body></html>"""

    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(bad_html)
        score_before, notes_before = design_score(td)

        auto_fix_design_issues(td)

        score_after, notes_after = design_score(td)

    # auto-fix 后分数应显著提升
    assert score_after > score_before, (
        f"auto-fix 后分数应提升：before={score_before}, after={score_after}"
    )
    # auto-fix 后应至少达到 60 分
    assert score_after >= 60, f"auto-fix 后应≥60分：{score_after}, notes={notes_after}"


def test_auto_fix_idempotent():
    """对已修复的 HTML 再次 auto-fix 不应改变（幂等性）。"""
    import tempfile
    import os
    from driving.design_context import auto_fix_design_issues

    good_html = """<!DOCTYPE html>
<html lang="zh"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<style>
:root { --color-bg: #0D0D12; --color-text: #F5F5F5; --color-accent: #0A84FF; }
body { padding: 16px; margin: 0; font-size: 16px; transition: opacity 0.3s ease; }
h1 { font-size: 48px; }
:focus-visible { outline: 2px solid var(--color-accent); outline-offset: 2px; }
@media (max-width: 768px) { body { font-size: 14px; } }
@keyframes fadeInUp{from{opacity:0;transform:translateY(20px)}to{opacity:1;transform:translateY(0)}}
section{animation:fadeInUp 0.8s ease-out both}
</style></head><body>
<header><nav>Logo</nav></header>
<main><section><h1>Title</h1></section></main>
<footer>Copyright</footer>
<img src="logo.png" alt="Logo">
</body></html>"""

    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(good_html)
        fixed1 = auto_fix_design_issues(td)
        with open(os.path.join(td, "index.html"), "r") as f:
            content_after_first = f.read()
        fixed2 = auto_fix_design_issues(td)
        with open(os.path.join(td, "index.html"), "r") as f:
            content_after_second = f.read()

    # 第一次不应改变（已合规）
    assert fixed1 is False
    # 第二次也不应改变
    assert fixed2 is False
    # 内容应完全一致
    assert content_after_first == content_after_second


def test_auto_fix_eliminates_all_error_violations():
    """auto-fix 后 lint_design_quality 不应有 error 级违规。"""
    import tempfile
    import os
    from driving.design_context import lint_design_quality, auto_fix_design_issues

    bad_html = """<html><head><style>
body { padding: 16px; font-size: 16px; }
</style></head><body>
<img src="x.jpg">
</body></html>"""

    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(bad_html)

        violations_before = lint_design_quality(td)
        errors_before = [v for v in violations_before if v["severity"] == "error"]

        auto_fix_design_issues(td)

        violations_after = lint_design_quality(td)
        errors_after = [v for v in violations_after if v["severity"] == "error"]

    # auto-fix 前应有 error 违规
    assert len(errors_before) > 0
    # auto-fix 后不应有 error 级违规（viewport + img alt 都被修复）
    assert errors_after == [], f"auto-fix 后不应有 error 违规: {errors_after}"


# ---------- M29: 语义化 HTML auto-fix（缺少 header/main/footer 时自动注入） ----------


def test_auto_fix_semantic_missing_main():
    """缺少 <main> 时应把 body 内容包裹在 <main> 中。"""
    import tempfile
    import os
    from driving.design_context import auto_fix_semantic_html

    html = """<html lang="zh"><head>
<meta name="viewport" content="width=device-width">
</head><body>
<h1>Title</h1>
<p>Content</p>
</body></html>"""

    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        fixed = auto_fix_semantic_html(td)
        with open(os.path.join(td, "index.html"), "r") as f:
            content = f.read()

    assert fixed is True
    assert "<main" in content
    assert "</main>" in content


def test_auto_fix_semantic_missing_header():
    """缺少 <header> 时应在 body 开头注入。"""
    import tempfile
    import os
    from driving.design_context import auto_fix_semantic_html

    html = """<html lang="zh"><head>
<meta name="viewport" content="width=device-width">
</head><body>
<main><p>Content</p></main>
</body></html>"""

    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        fixed = auto_fix_semantic_html(td)
        with open(os.path.join(td, "index.html"), "r") as f:
            content = f.read()

    assert fixed is True
    assert "<header" in content


def test_auto_fix_semantic_missing_footer():
    """缺少 <footer> 时应在 body 末尾注入。"""
    import tempfile
    import os
    from driving.design_context import auto_fix_semantic_html

    html = """<html lang="zh"><head>
<meta name="viewport" content="width=device-width">
</head><body>
<header>Logo</header>
<main><p>Content</p></main>
</body></html>"""

    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        fixed = auto_fix_semantic_html(td)
        with open(os.path.join(td, "index.html"), "r") as f:
            content = f.read()

    assert fixed is True
    assert "<footer" in content


def test_auto_fix_semantic_all_present():
    """已有 header/main/footer 不应修改。"""
    import tempfile
    import os
    from driving.design_context import auto_fix_semantic_html

    html = """<html lang="zh"><head>
<meta name="viewport" content="width=device-width">
</head><body>
<header>Logo</header>
<main><p>Content</p></main>
<footer>Copyright</footer>
</body></html>"""

    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        fixed = auto_fix_semantic_html(td)

    assert fixed is False


def test_auto_fix_semantic_empty_dir():
    """空目录不应报错。"""
    import tempfile
    from driving.design_context import auto_fix_semantic_html

    with tempfile.TemporaryDirectory() as td:
        fixed = auto_fix_semantic_html(td)
    assert fixed is False


# ---------- M34: heading_hierarchy + focus_visible ----------


def test_lint_heading_hierarchy_skip():
    """标题跳级（h1 → h3）应报 warning。"""
    import tempfile
    import os
    from driving.design_context import lint_design_quality

    html = """<html lang="zh"><head><meta name="viewport" content="width=device-width">
<style>:root{--color-bg:#0D0D12;--color-text:#F5F5F5}body{transition:opacity 0.3s}</style>
</head><body><header>H</header><main><section>
<h1>Title</h1><h3>Skip</h3>
</section></main><footer>F</footer></body></html>"""

    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        violations = lint_design_quality(td)

    h_violations = [v for v in violations if v["rule"] == "heading_hierarchy"]
    assert len(h_violations) >= 1
    assert "跳级" in h_violations[0]["message"] or "h1" in h_violations[0]["message"]


def test_lint_heading_hierarchy_multiple_h1():
    """多个 h1 应报 warning。"""
    import tempfile
    import os
    from driving.design_context import lint_design_quality

    html = """<html lang="zh"><head><meta name="viewport" content="width=device-width">
<style>:root{--color-bg:#0D0D12}</style>
</head><body><header>H</header><main><section>
<h1>First</h1><h2>Sub</h2><h1>Second</h1>
</section></main><footer>F</footer></body></html>"""

    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        violations = lint_design_quality(td)

    h_violations = [v for v in violations if v["rule"] == "heading_hierarchy"]
    assert len(h_violations) >= 1
    assert "h1" in h_violations[0]["message"]


def test_lint_heading_hierarchy_correct_no_violation():
    """正确层级（h1 → h2 → h3）不应报违规。"""
    import tempfile
    import os
    from driving.design_context import lint_design_quality

    html = """<html lang="zh"><head><meta name="viewport" content="width=device-width">
<style>:root{--color-bg:#0D0D12}</style>
</head><body><header>H</header><main><section>
<h1>Title</h1><h2>Section</h2><h3>Subsection</h3>
</section></main><footer>F</footer></body></html>"""

    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        violations = lint_design_quality(td)

    h_violations = [v for v in violations if v["rule"] == "heading_hierarchy"]
    assert h_violations == [], f"正确层级不应有违规: {h_violations}"


def test_lint_focus_visible_missing():
    """缺少 :focus 样式应报 warning。"""
    import tempfile
    import os
    from driving.design_context import lint_design_quality

    html = """<html lang="zh"><head><meta name="viewport" content="width=device-width">
<style>:root{--color-bg:#0D0D12}body{transition:opacity 0.3s}</style>
</head><body><header>H</header><main><section><h1>T</h1></section></main>
<footer>F</footer></body></html>"""

    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        violations = lint_design_quality(td)

    focus_violations = [v for v in violations if v["rule"] == "focus_visible"]
    assert len(focus_violations) == 1
    assert focus_violations[0]["severity"] == "warning"


def test_lint_focus_visible_present():
    """有 :focus 样式不应报违规。"""
    import tempfile
    import os
    from driving.design_context import lint_design_quality

    html = """<html lang="zh"><head><meta name="viewport" content="width=device-width">
<style>:root{--color-bg:#0D0D12}
button:focus { outline: 2px solid #0A84FF; }
body{transition:opacity 0.3s}</style>
</head><body><header>H</header><main><section><h1>T</h1></section></main>
<footer>F</footer></body></html>"""

    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        violations = lint_design_quality(td)

    focus_violations = [v for v in violations if v["rule"] == "focus_visible"]
    assert focus_violations == [], f"有 :focus 不应报违规: {focus_violations}"


def test_auto_fix_focus_visible_injects():
    """缺少 :focus 时自动注入 :focus-visible 样式。"""
    import tempfile
    import os
    from driving.design_context import auto_fix_focus_visible

    html = """<html><head><style>body { color: red; }</style></head>
<body><button>Click</button></body></html>"""

    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        changed = auto_fix_focus_visible(td)
        with open(os.path.join(td, "index.html")) as f:
            content = f.read()

    assert changed is True
    assert ":focus-visible" in content or ":focus" in content
    assert "outline" in content


def test_auto_fix_focus_visible_present_no_change():
    """已有 :focus 样式时不修改。"""
    import tempfile
    import os
    from driving.design_context import auto_fix_focus_visible

    html = """<html><head><style>
button:focus { outline: 2px solid blue; }
</style></head><body><button>Click</button></body></html>"""

    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        changed = auto_fix_focus_visible(td)
        with open(os.path.join(td, "index.html")) as f:
            content = f.read()

    assert changed is False
    # 内容不变
    assert "button:focus" in content


def test_auto_fix_focus_visible_empty_dir():
    """空目录不应报错。"""
    import tempfile
    from driving.design_context import auto_fix_focus_visible

    with tempfile.TemporaryDirectory() as td:
        changed = auto_fix_focus_visible(td)
    assert changed is False


def test_auto_fix_design_issues_includes_focus_visible():
    """auto_fix_design_issues 组合函数应包含 focus_visible 修复。"""
    import tempfile
    import os
    from driving.design_context import auto_fix_design_issues

    # HTML 缺 :focus 样式
    html = """<html><head><style>body { color: red; }</style></head>
<body><button>Click</button></body></html>"""

    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        auto_fix_design_issues(td)
        with open(os.path.join(td, "index.html")) as f:
            content = f.read()

    assert ":focus-visible" in content or ":focus" in content


# ---------- M35: responsive_breakpoints + component_states lint ----------


def test_lint_responsive_breakpoints_missing():
    """缺少 @media 查询应报 warning（原则 7：响应式必须写断点）。"""
    import tempfile
    import os
    from driving.design_context import lint_design_quality

    html = """<html lang="en"><head>
<meta name="viewport" content="width=device-width">
<style>body { font-size: 16px; }</style>
</head><body><header>H</header><main><section>S</section></main><footer>F</footer>
</body></html>"""

    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        violations = lint_design_quality(td)

    bp_violations = [v for v in violations if v["rule"] == "responsive_breakpoints"]
    assert len(bp_violations) == 1
    assert bp_violations[0]["severity"] == "warning"


def test_lint_responsive_breakpoints_present():
    """有 @media 查询不应报违规。"""
    import tempfile
    import os
    from driving.design_context import lint_design_quality

    html = """<html lang="en"><head>
<meta name="viewport" content="width=device-width">
<style>
body { font-size: 16px; }
@media (max-width: 768px) { body { font-size: 14px; } }
</style>
</head><body><header>H</header><main><section>S</section></main><footer>F</footer>
</body></html>"""

    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        violations = lint_design_quality(td)

    bp_violations = [v for v in violations if v["rule"] == "responsive_breakpoints"]
    assert bp_violations == []


def test_lint_component_states_missing():
    """有交互元素但缺少 hover/active/focus/disabled 状态应报 warning（原则 6）。"""
    import tempfile
    import os
    from driving.design_context import lint_design_quality

    html = """<html lang="en"><head>
<meta name="viewport" content="width=device-width">
<style>button { background: blue; }</style>
</head><body><header>H</header><main><section>
<button>Click</button>
</section></main><footer>F</footer>
</body></html>"""

    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        violations = lint_design_quality(td)

    cs_violations = [v for v in violations if v["rule"] == "component_states"]
    assert len(cs_violations) >= 1
    assert cs_violations[0]["severity"] == "warning"


def test_lint_component_states_present():
    """有完整 hover/active/focus/disabled 状态不应报违规。"""
    import tempfile
    import os
    from driving.design_context import lint_design_quality

    html = """<html lang="en"><head>
<meta name="viewport" content="width=device-width">
<style>
button { background: blue; }
button:hover { background: darkblue; }
button:active { background: navy; }
button:focus { outline: 2px solid blue; }
button:disabled { opacity: 0.5; }
@media (max-width: 768px) { button { width: 100%; } }
</style>
</head><body><header>H</header><main><section>
<button>Click</button>
</section></main><footer>F</footer>
</body></html>"""

    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        violations = lint_design_quality(td)

    cs_violations = [v for v in violations if v["rule"] == "component_states"]
    assert cs_violations == []


def test_lint_component_states_no_interactive_elements():
    """无交互元素时不应报 component_states 违规。"""
    import tempfile
    import os
    from driving.design_context import lint_design_quality

    html = """<html lang="en"><head>
<meta name="viewport" content="width=device-width">
<style>body { font-size: 16px; }</style>
</head><body><header>H</header><main><section><p>Text only</p></section></main><footer>F</footer>
</body></html>"""

    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        violations = lint_design_quality(td)

    cs_violations = [v for v in violations if v["rule"] == "component_states"]
    assert cs_violations == []


def test_auto_fix_responsive_injects_media_query():
    """缺少 @media 时应自动注入响应式断点。"""
    import tempfile
    import os
    from driving.design_context import auto_fix_responsive

    html = """<html><head><style>body { font-size: 16px; }</style></head>
<body><p>Hello</p></body></html>"""

    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        changed = auto_fix_responsive(td)
        with open(os.path.join(td, "index.html")) as f:
            content = f.read()

    assert changed is True
    assert "@media" in content
    assert "768px" in content


def test_auto_fix_responsive_present_no_change():
    """已有 @media 时不修改。"""
    import tempfile
    import os
    from driving.design_context import auto_fix_responsive

    html = """<html><head><style>
body { font-size: 16px; }
@media (max-width: 768px) { body { font-size: 14px; } }
</style></head><body><p>Hello</p></body></html>"""

    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        changed = auto_fix_responsive(td)

    assert changed is False


def test_auto_fix_responsive_empty_dir():
    """空目录应返回 False。"""
    import tempfile
    from driving.design_context import auto_fix_responsive

    with tempfile.TemporaryDirectory() as td:
        changed = auto_fix_responsive(td)

    assert changed is False


def test_auto_fix_component_states_injects_states():
    """缺少状态样式时应自动注入 hover/active/focus/disabled。"""
    import tempfile
    import os
    from driving.design_context import auto_fix_component_states

    html = """<html><head><style>button { background: blue; }</style></head>
<body><button>Click</button></body></html>"""

    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        changed = auto_fix_component_states(td)
        with open(os.path.join(td, "index.html")) as f:
            content = f.read()

    assert changed is True
    assert ":hover" in content
    assert ":active" in content
    assert ":disabled" in content


def test_auto_fix_component_states_present_no_change():
    """已有完整状态样式时不修改。"""
    import tempfile
    import os
    from driving.design_context import auto_fix_component_states

    html = """<html><head><style>
button { background: blue; }
button:hover { background: darkblue; }
button:active { background: navy; }
button:focus { outline: 2px solid blue; }
button:disabled { opacity: 0.5; }
</style></head><body><button>Click</button></body></html>"""

    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        changed = auto_fix_component_states(td)

    assert changed is False


def test_auto_fix_component_states_no_button():
    """无交互元素时不修改。"""
    import tempfile
    import os
    from driving.design_context import auto_fix_component_states

    html = """<html><head><style>body { color: red; }</style></head>
<body><p>Hello</p></body></html>"""

    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        changed = auto_fix_component_states(td)

    assert changed is False


def test_auto_fix_component_states_empty_dir():
    """空目录应返回 False。"""
    import tempfile
    from driving.design_context import auto_fix_component_states

    with tempfile.TemporaryDirectory() as td:
        changed = auto_fix_component_states(td)

    assert changed is False


def test_auto_fix_design_issues_includes_responsive_and_component_states():
    """auto_fix_design_issues 组合函数应包含 responsive 和 component_states 修复。"""
    import tempfile
    import os
    from driving.design_context import auto_fix_design_issues

    html = """<html><head><style>button { background: blue; }</style></head>
<body><button>Click</button></body></html>"""

    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        auto_fix_design_issues(td)
        with open(os.path.join(td, "index.html")) as f:
            content = f.read()

    assert "@media" in content
    assert ":hover" in content
    assert ":disabled" in content


# ---------- M36: design_score 评分系统升级（含 M34/M35 新维度） ----------


def test_design_score_rewards_media_queries():
    """有 @media 查询的 HTML 应比没有的分数高。"""
    import tempfile
    import os
    from driving.design_context import design_score

    base_html = """<!DOCTYPE html>
<html lang="zh"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<style>
:root { --color-bg: #0D0D12; --color-text: #F5F5F5; --color-accent: #0A84FF; }
body { transition: opacity 0.3s ease; }
:focus-visible { outline: 2px solid var(--color-accent); }
</style></head><body>
<header><nav>Logo</nav></header>
<main><section><h1>Title</h1></section></main>
<footer>Copyright</footer>
</body></html>"""

    html_with_media = base_html.replace(
        "</style>",
        "@media (max-width: 768px) { body { font-size: 14px; } }</style>",
    )

    with tempfile.TemporaryDirectory() as td1:
        with open(os.path.join(td1, "index.html"), "w") as f:
            f.write(base_html)
        score_no_media, _ = design_score(td1)

    with tempfile.TemporaryDirectory() as td2:
        with open(os.path.join(td2, "index.html"), "w") as f:
            f.write(html_with_media)
        score_with_media, _ = design_score(td2)

    assert score_with_media > score_no_media, (
        f"有@media应比无@media分数高: {score_with_media} vs {score_no_media}"
    )


def test_design_score_rewards_focus_visible():
    """有 :focus-visible 样式的 HTML 应比没有的分数高。"""
    import tempfile
    import os
    from driving.design_context import design_score

    base_html = """<!DOCTYPE html>
<html lang="zh"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<style>
:root { --color-bg: #0D0D12; --color-text: #F5F5F5; --color-accent: #0A84FF; }
body { transition: opacity 0.3s ease; }
@media (max-width: 768px) { body { font-size: 14px; } }
</style></head><body>
<header><nav>Logo</nav></header>
<main><section><h1>Title</h1></section></main>
<footer>Copyright</footer>
</body></html>"""

    html_with_focus = base_html.replace(
        "</style>",
        ":focus-visible { outline: 2px solid var(--color-accent); }</style>",
    )

    with tempfile.TemporaryDirectory() as td1:
        with open(os.path.join(td1, "index.html"), "w") as f:
            f.write(base_html)
        score_no_focus, _ = design_score(td1)

    with tempfile.TemporaryDirectory() as td2:
        with open(os.path.join(td2, "index.html"), "w") as f:
            f.write(html_with_focus)
        score_with_focus, _ = design_score(td2)

    assert score_with_focus > score_no_focus, (
        f"有:focus应比无:focus分数高: {score_with_focus} vs {score_no_focus}"
    )


def test_design_score_rewards_component_states():
    """有完整组件状态样式的 HTML 应比缺少的分数高。"""
    import tempfile
    import os
    from driving.design_context import design_score

    base_html = """<!DOCTYPE html>
<html lang="zh"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<style>
:root { --color-bg: #0D0D12; --color-text: #F5F5F5; --color-accent: #0A84FF; }
body { transition: opacity 0.3s ease; }
:focus-visible { outline: 2px solid var(--color-accent); }
@media (max-width: 768px) { body { font-size: 14px; } }
</style></head><body>
<header><nav>Logo</nav></header>
<main><section><h1>Title</h1><button>Click</button></section></main>
<footer>Copyright</footer>
</body></html>"""

    html_with_states = base_html.replace(
        "</style>",
        "button:hover{opacity:0.85}button:active{transform:scale(0.98)}button:disabled{opacity:0.5}</style>",
    )

    with tempfile.TemporaryDirectory() as td1:
        with open(os.path.join(td1, "index.html"), "w") as f:
            f.write(base_html)
        score_no_states, _ = design_score(td1)

    with tempfile.TemporaryDirectory() as td2:
        with open(os.path.join(td2, "index.html"), "w") as f:
            f.write(html_with_states)
        score_with_states, _ = design_score(td2)

    assert score_with_states > score_no_states, (
        f"有组件状态应比缺少分数高: {score_with_states} vs {score_no_states}"
    )


def test_design_score_penalizes_heading_skip():
    """标题层级跳级应扣分。"""
    import tempfile
    import os
    from driving.design_context import design_score

    good_headings_html = """<!DOCTYPE html>
<html lang="zh"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<style>
:root { --color-bg: #0D0D12; --color-text: #F5F5F5; --color-accent: #0A84FF; }
body { transition: opacity 0.3s ease; }
:focus-visible { outline: 2px solid var(--color-accent); }
@media (max-width: 768px) { body { font-size: 14px; } }
</style></head><body>
<header><nav>Logo</nav></header>
<main><section><h1>Title</h1><h2>Sub</h2></section></main>
<footer>Copyright</footer>
</body></html>"""

    skip_headings_html = """<!DOCTYPE html>
<html lang="zh"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<style>
:root { --color-bg: #0D0D12; --color-text: #F5F5F5; --color-accent: #0A84FF; }
body { transition: opacity 0.3s ease; }
:focus-visible { outline: 2px solid var(--color-accent); }
@media (max-width: 768px) { body { font-size: 14px; } }
</style></head><body>
<header><nav>Logo</nav></header>
<main><section><h1>Title</h1><h4>Skip</h4></section></main>
<footer>Copyright</footer>
</body></html>"""

    with tempfile.TemporaryDirectory() as td1:
        with open(os.path.join(td1, "index.html"), "w") as f:
            f.write(good_headings_html)
        score_good, _ = design_score(td1)

    with tempfile.TemporaryDirectory() as td2:
        with open(os.path.join(td2, "index.html"), "w") as f:
            f.write(skip_headings_html)
        score_skip, _ = design_score(td2)

    assert score_good > score_skip, (
        f"良好标题层级应比跳级分数高: {score_good} vs {score_skip}"
    )


def test_design_score_perfect_with_all_dimensions():
    """包含所有 M34/M35 维度的完美 HTML 应得接近 100 分。"""
    import tempfile
    import os
    from driving.design_context import design_score

    perfect_html = """<!DOCTYPE html>
<html lang="zh"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<style>
:root { --color-bg: #0D0D12; --color-text: #F5F5F5; --color-accent: #0A84FF; }
body { transition: opacity 0.3s ease; transform: translateY(0); }
:focus-visible { outline: 2px solid var(--color-accent); outline-offset: 2px; }
button:hover { opacity: 0.85; }
button:active { transform: scale(0.98); }
button:focus { outline: 2px solid var(--color-accent); }
button:disabled { opacity: 0.5; cursor: not-allowed; }
@media (max-width: 768px) { body { font-size: 14px; } }
</style></head><body>
<header><nav>Logo</nav></header>
<main><section><h1>Title</h1><h2>Sub</h2><button>Click</button></section></main>
<footer>Copyright</footer>
</body></html>"""

    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(perfect_html)
        score, notes = design_score(td)

    assert score >= 90, f"完美HTML应得≥90分，实际{score}: {notes}"


# ---------- M37: aria_label + form_label lint（axe-core 启发） ----------


def test_lint_aria_label_button_missing_text():
    """button 无文本内容且无 aria-label 应报 warning。"""
    import tempfile
    import os
    from driving.design_context import lint_design_quality

    html = """<html lang="en"><head>
<meta name="viewport" content="width=device-width">
<style>button:hover{}button:active{}button:focus{}button:disabled{}
@media(max-width:768px){}</style>
</head><body><header>H</header><main><section>
<button></button>
</section></main><footer>F</footer></body></html>"""

    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        violations = lint_design_quality(td)

    aria_violations = [v for v in violations if v["rule"] == "aria_label"]
    assert len(aria_violations) >= 1
    assert aria_violations[0]["severity"] == "warning"


def test_lint_aria_label_button_with_text():
    """button 有文本内容不应报违规。"""
    import tempfile
    import os
    from driving.design_context import lint_design_quality

    html = """<html lang="en"><head>
<meta name="viewport" content="width=device-width">
<style>button:hover{}button:active{}button:focus{}button:disabled{}
@media(max-width:768px){}</style>
</head><body><header>H</header><main><section>
<button>Submit</button>
</section></main><footer>F</footer></body></html>"""

    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        violations = lint_design_quality(td)

    aria_violations = [v for v in violations if v["rule"] == "aria_label"]
    assert aria_violations == []


def test_lint_aria_label_button_with_aria_label():
    """button 有 aria-label 不应报违规。"""
    import tempfile
    import os
    from driving.design_context import lint_design_quality

    html = """<html lang="en"><head>
<meta name="viewport" content="width=device-width">
<style>button:hover{}button:active{}button:focus{}button:disabled{}
@media(max-width:768px){}</style>
</head><body><header>H</header><main><section>
<button aria-label="Close"><svg></svg></button>
</section></main><footer>F</footer></body></html>"""

    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        violations = lint_design_quality(td)

    aria_violations = [v for v in violations if v["rule"] == "aria_label"]
    assert aria_violations == []


def test_lint_aria_label_link_missing_text():
    """a 标签无文本且无 aria-label 应报 warning。"""
    import tempfile
    import os
    from driving.design_context import lint_design_quality

    html = """<html lang="en"><head>
<meta name="viewport" content="width=device-width">
<style>a:hover{}a:active{}a:focus{}a:disabled{}
@media(max-width:768px){}</style>
</head><body><header>H</header><main><section>
<a href="#"></a>
</section></main><footer>F</footer></body></html>"""

    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        violations = lint_design_quality(td)

    aria_violations = [v for v in violations if v["rule"] == "aria_label"]
    assert len(aria_violations) >= 1


def test_lint_form_label_missing():
    """input 无关联 label 应报 warning。"""
    import tempfile
    import os
    from driving.design_context import lint_design_quality

    html = """<html lang="en"><head>
<meta name="viewport" content="width=device-width">
<style>input:hover{}input:active{}input:focus{}input:disabled{}
@media(max-width:768px){}</style>
</head><body><header>H</header><main><section>
<input type="text" name="email">
</section></main><footer>F</footer></body></html>"""

    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        violations = lint_design_quality(td)

    label_violations = [v for v in violations if v["rule"] == "form_label"]
    assert len(label_violations) >= 1
    assert label_violations[0]["severity"] == "warning"


def test_lint_form_label_with_label_tag():
    """input 有关联 label 不应报违规。"""
    import tempfile
    import os
    from driving.design_context import lint_design_quality

    html = """<html lang="en"><head>
<meta name="viewport" content="width=device-width">
<style>input:hover{}input:active{}input:focus{}input:disabled{}
@media(max-width:768px){}</style>
</head><body><header>H</header><main><section>
<label for="email">Email</label>
<input type="text" id="email" name="email">
</section></main><footer>F</footer></body></html>"""

    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        violations = lint_design_quality(td)

    label_violations = [v for v in violations if v["rule"] == "form_label"]
    assert label_violations == []


def test_lint_form_label_with_aria_label():
    """input 有 aria-label 不应报违规。"""
    import tempfile
    import os
    from driving.design_context import lint_design_quality

    html = """<html lang="en"><head>
<meta name="viewport" content="width=device-width">
<style>input:hover{}input:active{}input:focus{}input:disabled{}
@media(max-width:768px){}</style>
</head><body><header>H</header><main><section>
<input type="text" aria-label="Search" name="q">
</section></main><footer>F</footer></body></html>"""

    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        violations = lint_design_quality(td)

    label_violations = [v for v in violations if v["rule"] == "form_label"]
    assert label_violations == []


# ---------- M38: aria_label + form_label auto_fix + score 集成 ----------


def test_auto_fix_aria_label_injects_for_button():
    """button 无文本无 aria-label 时应自动注入 aria-label。"""
    import tempfile
    import os
    from driving.design_context import auto_fix_aria_label

    html = """<html><head><style>button:hover{}button:active{}button:focus{}button:disabled{}
@media(max-width:768px){}</style></head>
<body><button></button></body></html>"""

    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        changed = auto_fix_aria_label(td)
        with open(os.path.join(td, "index.html")) as f:
            content = f.read()

    assert changed is True
    assert "aria-label" in content


def test_auto_fix_aria_label_present_no_change():
    """button 已有 aria-label 或文本时不修改。"""
    import tempfile
    import os
    from driving.design_context import auto_fix_aria_label

    html = """<html><head><style>button:hover{}button:active{}button:focus{}button:disabled{}
@media(max-width:768px){}</style></head>
<body><button>Click</button></body></html>"""

    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        changed = auto_fix_aria_label(td)

    assert changed is False


def test_auto_fix_aria_label_empty_dir():
    """空目录应返回 False。"""
    import tempfile
    from driving.design_context import auto_fix_aria_label

    with tempfile.TemporaryDirectory() as td:
        changed = auto_fix_aria_label(td)

    assert changed is False


def test_auto_fix_form_label_injects_aria_label():
    """input 无 label 时应自动注入 aria-label。"""
    import tempfile
    import os
    from driving.design_context import auto_fix_form_label

    html = """<html><head><style>input:hover{}input:active{}input:focus{}input:disabled{}
@media(max-width:768px){}</style></head>
<body><input type="text" name="email"></body></html>"""

    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        changed = auto_fix_form_label(td)
        with open(os.path.join(td, "index.html")) as f:
            content = f.read()

    assert changed is True
    assert "aria-label" in content


def test_auto_fix_form_label_present_no_change():
    """input 已有 label 时不修改。"""
    import tempfile
    import os
    from driving.design_context import auto_fix_form_label

    html = """<html><head><style>input:hover{}input:active{}input:focus{}input:disabled{}
@media(max-width:768px){}</style></head>
<body><label for="email">Email</label><input type="text" id="email" name="email"></body></html>"""

    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        changed = auto_fix_form_label(td)

    assert changed is False


def test_auto_fix_form_label_empty_dir():
    """空目录应返回 False。"""
    import tempfile
    from driving.design_context import auto_fix_form_label

    with tempfile.TemporaryDirectory() as td:
        changed = auto_fix_form_label(td)

    assert changed is False


def test_auto_fix_design_issues_includes_aria_and_form_label():
    """auto_fix_design_issues 组合函数应包含 aria_label 和 form_label 修复。"""
    import tempfile
    import os
    from driving.design_context import auto_fix_design_issues

    html = """<html><head><style>button:hover{}button:active{}button:focus{}button:disabled{}
input:hover{}input:active{}input:focus{}input:disabled{}
@media(max-width:768px){}</style></head>
<body><button></button><input type="text" name="q"></body></html>"""

    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        auto_fix_design_issues(td)
        with open(os.path.join(td, "index.html")) as f:
            content = f.read()

    # button 应得到 aria-label
    assert "aria-label" in content


def test_design_score_penalizes_aria_label_missing():
    """缺少 aria-label 的 HTML 应比有的分数低。"""
    import tempfile
    import os
    from driving.design_context import design_score

    base_html = """<!DOCTYPE html>
<html lang="zh"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<style>
:root { --color-bg: #0D0D12; --color-text: #F5F5F5; --color-accent: #0A84FF; }
body { transition: opacity 0.3s ease; }
:focus-visible { outline: 2px solid var(--color-accent); }
button:hover{opacity:0.85}button:active{transform:scale(0.98)}button:focus{outline:2px solid blue}button:disabled{opacity:0.5}
@media (max-width: 768px) { body { font-size: 14px; } }
</style></head><body>
<header><nav>Logo</nav></header>
<main><section><h1>Title</h1><button></button></section></main>
<footer>Copyright</footer>
</body></html>"""

    good_html = base_html.replace("<button></button>", '<button>Submit</button>')

    with tempfile.TemporaryDirectory() as td1:
        with open(os.path.join(td1, "index.html"), "w") as f:
            f.write(base_html)
        score_bad, _ = design_score(td1)

    with tempfile.TemporaryDirectory() as td2:
        with open(os.path.join(td2, "index.html"), "w") as f:
            f.write(good_html)
        score_good, _ = design_score(td2)

    assert score_good > score_bad, (
        f"有aria-label的应比无的分数高: {score_good} vs {score_bad}"
    )


def test_lint_form_label_no_inputs():
    """无 input 元素时不应报 form_label 违规。"""
    import tempfile
    import os
    from driving.design_context import lint_design_quality

    html = """<html lang="en"><head>
<meta name="viewport" content="width=device-width">
<style>body{font-size:16px}@media(max-width:768px){}</style>
</head><body><header>H</header><main><section><p>Text</p></section></main><footer>F</footer>
</body></html>"""

    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        violations = lint_design_quality(td)

    label_violations = [v for v in violations if v["rule"] == "form_label"]
    assert label_violations == []


# ---------- M39: design_brief 集成新 lint 维度到 worker 提示 ----------


def test_build_design_brief_includes_aria_label_requirement():
    """完整版 brief 应包含 aria-label 要求。"""
    from driving.design_context import build_design_brief
    brief = build_design_brief("dark")
    assert "aria-label" in brief
    assert "可访问名称" in brief or "aria-label" in brief


def test_build_design_brief_includes_heading_hierarchy_requirement():
    """完整版 brief 应包含标题层级要求。"""
    from driving.design_context import build_design_brief
    brief = build_design_brief("dark")
    assert "h1→h2" in brief or "不跳级" in brief


def test_build_design_brief_includes_form_label_requirement():
    """完整版 brief 应包含 input label 要求。"""
    from driving.design_context import build_design_brief
    brief = build_design_brief("dark")
    assert "label" in brief.lower()
    assert "input" in brief.lower()


def test_build_design_brief_compact_includes_all_new_rules():
    """精简版 brief 应包含所有 M34-M38 新规则。"""
    from driving.design_context import build_design_brief_compact
    brief = build_design_brief_compact("dark")
    # M35: 组件状态
    assert "active" in brief
    assert "disabled" in brief
    # M35: @media 响应式
    assert "@media" in brief
    # M34: focus-visible
    assert "focus-visible" in brief
    # M37: aria-label
    assert "aria-label" in brief
    # M34: 标题层级
    assert "h1" in brief or "跳级" in brief


# ---------- M48: auto_fix_color_palette — 配色超过 5 种时确定性合并 ----------


def test_auto_fix_color_palette_too_many_colors():
    """配色超过 5 种时，auto_fix 应合并到 top-5 最常用色。"""
    import tempfile
    import os
    import re
    from driving.design_context import auto_fix_color_palette, design_score

    # 8 种设计色（不含黑白），其中 #0A84FF 出现 4 次（最多）
    html = """<html><head>
<style>
:root { --c1: #0A84FF; --c2: #FF3B30; --c3: #34C759; --c4: #FF9500; --c5: #AF52DE; --c6: #5AC8FA; --c7: #FFD60A; --c8: #BF5AF2; }
</style>
</head><body>
<div style="color:#0A84FF">a</div>
<div style="color:#0A84FF">b</div>
<div style="color:#0A84FF">c</div>
<div style="color:#0A84FF">d</div>
<div style="color:#FF3B30">e</div>
<div style="color:#34C759">f</div>
<div style="color:#FF9500">g</div>
<div style="color:#AF52DE">h</div>
</body></html>"""

    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        changed = auto_fix_color_palette(td)
        with open(os.path.join(td, "index.html"), "r") as f:
            content = f.read()

        # 验证：修改后设计色 ≤ 5
        hex_colors = set(re.findall(r"#[0-9A-Fa-f]{6}\b", content))
        design_colors = {c for c in hex_colors if c.upper() not in ("#000000", "#FFFFFF")}
        score, notes = design_score(td)

    assert changed is True
    assert len(design_colors) <= 5, f"合并后应≤5色，实际{len(design_colors)}: {design_colors}"
    # 最常用的色应保留
    assert "#0A84FF" in content.upper() or "#0a84ff" in content.lower()


def test_auto_fix_color_palette_five_or_less_no_change():
    """配色 ≤ 5 种时不修改。"""
    import tempfile
    import os
    from driving.design_context import auto_fix_color_palette

    html = """<html><head>
<style>:root { --c1: #0A84FF; --c2: #FF3B30; --c3: #34C759; }</style>
</head><body><div style="color:#0A84FF">a</div></body></html>"""

    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        changed = auto_fix_color_palette(td)

    assert changed is False


def test_auto_fix_color_palette_empty_dir():
    """空目录不报错。"""
    import tempfile
    from driving.design_context import auto_fix_color_palette

    with tempfile.TemporaryDirectory() as td:
        changed = auto_fix_color_palette(td)
    assert changed is False


def test_auto_fix_design_issues_includes_color_palette():
    """auto_fix_design_issues 组合应包含 color_palette 修复。"""
    import tempfile
    import os
    import re
    from driving.design_context import auto_fix_design_issues

    # 7 种设计色
    html = """<html lang="zh"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<style>:root { --c1: #0A84FF; --c2: #FF3B30; --c3: #34C759; --c4: #FF9500; --c5: #AF52DE; --c6: #5AC8FA; --c7: #FFD60A; }
body { margin: 0; }</style>
</head><body><header>H</header><main><section>S</section></main><footer>F</footer>
<div style="color:#0A84FF">a</div><div style="color:#0A84FF">b</div>
<div style="color:#FF3B30">c</div><div style="color:#34C759">d</div>
<div style="color:#FF9500">e</div><div style="color:#AF52DE">f</div>
</body></html>"""

    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        auto_fix_design_issues(td)
        with open(os.path.join(td, "index.html"), "r") as f:
            content = f.read()
        hex_colors = set(re.findall(r"#[0-9A-Fa-f]{6}\b", content))
        design_colors = {c for c in hex_colors if c.upper() not in ("#000000", "#FFFFFF")}

    assert len(design_colors) <= 5, f"组合修复后应≤5色，实际{len(design_colors)}"


# ---------- M53: 入场动画 lint + auto-fix（scroll-reveal / stagger fade-in） ----------


def test_check_scroll_animation_no_html():
    """无 HTML 文件时不应报违规。"""
    import tempfile
    from driving.design_context import check_scroll_animation

    with tempfile.TemporaryDirectory() as td:
        violations = check_scroll_animation(td)

    assert violations == []


def test_check_scroll_animation_missing():
    """无 @keyframes 也无 animation: → 报 violation。"""
    import tempfile
    import os
    from driving.design_context import check_scroll_animation

    html = """<html><head><style>body{color:red}</style></head>
    <body><p>no animation</p></body></html>"""

    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        violations = check_scroll_animation(td)

    scroll_violations = [v for v in violations if v["rule"] == "scroll_animation"]
    assert len(scroll_violations) >= 1
    assert scroll_violations[0]["severity"] == "warning"


def test_check_scroll_animation_present():
    """有 @keyframes 用 opacity/transform + 元素使用 animation: → 不报违规。"""
    import tempfile
    import os
    from driving.design_context import check_scroll_animation

    html = """<html><head><style>
    @keyframes fadeInUp{from{opacity:0;transform:translateY(20px)}to{opacity:1;transform:translateY(0)}}
    section{animation:fadeInUp 0.8s ease-out both}
    </style></head><body><section>content</section></body></html>"""

    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        violations = check_scroll_animation(td)

    scroll_violations = [v for v in violations if v["rule"] == "scroll_animation"]
    assert scroll_violations == []


def test_check_scroll_animation_keyframes_not_used():
    """有 @keyframes 但无元素使用 animation: → 报违规（动画定义了但没生效）。"""
    import tempfile
    import os
    from driving.design_context import check_scroll_animation

    html = """<html><head><style>
    @keyframes fadeInUp{from{opacity:0}to{opacity:1}}
    body{color:red}
    </style></head><body><p>no element uses animation</p></body></html>"""

    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        violations = check_scroll_animation(td)

    scroll_violations = [v for v in violations if v["rule"] == "scroll_animation"]
    assert len(scroll_violations) >= 1


def test_check_scroll_animation_empty_dir():
    """空目录不应报错。"""
    import tempfile
    from driving.design_context import check_scroll_animation

    with tempfile.TemporaryDirectory() as td:
        violations = check_scroll_animation(td)

    assert violations == []


def test_auto_fix_scroll_animation_injects():
    """无入场动画时应自动注入 @keyframes + animation。"""
    import tempfile
    import os
    from driving.design_context import auto_fix_scroll_animation

    html = """<html><head><style>body{color:red}</style></head>
    <body><section>content</section></body></html>"""

    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        changed = auto_fix_scroll_animation(td)
        with open(os.path.join(td, "index.html")) as f:
            content = f.read()

    assert changed is True
    assert "@keyframes" in content
    assert "animation:" in content.lower() or "animation :" in content.lower()
    # 注入的动画应使用 opacity 或 transform（性能友好）
    assert "opacity" in content or "transform" in content


def test_auto_fix_scroll_animation_skips_if_exists():
    """已有入场动画时不修改。"""
    import tempfile
    import os
    from driving.design_context import auto_fix_scroll_animation

    html = """<html><head><style>
    @keyframes fadeIn{from{opacity:0}to{opacity:1}}
    section{animation:fadeIn 0.5s ease-out}
    </style></head><body><section>content</section></body></html>"""

    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        changed = auto_fix_scroll_animation(td)

    assert changed is False


def test_auto_fix_scroll_animation_empty_dir():
    """空目录应返回 False。"""
    import tempfile
    from driving.design_context import auto_fix_scroll_animation

    with tempfile.TemporaryDirectory() as td:
        changed = auto_fix_scroll_animation(td)

    assert changed is False


def test_auto_fix_scroll_animation_injects_restrained():
    """注入的动画应克制（0.8s ease-out，物理呼吸式，非快速闪烁）。"""
    import tempfile
    import os
    from driving.design_context import auto_fix_scroll_animation

    html = """<html><head><style>body{color:red}</style></head>
    <body><section>content</section></body></html>"""

    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        auto_fix_scroll_animation(td)
        with open(os.path.join(td, "index.html")) as f:
            content = f.read()

    # 动画时长应 ≥ 0.5s（克制，非快速闪烁）
    import re
    durations = re.findall(r"animation[^;]*([\d.]+)s", content, re.IGNORECASE)
    assert durations, "应有 animation 时长"
    for d in durations:
        assert float(d) >= 0.5, f"动画时长 {d}s 太快，应≥0.5s（克制呼吸式）"


def test_auto_fix_design_issues_includes_scroll_animation():
    """auto_fix_design_issues 组合函数应包含 scroll_animation 修复。"""
    import tempfile
    import os
    from driving.design_context import auto_fix_design_issues

    html = """<html><head><style>body{color:red}</style></head>
    <body><section>content</section></body></html>"""

    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        auto_fix_design_issues(td)
        with open(os.path.join(td, "index.html")) as f:
            content = f.read()

    assert "@keyframes" in content
    assert "animation:" in content.lower() or "animation :" in content.lower()


def test_lint_design_quality_includes_scroll_animation():
    """lint_design_quality 应包含 scroll_animation 规则检查。"""
    import tempfile
    import os
    from driving.design_context import lint_design_quality

    html = """<html><head><style>body{color:red}</style></head>
    <body><section>content</section></body></html>"""

    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        violations = lint_design_quality(td)

    scroll_violations = [v for v in violations if v["rule"] == "scroll_animation"]
    assert len(scroll_violations) >= 1


def test_design_score_penalizes_missing_scroll_animation():
    """缺少入场动画的 HTML 应比有的分数低。"""
    import tempfile
    import os
    from driving.design_context import design_score

    base_html = """<!DOCTYPE html>
<html lang="zh"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<style>
:root { --color-bg: #0D0D12; --color-text: #F5F5F5; --color-accent: #0A84FF; }
body { transition: opacity 0.3s ease; }
:focus-visible { outline: 2px solid var(--color-accent); }
button:hover{opacity:0.85}button:active{transform:scale(0.98)}button:focus{outline:2px solid blue}button:disabled{opacity:0.5}
@media (max-width: 768px) { body { font-size: 14px; } }
</style></head><body>
<header><nav>Logo</nav></header>
<main><section><h1>Title</h1></section></main>
<footer>Copyright</footer>
</body></html>"""

    html_with_anim = base_html.replace(
        "</style>",
        "@keyframes fadeInUp{from{opacity:0;transform:translateY(20px)}to{opacity:1;transform:translateY(0)}}section{animation:fadeInUp 0.8s ease-out both}</style>",
    )

    with tempfile.TemporaryDirectory() as td1:
        with open(os.path.join(td1, "index.html"), "w") as f:
            f.write(base_html)
        score_no_anim, _ = design_score(td1)

    with tempfile.TemporaryDirectory() as td2:
        with open(os.path.join(td2, "index.html"), "w") as f:
            f.write(html_with_anim)
        score_with_anim, _ = design_score(td2)

    assert score_with_anim > score_no_anim, (
        f"有入场动画应比无入场动画分数高: {score_with_anim} vs {score_no_anim}"
    )


# ---------- M54: placeholder text lint（AI 生成 UI 头号破绽） ----------


def test_check_placeholder_text_no_html():
    """无 HTML 文件时不应报违规。"""
    import tempfile
    from driving.design_context import check_placeholder_text

    with tempfile.TemporaryDirectory() as td:
        violations = check_placeholder_text(td)

    assert violations == []


def test_check_placeholder_text_lorem_ipsum():
    """检测 Lorem ipsum 占位文本。"""
    import tempfile
    import os
    from driving.design_context import check_placeholder_text

    html = """<html><head><meta name="viewport" content="width=device-width"></head>
    <body><main><section><p>Lorem ipsum dolor sit amet</p></section></main></body></html>"""

    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        violations = check_placeholder_text(td)

    ph_violations = [v for v in violations if v["rule"] == "placeholder_text"]
    assert len(ph_violations) >= 1
    assert ph_violations[0]["severity"] == "error"


def test_check_placeholder_text_chinese_sample():
    """检测中文占位文本：示例文本/示例内容/内容内容内容。"""
    import tempfile
    import os
    from driving.design_context import check_placeholder_text

    html = """<html><head><meta name="viewport" content="width=device-width"></head>
    <body><main><section><h1>示例标题</h1><p>内容内容内容</p></section></main></body></html>"""

    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        violations = check_placeholder_text(td)

    ph_violations = [v for v in violations if v["rule"] == "placeholder_text"]
    assert len(ph_violations) >= 1


def test_check_placeholder_text_click_here():
    """检测 'Click here' / '点击这里' 等无信息量按钮文案。"""
    import tempfile
    import os
    from driving.design_context import check_placeholder_text

    html = """<html><head><meta name="viewport" content="width=device-width"></head>
    <body><main><section><a href="#">Click here</a></section></main></body></html>"""

    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        violations = check_placeholder_text(td)

    ph_violations = [v for v in violations if v["rule"] == "placeholder_text"]
    assert len(ph_violations) >= 1


def test_check_placeholder_text_real_content():
    """真实有意义的文案不应报违规。"""
    import tempfile
    import os
    from driving.design_context import check_placeholder_text

    html = """<html lang="zh"><head><meta name="viewport" content="width=device-width"></head>
    <body><main><section>
    <h1>Flipped AI 开发工厂</h1>
    <p>接入本地 MLX 双模型的 agentic 代码编辑器平台</p>
    <a href="/docs">查看文档</a>
    </section></main></body></html>"""

    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        violations = check_placeholder_text(td)

    ph_violations = [v for v in violations if v["rule"] == "placeholder_text"]
    assert ph_violations == [], f"真实文案不应报违规: {ph_violations}"


def test_check_placeholder_text_sample_text():
    """检测 'Sample text' / 'Sample content' 等英文占位。"""
    import tempfile
    import os
    from driving.design_context import check_placeholder_text

    html = """<html><head><meta name="viewport" content="width=device-width"></head>
    <body><main><section><p>Sample text goes here</p></section></main></body></html>"""

    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        violations = check_placeholder_text(td)

    ph_violations = [v for v in violations if v["rule"] == "placeholder_text"]
    assert len(ph_violations) >= 1


def test_check_placeholder_text_empty_dir():
    """空目录应返回空列表。"""
    import tempfile
    from driving.design_context import check_placeholder_text

    with tempfile.TemporaryDirectory() as td:
        violations = check_placeholder_text(td)

    assert violations == []


def test_check_placeholder_text_repeated_chars():
    """检测重复字符占位：xxxxx / ..... / -----。"""
    import tempfile
    import os
    from driving.design_context import check_placeholder_text

    html = """<html><head><meta name="viewport" content="width=device-width"></head>
    <body><main><section><h1>xxxxxxxxx</h1></section></main></body></html>"""

    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        violations = check_placeholder_text(td)

    ph_violations = [v for v in violations if v["rule"] == "placeholder_text"]
    assert len(ph_violations) >= 1


def test_lint_design_quality_includes_placeholder_text():
    """lint_design_quality 应包含 placeholder_text 规则。"""
    import tempfile
    import os
    from driving.design_context import lint_design_quality

    html = """<html><head><meta name="viewport" content="width=device-width"></head>
    <body><main><section><p>Lorem ipsum dolor sit amet</p></section></main></body></html>"""

    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        violations = lint_design_quality(td)

    ph_violations = [v for v in violations if v["rule"] == "placeholder_text"]
    assert len(ph_violations) >= 1


def test_design_score_penalizes_placeholder_text():
    """有占位文本的 HTML 应比真实文案的分数低。"""
    import tempfile
    import os
    from driving.design_context import design_score

    base_html = """<!DOCTYPE html>
<html lang="zh"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<style>
:root { --color-bg: #0D0D12; --color-text: #F5F5F5; --color-accent: #0A84FF; }
body { transition: opacity 0.3s ease; }
:focus-visible { outline: 2px solid var(--color-accent); }
button:hover{opacity:0.85}button:active{transform:scale(0.98)}button:focus{outline:2px solid blue}button:disabled{opacity:0.5}
@media (max-width: 768px) { body { font-size: 14px; } }
@keyframes fadeInUp{from{opacity:0;transform:translateY(20px)}to{opacity:1;transform:translateY(0)}}
section{animation:fadeInUp 0.8s ease-out both}
</style></head><body>
<header><nav>Logo</nav></header>
<main><section><h1>__TITLE__</h1><p>__BODY__</p></section></main>
<footer>Copyright</footer>
</body></html>"""

    real_html = base_html.replace("__TITLE__", "Flipped 开发工厂").replace("__BODY__", "自主迭代的 AI 平台")
    placeholder_html = base_html.replace("__TITLE__", "示例标题").replace("__BODY__", "Lorem ipsum dolor sit amet")

    with tempfile.TemporaryDirectory() as td1:
        with open(os.path.join(td1, "index.html"), "w") as f:
            f.write(real_html)
        score_real, _ = design_score(td1)

    with tempfile.TemporaryDirectory() as td2:
        with open(os.path.join(td2, "index.html"), "w") as f:
            f.write(placeholder_html)
        score_ph, _ = design_score(td2)

    assert score_real > score_ph, (
        f"真实文案应比占位文本分数高: {score_real} vs {score_ph}"
    )


# ---------- M55: auto_fix_placeholder_text — 替换占位文本为有意义文案 ----------


def test_auto_fix_placeholder_text_lorem_ipsum():
    """Lorem ipsum 应被替换为中性文案。"""
    import tempfile
    import os
    from driving.design_context import auto_fix_placeholder_text, check_placeholder_text

    html = """<html><head><meta name="viewport" content="width=device-width"></head>
    <body><main><section><p>Lorem ipsum dolor sit amet</p></section></main></body></html>"""

    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        changed = auto_fix_placeholder_text(td)
        with open(os.path.join(td, "index.html")) as f:
            content = f.read()
        violations = check_placeholder_text(td)

    assert changed is True
    assert "lorem ipsum" not in content.lower()
    ph_violations = [v for v in violations if v["rule"] == "placeholder_text"]
    assert ph_violations == [], f"修复后不应再有占位文本违规: {ph_violations}"


def test_auto_fix_placeholder_text_chinese_sample():
    """中文示例文本应被替换。"""
    import tempfile
    import os
    from driving.design_context import auto_fix_placeholder_text

    html = """<html><head><meta name="viewport" content="width=device-width"></head>
    <body><main><section><h1>示例标题</h1><p>示例内容</p></section></main></body></html>"""

    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        changed = auto_fix_placeholder_text(td)
        with open(os.path.join(td, "index.html")) as f:
            content = f.read()

    assert changed is True
    assert "示例标题" not in content
    assert "示例内容" not in content


def test_auto_fix_placeholder_text_click_here():
    """Click here 应被替换为更有意义的文案。"""
    import tempfile
    import os
    from driving.design_context import auto_fix_placeholder_text

    html = """<html><head><meta name="viewport" content="width=device-width"></head>
    <body><main><section><a href="#">Click here</a></section></main></body></html>"""

    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        changed = auto_fix_placeholder_text(td)
        with open(os.path.join(td, "index.html")) as f:
            content = f.read()

    assert changed is True
    assert "click here" not in content.lower()


def test_auto_fix_placeholder_text_no_change_if_clean():
    """无占位文本时不应修改文件。"""
    import tempfile
    import os
    from driving.design_context import auto_fix_placeholder_text

    html = """<html lang="zh"><head><meta name="viewport" content="width=device-width"></head>
    <body><main><section><h1>Flipped 开发工厂</h1><p>自主迭代的 AI 平台</p></section></main></body></html>"""

    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        changed = auto_fix_placeholder_text(td)

    assert changed is False


def test_auto_fix_placeholder_text_empty_dir():
    """空目录应返回 False。"""
    import tempfile
    from driving.design_context import auto_fix_placeholder_text

    with tempfile.TemporaryDirectory() as td:
        changed = auto_fix_placeholder_text(td)

    assert changed is False


def test_auto_fix_placeholder_text_repeated_chars():
    """重复字符占位应被替换。"""
    import tempfile
    import os
    from driving.design_context import auto_fix_placeholder_text

    html = """<html><head><meta name="viewport" content="width=device-width"></head>
    <body><main><section><h1>xxxxxxxxx</h1></section></main></body></html>"""

    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        changed = auto_fix_placeholder_text(td)
        with open(os.path.join(td, "index.html")) as f:
            content = f.read()

    assert changed is True
    assert "xxxxxxxxx" not in content


def test_auto_fix_placeholder_text_idempotent():
    """修复后再次运行不应再修改。"""
    import tempfile
    import os
    from driving.design_context import auto_fix_placeholder_text

    html = """<html><head><meta name="viewport" content="width=device-width"></head>
    <body><main><section><p>Lorem ipsum dolor sit amet</p></section></main></body></html>"""

    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        auto_fix_placeholder_text(td)
        changed2 = auto_fix_placeholder_text(td)

    assert changed2 is False


def test_auto_fix_design_issues_includes_placeholder_text():
    """auto_fix_design_issues 组合函数应包含 placeholder_text 修复。"""
    import tempfile
    import os
    from driving.design_context import auto_fix_design_issues

    html = """<html><head><meta name="viewport" content="width=device-width"></head>
    <body><main><section><p>Lorem ipsum dolor sit amet</p></section></main></body></html>"""

    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        auto_fix_design_issues(td)
        with open(os.path.join(td, "index.html")) as f:
            content = f.read()

    assert "lorem ipsum" not in content.lower()


# ---------- M56: 空链接/无效 href 检测（AI 生成 UI 常见破绽） ----------


def test_check_empty_links_no_html():
    """无 HTML 文件时不应报违规。"""
    import tempfile
    from driving.design_context import check_empty_links

    with tempfile.TemporaryDirectory() as td:
        violations = check_empty_links(td)

    assert violations == []


def test_check_empty_links_hash_href():
    """href='#' 应报违规。"""
    import tempfile
    import os
    from driving.design_context import check_empty_links

    html = """<html><head><meta name="viewport" content="width=device-width"></head>
    <body><main><section><a href="#">Link</a></section></main></body></html>"""

    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        violations = check_empty_links(td)

    link_violations = [v for v in violations if v["rule"] == "empty_link"]
    assert len(link_violations) >= 1
    assert link_violations[0]["severity"] == "warning"


def test_check_empty_links_javascript_void():
    """href='javascript:void(0)' 应报违规。"""
    import tempfile
    import os
    from driving.design_context import check_empty_links

    html = """<html><head><meta name="viewport" content="width=device-width"></head>
    <body><main><section><a href="javascript:void(0)">Click</a></section></main></body></html>"""

    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        violations = check_empty_links(td)

    link_violations = [v for v in violations if v["rule"] == "empty_link"]
    assert len(link_violations) >= 1


def test_check_empty_links_missing_href():
    """<a> 无 href 属性应报违规。"""
    import tempfile
    import os
    from driving.design_context import check_empty_links

    html = """<html><head><meta name="viewport" content="width=device-width"></head>
    <body><main><section><a>Link without href</a></section></main></body></html>"""

    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        violations = check_empty_links(td)

    link_violations = [v for v in violations if v["rule"] == "empty_link"]
    assert len(link_violations) >= 1


def test_check_empty_links_valid_href():
    """有效 href 不应报违规。"""
    import tempfile
    import os
    from driving.design_context import check_empty_links

    html = """<html><head><meta name="viewport" content="width=device-width"></head>
    <body><main><section><a href="/docs">查看文档</a></section></main></body></html>"""

    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        violations = check_empty_links(td)

    link_violations = [v for v in violations if v["rule"] == "empty_link"]
    assert link_violations == [], f"有效 href 不应报违规: {link_violations}"


def test_check_empty_links_external_url():
    """外部 URL 不应报违规。"""
    import tempfile
    import os
    from driving.design_context import check_empty_links

    html = """<html><head><meta name="viewport" content="width=device-width"></head>
    <body><main><section><a href="https://example.com">External</a></section></main></body></html>"""

    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        violations = check_empty_links(td)

    link_violations = [v for v in violations if v["rule"] == "empty_link"]
    assert link_violations == []


def test_check_empty_links_empty_dir():
    """空目录应返回空列表。"""
    import tempfile
    from driving.design_context import check_empty_links

    with tempfile.TemporaryDirectory() as td:
        violations = check_empty_links(td)

    assert violations == []


def test_check_empty_links_anchor_link():
    """href='#section' 锚点链接不应报违规（同页跳转是合法的）。"""
    import tempfile
    import os
    from driving.design_context import check_empty_links

    html = """<html><head><meta name="viewport" content="width=device-width"></head>
    <body><main><section id="top"><a href="#section2">跳转</a></section>
    <section id="section2">内容</section></main></body></html>"""

    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        violations = check_empty_links(td)

    link_violations = [v for v in violations if v["rule"] == "empty_link"]
    assert link_violations == [], f"锚点链接不应报违规: {link_violations}"


def test_lint_design_quality_includes_empty_links():
    """lint_design_quality 应包含 empty_link 规则。"""
    import tempfile
    import os
    from driving.design_context import lint_design_quality

    html = """<html><head><meta name="viewport" content="width=device-width"></head>
    <body><main><section><a href="#">Link</a></section></main></body></html>"""

    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        violations = lint_design_quality(td)

    link_violations = [v for v in violations if v["rule"] == "empty_link"]
    assert len(link_violations) >= 1


def test_design_score_penalizes_empty_links():
    """有空链接的 HTML 应比有效链接的分数低。"""
    import tempfile
    import os
    from driving.design_context import design_score

    base_html = """<!DOCTYPE html>
<html lang="zh"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<style>
:root { --color-bg: #0D0D12; --color-text: #F5F5F5; --color-accent: #0A84FF; }
body { transition: opacity 0.3s ease; }
:focus-visible { outline: 2px solid var(--color-accent); }
button:hover{opacity:0.85}button:active{transform:scale(0.98)}button:focus{outline:2px solid blue}button:disabled{opacity:0.5}
@media (max-width: 768px) { body { font-size: 14px; } }
@keyframes fadeInUp{from{opacity:0;transform:translateY(20px)}to{opacity:1;transform:translateY(0)}}
section{animation:fadeInUp 0.8s ease-out both}
</style></head><body>
<header><nav>Logo</nav></header>
<main><section><a href="__HREF__">查看详情</a></section></main>
<footer>Copyright</footer>
</body></html>"""

    valid_html = base_html.replace("__HREF__", "/docs")
    empty_html = base_html.replace("__HREF__", "#")

    with tempfile.TemporaryDirectory() as td1:
        with open(os.path.join(td1, "index.html"), "w") as f:
            f.write(valid_html)
        score_valid, _ = design_score(td1)

    with tempfile.TemporaryDirectory() as td2:
        with open(os.path.join(td2, "index.html"), "w") as f:
            f.write(empty_html)
        score_empty, _ = design_score(td2)

    assert score_valid > score_empty, (
        f"有效链接应比空链接分数高: {score_valid} vs {score_empty}"
    )


# ---------- M57: 内联样式检测（AI 应该用 CSS class 而非 inline style） ----------


def test_check_inline_styles_no_html():
    """无 HTML 文件时不应报违规。"""
    import tempfile
    from driving.design_context import check_inline_styles

    with tempfile.TemporaryDirectory() as td:
        violations = check_inline_styles(td)

    assert violations == []


def test_check_inline_styles_present():
    """有 style= 内联样式应报违规。"""
    import tempfile
    import os
    from driving.design_context import check_inline_styles

    html = """<html><head><meta name="viewport" content="width=device-width"></head>
    <body><main><section><div style="color:red;padding:10px">content</div></section></main></body></html>"""

    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        violations = check_inline_styles(td)

    style_violations = [v for v in violations if v["rule"] == "inline_style"]
    assert len(style_violations) >= 1
    assert style_violations[0]["severity"] == "warning"


def test_check_inline_styles_absent():
    """无内联样式不应报违规。"""
    import tempfile
    import os
    from driving.design_context import check_inline_styles

    html = """<html><head><meta name="viewport" content="width=device-width">
    <style>.card{color:red;padding:10px}</style></head>
    <body><main><section><div class="card">content</div></section></main></body></html>"""

    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        violations = check_inline_styles(td)

    style_violations = [v for v in violations if v["rule"] == "inline_style"]
    assert style_violations == [], f"无内联样式不应报违规: {style_violations}"


def test_check_inline_styles_multiple():
    """多个内联样式应报多个违规。"""
    import tempfile
    import os
    from driving.design_context import check_inline_styles

    html = """<html><head><meta name="viewport" content="width=device-width"></head>
    <body><main>
    <div style="color:red">A</div>
    <div style="color:blue">B</div>
    <div style="color:green">C</div>
    </main></body></html>"""

    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        violations = check_inline_styles(td)

    style_violations = [v for v in violations if v["rule"] == "inline_style"]
    assert len(style_violations) >= 3


def test_check_inline_styles_empty_dir():
    """空目录应返回空列表。"""
    import tempfile
    from driving.design_context import check_inline_styles

    with tempfile.TemporaryDirectory() as td:
        violations = check_inline_styles(td)

    assert violations == []


def test_check_inline_styles_ignores_style_tag():
    """<style> 标签内的 CSS 不应被误报为内联样式。"""
    import tempfile
    import os
    from driving.design_context import check_inline_styles

    html = """<html><head><meta name="viewport" content="width=device-width">
    <style>body { color: red; }</style></head>
    <body><main><section>content</section></main></body></html>"""

    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        violations = check_inline_styles(td)

    style_violations = [v for v in violations if v["rule"] == "inline_style"]
    assert style_violations == [], f"<style> 标签不应被误报: {style_violations}"


def test_lint_design_quality_includes_inline_styles():
    """lint_design_quality 应包含 inline_style 规则。"""
    import tempfile
    import os
    from driving.design_context import lint_design_quality

    html = """<html><head><meta name="viewport" content="width=device-width"></head>
    <body><main><section><div style="color:red">content</div></section></main></body></html>"""

    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        violations = lint_design_quality(td)

    style_violations = [v for v in violations if v["rule"] == "inline_style"]
    assert len(style_violations) >= 1


def test_design_score_penalizes_inline_styles():
    """有内联样式的 HTML 应比用 CSS class 的分数低。"""
    import tempfile
    import os
    from driving.design_context import design_score

    base_html = """<!DOCTYPE html>
<html lang="zh"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<style>
:root { --color-bg: #0D0D12; --color-text: #F5F5F5; --color-accent: #0A84FF; }
body { transition: opacity 0.3s ease; }
:focus-visible { outline: 2px solid var(--color-accent); }
button:hover{opacity:0.85}button:active{transform:scale(0.98)}button:focus{outline:2px solid blue}button:disabled{opacity:0.5}
@media (max-width: 768px) { body { font-size: 14px; } }
@keyframes fadeInUp{from{opacity:0;transform:translateY(20px)}to{opacity:1;transform:translateY(0)}}
section{animation:fadeInUp 0.8s ease-out both}
</style></head><body>
<header><nav>Logo</nav></header>
<main><section><div __ATTR__>查看详情</div></section></main>
<footer>Copyright</footer>
</body></html>"""

    clean_html = base_html.replace("__ATTR__", 'class="card"')
    inline_html = base_html.replace("__ATTR__", 'style="color:red"')

    with tempfile.TemporaryDirectory() as td1:
        with open(os.path.join(td1, "index.html"), "w") as f:
            f.write(clean_html)
        score_clean, _ = design_score(td1)

    with tempfile.TemporaryDirectory() as td2:
        with open(os.path.join(td2, "index.html"), "w") as f:
            f.write(inline_html)
        score_inline, _ = design_score(td2)

    assert score_clean > score_inline, (
        f"无内联样式应比有内联样式分数高: {score_clean} vs {score_inline}"
    )


# ---------- M58: console.log 调试残留检测 ----------


def test_check_console_log_no_html():
    """无 HTML 文件时不应报违规。"""
    import tempfile
    from driving.design_context import check_console_log

    with tempfile.TemporaryDirectory() as td:
        violations = check_console_log(td)

    assert violations == []


def test_check_console_log_present():
    """<script> 中有 console.log 应报违规。"""
    import tempfile
    import os
    from driving.design_context import check_console_log

    html = """<html><head><meta name="viewport" content="width=device-width"></head>
    <body><main><section>content</section></main>
    <script>console.log("debug");</script>
    </body></html>"""

    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        violations = check_console_log(td)

    log_violations = [v for v in violations if v["rule"] == "console_log"]
    assert len(log_violations) >= 1
    assert log_violations[0]["severity"] == "warning"


def test_check_console_log_absent():
    """无 console.log 不应报违规。"""
    import tempfile
    import os
    from driving.design_context import check_console_log

    html = """<html><head><meta name="viewport" content="width=device-width"></head>
    <body><main><section>content</section></main>
    <script>document.querySelector("h1").textContent = "Hello";</script>
    </body></html>"""

    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        violations = check_console_log(td)

    log_violations = [v for v in violations if v["rule"] == "console_log"]
    assert log_violations == [], f"无 console.log 不应报违规: {log_violations}"


def test_check_console_log_multiple():
    """多个 console.log 应报多个违规。"""
    import tempfile
    import os
    from driving.design_context import check_console_log

    html = """<html><head><meta name="viewport" content="width=device-width"></head>
    <body><main><section>content</section></main>
    <script>
    console.log("a");
    console.log("b");
    console.log("c");
    </script>
    </body></html>"""

    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        violations = check_console_log(td)

    log_violations = [v for v in violations if v["rule"] == "console_log"]
    assert len(log_violations) >= 3


def test_check_console_log_empty_dir():
    """空目录应返回空列表。"""
    import tempfile
    from driving.design_context import check_console_log

    with tempfile.TemporaryDirectory() as td:
        violations = check_console_log(td)

    assert violations == []


def test_check_console_log_no_script():
    """无 <script> 标签时不应报违规。"""
    import tempfile
    import os
    from driving.design_context import check_console_log

    html = """<html><head><meta name="viewport" content="width=device-width"></head>
    <body><main><section>content</section></main></body></html>"""

    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        violations = check_console_log(td)

    log_violations = [v for v in violations if v["rule"] == "console_log"]
    assert log_violations == []


def test_check_console_log_not_in_text():
    """文本内容中的 'console.log' 字样不应报违规（只在 script 块内检测）。"""
    import tempfile
    import os
    from driving.design_context import check_console_log

    html = """<html><head><meta name="viewport" content="width=device-width"></head>
    <body><main><section><p>使用 console.log 调试</p></section></main></body></html>"""

    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        violations = check_console_log(td)

    log_violations = [v for v in violations if v["rule"] == "console_log"]
    assert log_violations == [], f"文本中的 console.log 字样不应报违规: {log_violations}"


def test_lint_design_quality_includes_console_log():
    """lint_design_quality 应包含 console_log 规则。"""
    import tempfile
    import os
    from driving.design_context import lint_design_quality

    html = """<html><head><meta name="viewport" content="width=device-width"></head>
    <body><main><section>content</section></main>
    <script>console.log("debug");</script>
    </body></html>"""

    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        violations = lint_design_quality(td)

    log_violations = [v for v in violations if v["rule"] == "console_log"]
    assert len(log_violations) >= 1


def test_design_score_penalizes_console_log():
    """有 console.log 的 HTML 应比没有的分数低。"""
    import tempfile
    import os
    from driving.design_context import design_score

    base_html = """<!DOCTYPE html>
<html lang="zh"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<style>
:root { --color-bg: #0D0D12; --color-text: #F5F5F5; --color-accent: #0A84FF; }
body { transition: opacity 0.3s ease; }
:focus-visible { outline: 2px solid var(--color-accent); }
button:hover{opacity:0.85}button:active{transform:scale(0.98)}button:focus{outline:2px solid blue}button:disabled{opacity:0.5}
@media (max-width: 768px) { body { font-size: 14px; } }
@keyframes fadeInUp{from{opacity:0;transform:translateY(20px)}to{opacity:1;transform:translateY(0)}}
section{animation:fadeInUp 0.8s ease-out both}
</style></head><body>
<header><nav>Logo</nav></header>
<main><section>内容</section></main>
<footer>Copyright</footer>
__SCRIPT__
</body></html>"""

    clean_html = base_html.replace("__SCRIPT__", "")
    debug_html = base_html.replace("__SCRIPT__", '<script>console.log("debug");</script>')

    with tempfile.TemporaryDirectory() as td1:
        with open(os.path.join(td1, "index.html"), "w") as f:
            f.write(clean_html)
        score_clean, _ = design_score(td1)

    with tempfile.TemporaryDirectory() as td2:
        with open(os.path.join(td2, "index.html"), "w") as f:
            f.write(debug_html)
        score_debug, _ = design_score(td2)

    assert score_clean > score_debug, (
        f"无 console.log 应比有 console.log 分数高: {score_clean} vs {score_debug}"
    )


# ---------- M59: auto_fix_console_log — 自动移除 console.log 语句 ----------


def test_auto_fix_console_log_removes():
    """console.log 语句应被移除。"""
    import tempfile
    import os
    from driving.design_context import auto_fix_console_log, check_console_log

    html = """<html><head><meta name="viewport" content="width=device-width"></head>
    <body><main><section>content</section></main>
    <script>console.log("debug");</script>
    </body></html>"""

    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        changed = auto_fix_console_log(td)
        with open(os.path.join(td, "index.html")) as f:
            content = f.read()
        violations = check_console_log(td)

    assert changed is True
    assert "console.log" not in content
    log_violations = [v for v in violations if v["rule"] == "console_log"]
    assert log_violations == [], f"修复后不应再有 console.log: {log_violations}"


def test_auto_fix_console_log_multiple():
    """多个 console.log 应全部被移除。"""
    import tempfile
    import os
    from driving.design_context import auto_fix_console_log

    html = """<html><head><meta name="viewport" content="width=device-width"></head>
    <body><main><section>content</section></main>
    <script>
    console.log("a");
    console.log("b");
    console.log("c");
    </script>
    </body></html>"""

    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        changed = auto_fix_console_log(td)
        with open(os.path.join(td, "index.html")) as f:
            content = f.read()

    assert changed is True
    assert "console.log" not in content


def test_auto_fix_console_log_preserves_other_code():
    """移除 console.log 时不应破坏其他 JS 代码。"""
    import tempfile
    import os
    from driving.design_context import auto_fix_console_log

    html = """<html><head><meta name="viewport" content="width=device-width"></head>
    <body><main><section>content</section></main>
    <script>
    console.log("debug");
    document.querySelector("h1").textContent = "Hello";
    console.log("done");
    </script>
    </body></html>"""

    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        auto_fix_console_log(td)
        with open(os.path.join(td, "index.html")) as f:
            content = f.read()

    assert "console.log" not in content
    assert 'document.querySelector("h1").textContent = "Hello"' in content


def test_auto_fix_console_log_no_change_if_clean():
    """无 console.log 时不应修改文件。"""
    import tempfile
    import os
    from driving.design_context import auto_fix_console_log

    html = """<html><head><meta name="viewport" content="width=device-width"></head>
    <body><main><section>content</section></main>
    <script>document.querySelector("h1").textContent = "Hello";</script>
    </body></html>"""

    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        changed = auto_fix_console_log(td)

    assert changed is False


def test_auto_fix_console_log_empty_dir():
    """空目录应返回 False。"""
    import tempfile
    from driving.design_context import auto_fix_console_log

    with tempfile.TemporaryDirectory() as td:
        changed = auto_fix_console_log(td)

    assert changed is False


def test_auto_fix_console_log_idempotent():
    """修复后再次运行不应再修改。"""
    import tempfile
    import os
    from driving.design_context import auto_fix_console_log

    html = """<html><head><meta name="viewport" content="width=device-width"></head>
    <body><main><section>content</section></main>
    <script>console.log("debug");</script>
    </body></html>"""

    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        auto_fix_console_log(td)
        changed2 = auto_fix_console_log(td)

    assert changed2 is False


def test_auto_fix_design_issues_includes_console_log():
    """auto_fix_design_issues 组合函数应包含 console_log 修复。"""
    import tempfile
    import os
    from driving.design_context import auto_fix_design_issues

    html = """<html><head><meta name="viewport" content="width=device-width"></head>
    <body><main><section>content</section></main>
    <script>console.log("debug");</script>
    </body></html>"""

    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        auto_fix_design_issues(td)
        with open(os.path.join(td, "index.html")) as f:
            content = f.read()

    assert "console.log" not in content


# ---------- M60: auto_fix_empty_links ----------


def test_auto_fix_empty_links_hash():
    """href='#' 的 <a> 应被转为 <span>，移除 href。"""
    import tempfile
    import os
    from driving.design_context import auto_fix_empty_links, check_empty_links

    html = """<html><head><meta name="viewport" content="width=device-width"></head>
    <body><main id="main"><section>content</section></main>
    <a href="#">Click here</a>
    </body></html>"""

    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        changed = auto_fix_empty_links(td)
        with open(os.path.join(td, "index.html")) as f:
            content = f.read()
        violations = check_empty_links(td)

    assert changed is True
    assert "Click here" in content
    assert "<span" in content
    assert "<a " not in content and "<a>" not in content
    link_violations = [v for v in violations if v["rule"] == "empty_link"]
    assert link_violations == [], f"修复后不应有空链接: {link_violations}"


def test_auto_fix_empty_links_javascript_void():
    """href='javascript:void(0)' 应被转为 <span>。"""
    import tempfile
    import os
    from driving.design_context import auto_fix_empty_links

    html = """<html><head><meta name="viewport" content="width=device-width"></head>
    <body><main><section>content</section></main>
    <a href="javascript:void(0)">Button</a>
    </body></html>"""

    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        changed = auto_fix_empty_links(td)
        with open(os.path.join(td, "index.html")) as f:
            content = f.read()

    assert changed is True
    assert "Button" in content
    assert "<span" in content
    assert "javascript:void(0)" not in content


def test_auto_fix_empty_links_preserves_valid_links():
    """合法链接不应被修改。"""
    import tempfile
    import os
    from driving.design_context import auto_fix_empty_links

    html = """<html><head><meta name="viewport" content="width=device-width"></head>
    <body><main id="home"><section>content</section></main>
    <a href="/about">About</a>
    <a href="https://example.com">External</a>
    <a href="#home">Home</a>
    <a href="mailto:test@test.com">Email</a>
    </body></html>"""

    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        changed = auto_fix_empty_links(td)

    assert changed is False


def test_auto_fix_empty_links_preserves_attributes():
    """修复时保留 class/id 等其他属性。"""
    import tempfile
    import os
    from driving.design_context import auto_fix_empty_links

    html = """<html><head><meta name="viewport" content="width=device-width"></head>
    <body><main><section>content</section></main>
    <a href="#" class="btn btn-primary" id="cta">Click</a>
    </body></html>"""

    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        auto_fix_empty_links(td)
        with open(os.path.join(td, "index.html")) as f:
            content = f.read()

    assert 'class="btn btn-primary"' in content
    assert 'id="cta"' in content
    assert "<span" in content


def test_auto_fix_empty_links_no_change_if_clean():
    """无空链接时不应修改。"""
    import tempfile
    import os
    from driving.design_context import auto_fix_empty_links

    html = """<html><head><meta name="viewport" content="width=device-width"></head>
    <body><main id="home"><section>content</section></main>
    <a href="/path">Link</a>
    </body></html>"""

    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        changed = auto_fix_empty_links(td)

    assert changed is False


def test_auto_fix_empty_links_empty_dir():
    """空目录应返回 False。"""
    import tempfile
    from driving.design_context import auto_fix_empty_links

    with tempfile.TemporaryDirectory() as td:
        changed = auto_fix_empty_links(td)

    assert changed is False


def test_auto_fix_empty_links_idempotent():
    """修复后再次运行不应再修改。"""
    import tempfile
    import os
    from driving.design_context import auto_fix_empty_links

    html = """<html><head><meta name="viewport" content="width=device-width"></head>
    <body><main><section>content</section></main>
    <a href="#">Click</a>
    </body></html>"""

    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        auto_fix_empty_links(td)
        changed2 = auto_fix_empty_links(td)

    assert changed2 is False


def test_auto_fix_design_issues_includes_empty_links():
    """auto_fix_design_issues 组合函数应包含 empty_links 修复。"""
    import tempfile
    import os
    from driving.design_context import auto_fix_design_issues

    html = """<html><head><meta name="viewport" content="width=device-width"></head>
    <body><main><section>content</section></main>
    <a href="#">Click</a>
    </body></html>"""

    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        auto_fix_design_issues(td)
        with open(os.path.join(td, "index.html")) as f:
            content = f.read()

    assert "<span" in content
    assert "<a href=\"#\">" not in content


# ---------- M61: auto_fix_inline_styles ----------


def test_auto_fix_inline_styles_removes():
    """style='...' 属性应被移除，替换为 CSS class。"""
    import tempfile
    import os
    from driving.design_context import auto_fix_inline_styles, check_inline_styles

    html = """<html><head><meta name="viewport" content="width=device-width"></head>
    <body><main><section>content</section></main>
    <div style="color: red;">Hello</div>
    </body></html>"""

    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        changed = auto_fix_inline_styles(td)
        with open(os.path.join(td, "index.html")) as f:
            content = f.read()
        violations = check_inline_styles(td)

    assert changed is True
    assert 'style="color: red;"' not in content
    style_violations = [v for v in violations if v["rule"] == "inline_style"]
    assert style_violations == [], f"修复后不应有内联样式: {style_violations}"


def test_auto_fix_inline_styles_adds_class():
    """修复后元素应有自动生成的 class。"""
    import tempfile
    import os
    from driving.design_context import auto_fix_inline_styles

    html = """<html><head><meta name="viewport" content="width=device-width"></head>
    <body><main><section>content</section></main>
    <div style="color: red;">Hello</div>
    </body></html>"""

    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        auto_fix_inline_styles(td)
        with open(os.path.join(td, "index.html")) as f:
            content = f.read()

    assert "class=" in content
    assert "auto-style-" in content


def test_auto_fix_inline_styles_adds_css_rule():
    """修复后 <style> 块应包含对应的 CSS 规则。"""
    import tempfile
    import os
    from driving.design_context import auto_fix_inline_styles

    html = """<html><head><meta name="viewport" content="width=device-width"></head>
    <body><main><section>content</section></main>
    <div style="color: red;">Hello</div>
    </body></html>"""

    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        auto_fix_inline_styles(td)
        with open(os.path.join(td, "index.html")) as f:
            content = f.read()

    assert "<style>" in content
    assert "color: red" in content or "color:red" in content


def test_auto_fix_inline_styles_preserves_existing_class():
    """元素已有 class 时应追加而非覆盖。"""
    import tempfile
    import os
    from driving.design_context import auto_fix_inline_styles

    html = """<html><head><meta name="viewport" content="width=device-width"></head>
    <body><main><section>content</section></main>
    <div class="card" style="color: red;">Hello</div>
    </body></html>"""

    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        auto_fix_inline_styles(td)
        with open(os.path.join(td, "index.html")) as f:
            content = f.read()

    assert 'class="card' in content
    assert "auto-style-" in content
    assert 'style="color: red;"' not in content


def test_auto_fix_inline_styles_no_change_if_clean():
    """无内联样式时不应修改。"""
    import tempfile
    import os
    from driving.design_context import auto_fix_inline_styles

    html = """<html><head><meta name="viewport" content="width=device-width">
    <style>.card { color: red; }</style></head>
    <body><main><section>content</section></main>
    <div class="card">Hello</div>
    </body></html>"""

    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        changed = auto_fix_inline_styles(td)

    assert changed is False


def test_auto_fix_inline_styles_empty_dir():
    """空目录应返回 False。"""
    import tempfile
    from driving.design_context import auto_fix_inline_styles

    with tempfile.TemporaryDirectory() as td:
        changed = auto_fix_inline_styles(td)

    assert changed is False


def test_auto_fix_inline_styles_idempotent():
    """修复后再次运行不应再修改。"""
    import tempfile
    import os
    from driving.design_context import auto_fix_inline_styles

    html = """<html><head><meta name="viewport" content="width=device-width"></head>
    <body><main><section>content</section></main>
    <div style="color: red;">Hello</div>
    </body></html>"""

    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        auto_fix_inline_styles(td)
        changed2 = auto_fix_inline_styles(td)

    assert changed2 is False


def test_auto_fix_design_issues_includes_inline_styles():
    """auto_fix_design_issues 组合函数应包含 inline_styles 修复。"""
    import tempfile
    import os
    from driving.design_context import auto_fix_design_issues

    html = """<html><head><meta name="viewport" content="width=device-width"></head>
    <body><main><section>content</section></main>
    <div style="color: red;">Hello</div>
    </body></html>"""

    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        auto_fix_design_issues(td)
        with open(os.path.join(td, "index.html")) as f:
            content = f.read()

    assert 'style="color: red;"' not in content
    assert "auto-style-" in content


# ---------- M62: auto_fix_color_contrast ----------


def test_auto_fix_color_contrast_adjusts():
    """低对比度的文本颜色应被调整为满足 WCAG AA 标准。"""
    import tempfile
    import os
    from driving.design_context import auto_fix_color_contrast, check_color_contrast

    # #DDDDDD (浅灰) on #FFFFFF (白底) → 对比度约 1.4:1，远低于 4.5:1
    html = """<html><head><meta name="viewport" content="width=device-width">
    <style>
    .text { background-color: #FFFFFF; color: #DDDDDD; }
    </style></head>
    <body><main><section>content</section></main>
    <div class="text">Hello</div>
    </body></html>"""

    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        changed = auto_fix_color_contrast(td)
        with open(os.path.join(td, "index.html")) as f:
            content = f.read()
        violations = check_color_contrast(td)

    assert changed is True
    assert "#FFFFFF" in content  # 背景色不变
    contrast_violations = [v for v in violations if v["rule"] == "color_contrast"]
    assert contrast_violations == [], f"修复后不应有对比度违规: {contrast_violations}"


def test_auto_fix_color_contrast_no_change_if_ok():
    """高对比度颜色对不应被修改。"""
    import tempfile
    import os
    from driving.design_context import auto_fix_color_contrast

    # #000000 (黑) on #FFFFFF (白) → 对比度 21:1，远高于 4.5:1
    html = """<html><head><meta name="viewport" content="width=device-width">
    <style>
    .text { background-color: #FFFFFF; color: #000000; }
    </style></head>
    <body><main><section>content</section></main>
    <div class="text">Hello</div>
    </body></html>"""

    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        changed = auto_fix_color_contrast(td)

    assert changed is False


def test_auto_fix_color_contrast_empty_dir():
    """空目录应返回 False。"""
    import tempfile
    from driving.design_context import auto_fix_color_contrast

    with tempfile.TemporaryDirectory() as td:
        changed = auto_fix_color_contrast(td)

    assert changed is False


def test_auto_fix_color_contrast_idempotent():
    """修复后再次运行不应再修改。"""
    import tempfile
    import os
    from driving.design_context import auto_fix_color_contrast

    html = """<html><head><meta name="viewport" content="width=device-width">
    <style>
    .text { background-color: #FFFFFF; color: #DDDDDD; }
    </style></head>
    <body><main><section>content</section></main>
    <div class="text">Hello</div>
    </body></html>"""

    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        auto_fix_color_contrast(td)
        changed2 = auto_fix_color_contrast(td)

    assert changed2 is False


def test_auto_fix_color_contrast_dark_bg():
    """深色背景上的低对比度文本应被提亮。"""
    import tempfile
    import os
    from driving.design_context import auto_fix_color_contrast, check_color_contrast

    # #333333 (深灰) on #0D0D12 (近黑) → 对比度约 1.5:1
    html = """<html><head><meta name="viewport" content="width=device-width">
    <style>
    .text { background-color: #0D0D12; color: #333333; }
    </style></head>
    <body><main><section>content</section></main>
    <div class="text">Hello</div>
    </body></html>"""

    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        changed = auto_fix_color_contrast(td)
        violations = check_color_contrast(td)

    assert changed is True
    contrast_violations = [v for v in violations if v["rule"] == "color_contrast"]
    assert contrast_violations == [], f"修复后不应有对比度违规: {contrast_violations}"


def test_auto_fix_design_issues_includes_color_contrast():
    """auto_fix_design_issues 组合函数应包含 color_contrast 修复。"""
    import tempfile
    import os
    from driving.design_context import auto_fix_design_issues, check_color_contrast

    html = """<html><head><meta name="viewport" content="width=device-width">
    <style>
    .text { background-color: #FFFFFF; color: #DDDDDD; }
    </style></head>
    <body><main><section>content</section></main>
    <div class="text">Hello</div>
    </body></html>"""

    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        auto_fix_design_issues(td)
        violations = check_color_contrast(td)

    contrast_violations = [v for v in violations if v["rule"] == "color_contrast"]
    assert contrast_violations == [], f"组合修复后不应有对比度违规: {contrast_violations}"


# ---------- M63: E2E 冒烟测试 — 完整 auto-fix 管线验证 ----------


def test_m63_smoke_all_auto_fix_repair_comprehensive_bad_html():
    """M63: E2E 冒烟测试 — 含全部可修复设计问题的 HTML →
    真实 auto_fix_design_issues（18组）一次性修复 → design_score 达标 → 无 error 违规。

    验证用户核心目标：给方向 → 自行产出 → 自行修复 → 达标。
    构造的 bad HTML 覆盖全部 4 个 error 级违规（meta_viewport/img_alt/color_contrast/placeholder_text）
    以及多个 warning 级问题（spacing/typography/console_log/empty_links/inline_styles/无CSS变量等）。
    """
    import tempfile
    import os
    from driving.design_context import (
        auto_fix_design_issues,
        design_score,
        lint_design_quality,
    )

    # 构造含多种可修复问题的 BAD HTML
    bad_html = """<!DOCTYPE html>
<html><head><meta charset="utf-8">
<style>
.bad { padding: 13px; margin: 7px; font-size: 37px; transition: margin 0.3s; background-color: #FFFFFF; color: #DDDDDD; }
</style>
</head><body>
<div class="bad">Lorem ipsum dolor sit amet</div>
<a href="#">Click here</a>
<button style="color: red;">Sample text</button>
<img src="x.png">
<script>console.log("debug"); console.log("test");</script>
</body></html>"""

    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(bad_html)

        # 修复前：分数应低，有 error 违规
        score_before, _ = design_score(td)
        violations_before = lint_design_quality(td)
        errors_before = [v for v in violations_before if v["severity"] == "error"]

        # 运行全部 18 组 auto-fix
        changed = auto_fix_design_issues(td)

        # 修复后：分数应显著提升
        score_after, notes_after = design_score(td)
        violations_after = lint_design_quality(td)
        errors_after = [v for v in violations_after if v["severity"] == "error"]

    assert changed is True, "auto_fix 应做了修改"
    assert len(errors_before) > 0, f"修复前应有 error 违规: {errors_before}"
    assert score_after > score_before, f"分数应提升: {score_before} -> {score_after}"
    assert score_after >= 70, f"修复后分数应>=70: {score_after}, notes: {notes_after}"
    assert errors_after == [], f"修复后不应有 error 违规: {errors_after}"


def test_m63_smoke_factory_loop_bad_worker_to_passing(monkeypatch):
    """M63: E2E 冒烟测试 — worker 产出 bad HTML → auto_fix 修复 →
    确定性 verify_cmd 通过 → 工厂完成。

    验证完整链路：确定性 planner 生成任务 → worker（模拟 Kimi）产出有问题的 HTML →
    auto_fix_design_issues 修复 → verify_cmd 检查通过 → 工厂 status=done。
    """
    import tempfile
    import os
    from driving.factory_loop import (
        run_factory_loop,
        FactoryState,
        FactoryStatus,
        TaskResult,
    )
    from driving.design_context import auto_fix_design_issues

    # mock GLM 不可用 → 强制确定性 planner fallback
    monkeypatch.setattr(
        "driving.factory_loop._make_llm",
        lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("no GLM")),
    )
    monkeypatch.setattr(
        "driving.task_proposer._make_llm",
        lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("no GLM")),
    )

    # worker 模拟：写 bad HTML，然后调用真实 auto_fix（模拟 local_worker 行为）
    def fake_orchestrator(task, state):
        html_path = os.path.join(state.cwd, "index.html")
        # 每次都写一份有问题的 HTML（模拟 worker 不遵守设计约束）
        bad_html = """<!DOCTYPE html>
<html><head><meta charset="utf-8">
<style>.x { padding: 13px; transition: margin 0.3s; }</style>
</head><body>
<div class="x">Lorem ipsum</div>
<a href="#">link</a>
<img src="a.png">
<script>console.log("x");</script>
</body></html>"""
        with open(html_path, "w") as f:
            f.write(bad_html)
        # 真实 auto_fix 修复所有问题
        auto_fix_design_issues(state.cwd)
        return TaskResult(
            task=task, verified=True, stop_reason="verified", iteration=1
        )

    with tempfile.TemporaryDirectory() as d:
        state = run_factory_loop(
            product_goal="做一个落地页",
            cwd=d,
            db_path=os.path.join(d, "test_factory.db"),
            checkpoint_db_path=os.path.join(d, "test_ckpt.db"),
            max_tasks=10,
            max_rounds=1,
            orchestrator_fn=fake_orchestrator,
        )

        # 工厂应完成
        assert state.status.value == "done", f"工厂应完成，实际 {state.status.value}"
        assert len(state.completed) >= 1, "应完成至少 1 个任务"
        # 产物文件应存在
        assert os.path.isfile(os.path.join(d, "index.html")), "index.html 应存在"


# ---------- M69: z-index 堆叠混乱检测 + auto-fix ----------


def test_check_zindex_chaos_no_html():
    """无 HTML 文件时应返回空列表。"""
    import tempfile
    from driving.design_context import check_zindex_chaos

    with tempfile.TemporaryDirectory() as td:
        violations = check_zindex_chaos(td)

    assert violations == []


def test_check_zindex_chaos_high_value():
    """z-index 值 > 100（如 9999）应报 warning（典型 AI 堆叠军备竞赛）。"""
    import tempfile
    import os
    from driving.design_context import check_zindex_chaos

    html = """<html><head><meta name="viewport" content="width=device-width">
    <style>
    .modal { z-index: 9999; }
    .overlay { z-index: 999; }
    </style></head>
    <body><main><section>content</section></main></body></html>"""

    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        violations = check_zindex_chaos(td)

    zindex_violations = [v for v in violations if v["rule"] == "zindex_chaos"]
    assert len(zindex_violations) >= 1, f"z-index 9999 应报违规: {violations}"
    assert zindex_violations[0]["severity"] == "warning"


def test_check_zindex_chaos_clean():
    """z-index 0/10/20（≤5 个且都 ≤100）不应报违规。"""
    import tempfile
    import os
    from driving.design_context import check_zindex_chaos

    html = """<html><head><meta name="viewport" content="width=device-width">
    <style>
    .base { z-index: 0; }
    .dropdown { z-index: 10; }
    .modal { z-index: 20; }
    </style></head>
    <body><main><section>content</section></main></body></html>"""

    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        violations = check_zindex_chaos(td)

    zindex_violations = [v for v in violations if v["rule"] == "zindex_chaos"]
    assert zindex_violations == [], f"合理的 z-index 系统不应报违规: {zindex_violations}"


def test_check_zindex_chaos_too_many():
    """超过 5 个不同 z-index 值应报 warning（堆叠混乱）。"""
    import tempfile
    import os
    from driving.design_context import check_zindex_chaos

    html = """<html><head><meta name="viewport" content="width=device-width">
    <style>
    .a { z-index: 1; }
    .b { z-index: 2; }
    .c { z-index: 3; }
    .d { z-index: 4; }
    .e { z-index: 5; }
    .f { z-index: 6; }
    </style></head>
    <body><main><section>content</section></main></body></html>"""

    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        violations = check_zindex_chaos(td)

    zindex_violations = [v for v in violations if v["rule"] == "zindex_chaos"]
    assert len(zindex_violations) >= 1, f"6 个不同 z-index 值应报违规: {violations}"


def test_check_zindex_chaos_empty_dir():
    """空目录应返回空列表。"""
    import tempfile
    from driving.design_context import check_zindex_chaos

    with tempfile.TemporaryDirectory() as td:
        violations = check_zindex_chaos(td)

    assert violations == []


def test_lint_design_quality_includes_zindex():
    """lint_design_quality 应包含 zindex_chaos 规则。"""
    import tempfile
    import os
    from driving.design_context import lint_design_quality

    html = """<html><head><meta name="viewport" content="width=device-width">
    <style>
    .modal { z-index: 9999; }
    </style></head>
    <body><main><section>content</section></main></body></html>"""

    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        violations = lint_design_quality(td)

    zindex_violations = [v for v in violations if v["rule"] == "zindex_chaos"]
    assert len(zindex_violations) >= 1, f"lint 应包含 zindex_chaos: {violations}"


def test_auto_fix_zindex_normalizes():
    """z-index 9999/999/100/50/10 应被规范化为 0/10/20/30/40。"""
    import tempfile
    import os
    from driving.design_context import auto_fix_zindex, check_zindex_chaos

    html = """<html><head><meta name="viewport" content="width=device-width">
    <style>
    .a { z-index: 10; }
    .b { z-index: 50; }
    .c { z-index: 100; }
    .d { z-index: 999; }
    .e { z-index: 9999; }
    </style></head>
    <body><main><section>content</section></main></body></html>"""

    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        changed = auto_fix_zindex(td)
        content = open(os.path.join(td, "index.html"), "r").read()
        violations = check_zindex_chaos(td)

    assert changed is True, "应报告已修改"
    # 修复后不应有 z-index 违规
    zindex_violations = [v for v in violations if v["rule"] == "zindex_chaos"]
    assert zindex_violations == [], f"修复后不应有 z-index 违规: {zindex_violations}"
    # 应包含规范化后的值（0/10/20/30/40）
    assert "z-index: 40" in content, f"最高值应规范化为 40: {content}"
    assert "z-index: 0" in content, f"最低值应规范化为 0: {content}"
    assert "9999" not in content, f"不应再包含 9999: {content}"
    assert "999;" not in content, f"不应再包含 999: {content}"


def test_auto_fix_zindex_no_change_if_clean():
    """合理的 z-index 系统不应被修改。"""
    import tempfile
    import os
    from driving.design_context import auto_fix_zindex

    html = """<html><head><meta name="viewport" content="width=device-width">
    <style>
    .base { z-index: 0; }
    .dropdown { z-index: 10; }
    .modal { z-index: 20; }
    </style></head>
    <body><main><section>content</section></main></body></html>"""

    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        original = open(os.path.join(td, "index.html"), "r").read()
        changed = auto_fix_zindex(td)
        after = open(os.path.join(td, "index.html"), "r").read()

    assert changed is False, "合理 z-index 不应报告修改"
    assert original == after, "内容不应改变"


def test_auto_fix_zindex_empty_dir():
    """空目录应返回 False。"""
    import tempfile
    from driving.design_context import auto_fix_zindex

    with tempfile.TemporaryDirectory() as td:
        changed = auto_fix_zindex(td)

    assert changed is False


def test_auto_fix_zindex_idempotent():
    """两次 auto_fix 结果应一致（幂等性）。"""
    import tempfile
    import os
    from driving.design_context import auto_fix_zindex

    html = """<html><head><meta name="viewport" content="width=device-width">
    <style>
    .a { z-index: 9999; }
    .b { z-index: 500; }
    .c { z-index: 1; }
    </style></head>
    <body><main><section>content</section></main></body></html>"""

    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        auto_fix_zindex(td)
        first_run = open(os.path.join(td, "index.html"), "r").read()
        auto_fix_zindex(td)
        second_run = open(os.path.join(td, "index.html"), "r").read()

    assert first_run == second_run, f"幂等性失败:\n第一次:\n{first_run}\n第二次:\n{second_run}"


def test_auto_fix_design_issues_includes_zindex():
    """auto_fix_design_issues 组合函数应包含 z-index 修复。"""
    import tempfile
    import os
    from driving.design_context import auto_fix_design_issues, check_zindex_chaos

    html = """<html><head><meta name="viewport" content="width=device-width">
    <style>
    .modal { z-index: 9999; }
    .overlay { z-index: 500; }
    </style></head>
    <body><main><section>content</section></main></body></html>"""

    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        auto_fix_design_issues(td)
        violations = check_zindex_chaos(td)

    zindex_violations = [v for v in violations if v["rule"] == "zindex_chaos"]
    assert zindex_violations == [], f"组合修复后不应有 z-index 违规: {zindex_violations}"


# ---------- M70: border-radius 一致性检测 + auto-fix ----------


def test_check_border_radius_chaos_no_html():
    """无 HTML 文件时应返回空列表。"""
    import tempfile
    from driving.design_context import check_border_radius_chaos

    with tempfile.TemporaryDirectory() as td:
        violations = check_border_radius_chaos(td)

    assert violations == []


def test_check_border_radius_chaos_non_standard():
    """非标准 border-radius 值（如 7px/13px）应报 warning。"""
    import tempfile
    import os
    from driving.design_context import check_border_radius_chaos

    html = """<html><head><meta name="viewport" content="width=device-width">
    <style>
    .a { border-radius: 7px; }
    .b { border-radius: 13px; }
    </style></head>
    <body><main><section>content</section></main></body></html>"""

    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        violations = check_border_radius_chaos(td)

    radius_violations = [v for v in violations if v["rule"] == "border_radius_chaos"]
    assert len(radius_violations) >= 1, f"非标准值应报违规: {violations}"


def test_check_border_radius_chaos_clean():
    """标准 border-radius 值（0/4/8/12/16px）不应报违规。"""
    import tempfile
    import os
    from driving.design_context import check_border_radius_chaos

    html = """<html><head><meta name="viewport" content="width=device-width">
    <style>
    .a { border-radius: 0; }
    .b { border-radius: 4px; }
    .c { border-radius: 8px; }
    .d { border-radius: 12px; }
    .e { border-radius: 16px; }
    </style></head>
    <body><main><section>content</section></main></body></html>"""

    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        violations = check_border_radius_chaos(td)

    radius_violations = [v for v in violations if v["rule"] == "border_radius_chaos"]
    assert radius_violations == [], f"标准值不应报违规: {radius_violations}"


def test_check_border_radius_chaos_too_many():
    """超过 6 个不同 border-radius 值应报 warning。"""
    import tempfile
    import os
    from driving.design_context import check_border_radius_chaos

    html = """<html><head><meta name="viewport" content="width=device-width">
    <style>
    .a { border-radius: 2px; }
    .b { border-radius: 4px; }
    .c { border-radius: 6px; }
    .d { border-radius: 8px; }
    .e { border-radius: 12px; }
    .f { border-radius: 16px; }
    .g { border-radius: 24px; }
    </style></head>
    <body><main><section>content</section></main></body></html>"""

    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        violations = check_border_radius_chaos(td)

    radius_violations = [v for v in violations if v["rule"] == "border_radius_chaos"]
    assert len(radius_violations) >= 1, f"7 个不同值应报违规: {violations}"


def test_check_border_radius_chaos_empty_dir():
    """空目录应返回空列表。"""
    import tempfile
    from driving.design_context import check_border_radius_chaos

    with tempfile.TemporaryDirectory() as td:
        violations = check_border_radius_chaos(td)

    assert violations == []


def test_lint_design_quality_includes_border_radius():
    """lint_design_quality 应包含 border_radius_chaos 规则。"""
    import tempfile
    import os
    from driving.design_context import lint_design_quality

    html = """<html><head><meta name="viewport" content="width=device-width">
    <style>
    .a { border-radius: 7px; }
    </style></head>
    <body><main><section>content</section></main></body></html>"""

    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        violations = lint_design_quality(td)

    radius_violations = [v for v in violations if v["rule"] == "border_radius_chaos"]
    assert len(radius_violations) >= 1, f"lint 应包含 border_radius_chaos: {violations}"


def test_auto_fix_border_radius_normalizes():
    """非标准 border-radius 值应被规范化为最近标准值。"""
    import tempfile
    import os
    from driving.design_context import auto_fix_border_radius, check_border_radius_chaos

    html = """<html><head><meta name="viewport" content="width=device-width">
    <style>
    .a { border-radius: 7px; }
    .b { border-radius: 13px; }
    .c { border-radius: 25px; }
    </style></head>
    <body><main><section>content</section></main></body></html>"""

    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        changed = auto_fix_border_radius(td)
        content = open(os.path.join(td, "index.html"), "r").read()
        violations = check_border_radius_chaos(td)

    assert changed is True, "应报告已修改"
    radius_violations = [v for v in violations if v["rule"] == "border_radius_chaos"]
    assert radius_violations == [], f"修复后不应有违规: {radius_violations}"
    # 7→8, 13→12, 25→24
    assert "8px" in content, f"7应规范化为8: {content}"
    assert "12px" in content, f"13应规范化为12: {content}"
    assert "24px" in content, f"25应规范化为24: {content}"


def test_auto_fix_border_radius_no_change_if_clean():
    """标准的 border-radius 不应被修改。"""
    import tempfile
    import os
    from driving.design_context import auto_fix_border_radius

    html = """<html><head><meta name="viewport" content="width=device-width">
    <style>
    .a { border-radius: 4px; }
    .b { border-radius: 8px; }
    </style></head>
    <body><main><section>content</section></main></body></html>"""

    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        original = open(os.path.join(td, "index.html"), "r").read()
        changed = auto_fix_border_radius(td)
        after = open(os.path.join(td, "index.html"), "r").read()

    assert changed is False, "标准值不应报告修改"
    assert original == after, "内容不应改变"


def test_auto_fix_border_radius_empty_dir():
    """空目录应返回 False。"""
    import tempfile
    from driving.design_context import auto_fix_border_radius

    with tempfile.TemporaryDirectory() as td:
        changed = auto_fix_border_radius(td)

    assert changed is False


def test_auto_fix_border_radius_idempotent():
    """两次 auto_fix 结果应一致（幂等性）。"""
    import tempfile
    import os
    from driving.design_context import auto_fix_border_radius

    html = """<html><head><meta name="viewport" content="width=device-width">
    <style>
    .a { border-radius: 7px; }
    .b { border-radius: 13px; }
    </style></head>
    <body><main><section>content</section></main></body></html>"""

    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        auto_fix_border_radius(td)
        first_run = open(os.path.join(td, "index.html"), "r").read()
        auto_fix_border_radius(td)
        second_run = open(os.path.join(td, "index.html"), "r").read()

    assert first_run == second_run, f"幂等性失败:\n第一次:\n{first_run}\n第二次:\n{second_run}"


def test_auto_fix_design_issues_includes_border_radius():
    """auto_fix_design_issues 组合函数应包含 border-radius 修复。"""
    import tempfile
    import os
    from driving.design_context import auto_fix_design_issues, check_border_radius_chaos

    html = """<html><head><meta name="viewport" content="width=device-width">
    <style>
    .a { border-radius: 7px; }
    .b { border-radius: 13px; }
    </style></head>
    <body><main><section>content</section></main></body></html>"""

    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        auto_fix_design_issues(td)
        violations = check_border_radius_chaos(td)

    radius_violations = [v for v in violations if v["rule"] == "border_radius_chaos"]
    assert radius_violations == [], f"组合修复后不应有违规: {radius_violations}"


# ======================== M71: box-shadow elevation 混乱检测 + auto-fix ========================


def test_check_box_shadow_chaos_no_html():
    """无 HTML 文件的目录返回空列表。"""
    import tempfile
    from driving.design_context import check_box_shadow_chaos
    with tempfile.TemporaryDirectory() as td:
        assert check_box_shadow_chaos(td) == []


def test_check_box_shadow_chaos_non_standard():
    """非标准 box-shadow blur 值应报 warning。"""
    import tempfile
    import os
    from driving.design_context import check_box_shadow_chaos
    html = """<html><head><style>
    .a { box-shadow: 0 3px 7px rgba(0,0,0,0.1); }
    .b { box-shadow: 0 13px 29px rgba(0,0,0,0.2); }
    </style></head><body><main><section>x</section></main></body></html>"""
    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        violations = check_box_shadow_chaos(td)
    shadow_v = [v for v in violations if v["rule"] == "box_shadow_chaos"]
    assert len(shadow_v) >= 1
    assert shadow_v[0]["severity"] == "warning"


def test_check_box_shadow_chaos_clean():
    """标准 elevation 值不报违规。"""
    import tempfile
    import os
    from driving.design_context import check_box_shadow_chaos
    html = """<html><head><style>
    .a { box-shadow: 0 1px 2px rgba(0,0,0,0.05); }
    .b { box-shadow: 0 4px 6px rgba(0,0,0,0.07); }
    .c { box-shadow: 0 10px 15px rgba(0,0,0,0.1); }
    </style></head><body><main><section>x</section></main></body></html>"""
    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        violations = check_box_shadow_chaos(td)
    shadow_v = [v for v in violations if v["rule"] == "box_shadow_chaos"]
    assert shadow_v == [], f"标准值不应报违规: {shadow_v}"


def test_check_box_shadow_chaos_too_many():
    """超过 4 个不同 box-shadow 值报 warning。"""
    import tempfile
    import os
    from driving.design_context import check_box_shadow_chaos
    html = """<html><head><style>
    .a { box-shadow: 0 1px 2px rgba(0,0,0,0.05); }
    .b { box-shadow: 0 2px 4px rgba(0,0,0,0.05); }
    .c { box-shadow: 0 4px 6px rgba(0,0,0,0.07); }
    .d { box-shadow: 0 6px 8px rgba(0,0,0,0.08); }
    .e { box-shadow: 0 10px 15px rgba(0,0,0,0.1); }
    </style></head><body><main><section>x</section></main></body></html>"""
    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        violations = check_box_shadow_chaos(td)
    shadow_v = [v for v in violations if v["rule"] == "box_shadow_chaos"]
    assert len(shadow_v) >= 1


def test_check_box_shadow_chaos_empty_dir():
    """空目录返回空列表。"""
    import tempfile
    from driving.design_context import check_box_shadow_chaos
    with tempfile.TemporaryDirectory() as td:
        assert check_box_shadow_chaos(td) == []


def test_lint_design_quality_includes_box_shadow():
    """lint_design_quality 应包含 box-shadow 检查。"""
    import tempfile
    import os
    from driving.design_context import lint_design_quality
    html = """<html><head><style>
    .a { box-shadow: 0 3px 7px rgba(0,0,0,0.1); }
    </style></head><body><main><section>x</section></main></body></html>"""
    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        violations = lint_design_quality(td)
    shadow_v = [v for v in violations if v["rule"] == "box_shadow_chaos"]
    assert len(shadow_v) >= 1, f"lint 应检测到 box-shadow 违规: {violations}"


def test_auto_fix_box_shadow_normalizes():
    """非标准 box-shadow 应规范化到最近标准 elevation。"""
    import tempfile
    import os
    from driving.design_context import auto_fix_box_shadow, check_box_shadow_chaos
    html = """<html><head><meta name="viewport" content="width=device-width">
    <style>
    .a { box-shadow: 0 3px 7px rgba(0,0,0,0.1); }
    .b { box-shadow: 0 13px 29px rgba(0,0,0,0.2); }
    </style></head>
    <body><main><section>content</section></main></body></html>"""
    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        changed = auto_fix_box_shadow(td)
        content = open(os.path.join(td, "index.html"), "r").read()
        violations = check_box_shadow_chaos(td)
    assert changed is True, "应报告已修改"
    shadow_v = [v for v in violations if v["rule"] == "box_shadow_chaos"]
    assert shadow_v == [], f"修复后不应有违规: {shadow_v}"
    # 7px blur → 6px (md), 29px blur → 25px (xl-ish)
    assert "6px" in content or "15px" in content or "25px" in content, f"应有标准值: {content}"


def test_auto_fix_box_shadow_no_change_if_clean():
    """标准 box-shadow 不修改。"""
    import tempfile
    import os
    from driving.design_context import auto_fix_box_shadow
    html = """<html><head><style>
    .a { box-shadow: 0 1px 2px rgba(0,0,0,0.05); }
    .b { box-shadow: 0 4px 6px rgba(0,0,0,0.07); }
    </style></head><body><main><section>x</section></main></body></html>"""
    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        changed = auto_fix_box_shadow(td)
    assert changed is False, "标准值不应修改"


def test_auto_fix_box_shadow_empty_dir():
    """空目录返回 False。"""
    import tempfile
    from driving.design_context import auto_fix_box_shadow
    with tempfile.TemporaryDirectory() as td:
        assert auto_fix_box_shadow(td) is False


def test_auto_fix_box_shadow_idempotent():
    """二次运行不修改。"""
    import tempfile
    import os
    from driving.design_context import auto_fix_box_shadow
    html = """<html><head><style>
    .a { box-shadow: 0 3px 7px rgba(0,0,0,0.1); }
    .b { box-shadow: 0 13px 29px rgba(0,0,0,0.2); }
    </style></head><body><main><section>x</section></main></body></html>"""
    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        auto_fix_box_shadow(td)
        changed2 = auto_fix_box_shadow(td)
    assert changed2 is False, "二次运行不应修改"


def test_auto_fix_design_issues_includes_box_shadow():
    """auto_fix_design_issues 组合函数应包含 box-shadow 修复。"""
    import tempfile
    import os
    from driving.design_context import auto_fix_design_issues, check_box_shadow_chaos
    html = """<html><head><meta name="viewport" content="width=device-width">
    <style>
    .a { box-shadow: 0 3px 7px rgba(0,0,0,0.1); }
    .b { box-shadow: 0 13px 29px rgba(0,0,0,0.2); }
    </style></head>
    <body><main><section>content</section></main></body></html>"""
    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        auto_fix_design_issues(td)
        violations = check_box_shadow_chaos(td)
    shadow_v = [v for v in violations if v["rule"] == "box_shadow_chaos"]
    assert shadow_v == [], f"组合修复后不应有违规: {shadow_v}"


# ======================== M72: transition duration 一致性检测 + auto-fix ========================


def test_check_transition_chaos_no_html():
    """无 HTML 文件的目录返回空列表。"""
    import tempfile
    from driving.design_context import check_transition_chaos
    with tempfile.TemporaryDirectory() as td:
        assert check_transition_chaos(td) == []


def test_check_transition_chaos_non_standard():
    """非标准 transition duration 应报 warning。"""
    import tempfile
    import os
    from driving.design_context import check_transition_chaos
    html = """<html><head><style>
    .a { transition: opacity 0.25s ease; }
    .b { transition: transform 0.35s ease; }
    </style></head><body><main><section>x</section></main></body></html>"""
    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        violations = check_transition_chaos(td)
    t_v = [v for v in violations if v["rule"] == "transition_chaos"]
    assert len(t_v) >= 1
    assert t_v[0]["severity"] == "warning"


def test_check_transition_chaos_clean():
    """标准 duration 不报违规。"""
    import tempfile
    import os
    from driving.design_context import check_transition_chaos
    html = """<html><head><style>
    .a { transition: opacity 0.15s ease-out; }
    .b { transition: transform 0.2s ease-out; }
    .c { transition: all 0.3s ease-out; }
    </style></head><body><main><section>x</section></main></body></html>"""
    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        violations = check_transition_chaos(td)
    t_v = [v for v in violations if v["rule"] == "transition_chaos"]
    assert t_v == [], f"标准值不应报违规: {t_v}"


def test_check_transition_chaos_ms_units():
    """支持 ms 单位的 duration。"""
    import tempfile
    import os
    from driving.design_context import check_transition_chaos
    html = """<html><head><style>
    .a { transition: opacity 150ms ease-out; }
    .b { transition: transform 200ms ease-out; }
    </style></head><body><main><section>x</section></main></body></html>"""
    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        violations = check_transition_chaos(td)
    t_v = [v for v in violations if v["rule"] == "transition_chaos"]
    assert t_v == [], f"标准 ms 值不应报违规: {t_v}"


def test_check_transition_chaos_empty_dir():
    """空目录返回空列表。"""
    import tempfile
    from driving.design_context import check_transition_chaos
    with tempfile.TemporaryDirectory() as td:
        assert check_transition_chaos(td) == []


def test_lint_design_quality_includes_transition():
    """lint_design_quality 应包含 transition 检查。"""
    import tempfile
    import os
    from driving.design_context import lint_design_quality
    html = """<html><head><style>
    .a { transition: opacity 0.25s ease; }
    </style></head><body><main><section>x</section></main></body></html>"""
    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        violations = lint_design_quality(td)
    t_v = [v for v in violations if v["rule"] == "transition_chaos"]
    assert len(t_v) >= 1, f"lint 应检测到 transition 违规: {violations}"


def test_auto_fix_transition_normalizes():
    """非标准 duration 应规范化到最近标准值。"""
    import tempfile
    import os
    from driving.design_context import auto_fix_transition, check_transition_chaos
    html = """<html><head><meta name="viewport" content="width=device-width">
    <style>
    .a { transition: opacity 0.25s ease; }
    .b { transition: transform 0.35s ease; }
    </style></head>
    <body><main><section>content</section></main></body></html>"""
    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        changed = auto_fix_transition(td)
        content = open(os.path.join(td, "index.html"), "r").read()
        violations = check_transition_chaos(td)
    assert changed is True, "应报告已修改"
    t_v = [v for v in violations if v["rule"] == "transition_chaos"]
    assert t_v == [], f"修复后不应有违规: {t_v}"
    # 0.25s → 0.2s or 0.3s, 0.35s → 0.3s
    assert "0.2s" in content or "0.3s" in content, f"应有标准值: {content}"


def test_auto_fix_transition_no_change_if_clean():
    """标准 duration 不修改。"""
    import tempfile
    import os
    from driving.design_context import auto_fix_transition
    html = """<html><head><style>
    .a { transition: opacity 0.15s ease-out; }
    .b { transition: transform 0.3s ease-out; }
    </style></head><body><main><section>x</section></main></body></html>"""
    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        changed = auto_fix_transition(td)
    assert changed is False, "标准值不应修改"


def test_auto_fix_transition_chaos_empty_dir():
    """空目录返回 False。"""
    import tempfile
    from driving.design_context import auto_fix_transition
    with tempfile.TemporaryDirectory() as td:
        assert auto_fix_transition(td) is False


def test_auto_fix_transition_idempotent():
    """二次运行不修改。"""
    import tempfile
    import os
    from driving.design_context import auto_fix_transition
    html = """<html><head><style>
    .a { transition: opacity 0.25s ease; }
    .b { transition: transform 0.35s ease; }
    </style></head><body><main><section>x</section></main></body></html>"""
    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        auto_fix_transition(td)
        changed2 = auto_fix_transition(td)
    assert changed2 is False, "二次运行不应修改"


def test_auto_fix_design_issues_includes_transition():
    """auto_fix_design_issues 组合函数应包含 transition 修复。"""
    import tempfile
    import os
    from driving.design_context import auto_fix_design_issues, check_transition_chaos
    html = """<html><head><meta name="viewport" content="width=device-width">
    <style>
    .a { transition: opacity 0.25s ease; }
    .b { transition: transform 0.35s ease; }
    </style></head>
    <body><main><section>content</section></main></body></html>"""
    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        auto_fix_design_issues(td)
        violations = check_transition_chaos(td)
    t_v = [v for v in violations if v["rule"] == "transition_chaos"]
    assert t_v == [], f"组合修复后不应有违规: {t_v}"


# ======================== M73: opacity 一致性检测 + auto-fix ========================


def test_check_opacity_chaos_no_html():
    """无 HTML 文件的目录返回空列表。"""
    import tempfile
    from driving.design_context import check_opacity_chaos
    with tempfile.TemporaryDirectory() as td:
        assert check_opacity_chaos(td) == []


def test_check_opacity_chaos_non_standard():
    """非标准 opacity 值应报 warning。"""
    import tempfile
    import os
    from driving.design_context import check_opacity_chaos
    html = """<html><head><style>
    .a { opacity: 0.3; }
    .b { opacity: 0.85; }
    </style></head><body><main><section>x</section></main></body></html>"""
    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        violations = check_opacity_chaos(td)
    o_v = [v for v in violations if v["rule"] == "opacity_chaos"]
    assert len(o_v) >= 1
    assert o_v[0]["severity"] == "warning"


def test_check_opacity_chaos_clean():
    """标准 opacity 值不报违规。"""
    import tempfile
    import os
    from driving.design_context import check_opacity_chaos
    html = """<html><head><style>
    .a { opacity: 0; }
    .b { opacity: 0.25; }
    .c { opacity: 0.5; }
    .d { opacity: 0.75; }
    .e { opacity: 1; }
    </style></head><body><main><section>x</section></main></body></html>"""
    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        violations = check_opacity_chaos(td)
    o_v = [v for v in violations if v["rule"] == "opacity_chaos"]
    assert o_v == [], f"标准值不应报违规: {o_v}"


def test_check_opacity_chaos_empty_dir():
    """空目录返回空列表。"""
    import tempfile
    from driving.design_context import check_opacity_chaos
    with tempfile.TemporaryDirectory() as td:
        assert check_opacity_chaos(td) == []


def test_lint_design_quality_includes_opacity():
    """lint_design_quality 应包含 opacity 检查。"""
    import tempfile
    import os
    from driving.design_context import lint_design_quality
    html = """<html><head><style>
    .a { opacity: 0.3; }
    </style></head><body><main><section>x</section></main></body></html>"""
    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        violations = lint_design_quality(td)
    o_v = [v for v in violations if v["rule"] == "opacity_chaos"]
    assert len(o_v) >= 1, f"lint 应检测到 opacity 违规: {violations}"


def test_auto_fix_opacity_normalizes():
    """非标准 opacity 应规范化到最近标准值。"""
    import tempfile
    import os
    from driving.design_context import auto_fix_opacity, check_opacity_chaos
    html = """<html><head><meta name="viewport" content="width=device-width">
    <style>
    .a { opacity: 0.3; }
    .b { opacity: 0.85; }
    </style></head>
    <body><main><section>content</section></main></body></html>"""
    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        changed = auto_fix_opacity(td)
        content = open(os.path.join(td, "index.html"), "r").read()
        violations = check_opacity_chaos(td)
    assert changed is True, "应报告已修改"
    o_v = [v for v in violations if v["rule"] == "opacity_chaos"]
    assert o_v == [], f"修复后不应有违规: {o_v}"
    # 0.3 → 0.25, 0.85 → 0.75
    assert "0.25" in content or "0.75" in content, f"应有标准值: {content}"


def test_auto_fix_opacity_no_change_if_clean():
    """标准 opacity 不修改。"""
    import tempfile
    import os
    from driving.design_context import auto_fix_opacity
    html = """<html><head><style>
    .a { opacity: 0.5; }
    .b { opacity: 1; }
    </style></head><body><main><section>x</section></main></body></html>"""
    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        changed = auto_fix_opacity(td)
    assert changed is False, "标准值不应修改"


def test_auto_fix_opacity_empty_dir():
    """空目录返回 False。"""
    import tempfile
    from driving.design_context import auto_fix_opacity
    with tempfile.TemporaryDirectory() as td:
        assert auto_fix_opacity(td) is False


def test_auto_fix_opacity_idempotent():
    """二次运行不修改。"""
    import tempfile
    import os
    from driving.design_context import auto_fix_opacity
    html = """<html><head><style>
    .a { opacity: 0.3; }
    .b { opacity: 0.85; }
    </style></head><body><main><section>x</section></main></body></html>"""
    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        auto_fix_opacity(td)
        changed2 = auto_fix_opacity(td)
    assert changed2 is False, "二次运行不应修改"


def test_auto_fix_design_issues_includes_opacity():
    """auto_fix_design_issues 组合函数应包含 opacity 修复。"""
    import tempfile
    import os
    from driving.design_context import auto_fix_design_issues, check_opacity_chaos
    html = """<html><head><meta name="viewport" content="width=device-width">
    <style>
    .a { opacity: 0.3; }
    .b { opacity: 0.85; }
    </style></head>
    <body><main><section>content</section></main></body></html>"""
    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        auto_fix_design_issues(td)
        violations = check_opacity_chaos(td)
    o_v = [v for v in violations if v["rule"] == "opacity_chaos"]
    assert o_v == [], f"组合修复后不应有违规: {o_v}"


# ---------- M74: font-size 一致性检测 + auto-fix ----------


def test_check_font_size_chaos_no_html():
    """没有 HTML 文件时应返回空列表。"""
    import tempfile
    import os
    from driving.design_context import check_font_size_chaos
    with tempfile.TemporaryDirectory() as td:
        result = check_font_size_chaos(td)
    assert result == []


def test_check_font_size_chaos_non_standard():
    """非标准 font-size 值应报 warning。"""
    import tempfile
    import os
    from driving.design_context import check_font_size_chaos
    html = """<html><head><style>
    .a { font-size: 13px; }
    .b { font-size: 17px; }
    .c { font-size: 23px; }
    </style></head><body>text</body></html>"""
    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        violations = check_font_size_chaos(td)
    fs_v = [v for v in violations if v["rule"] == "font_size_chaos"]
    assert len(fs_v) > 0
    assert fs_v[0]["severity"] == "warning"


def test_check_font_size_chaos_clean():
    """标准 font-size 值不应报违规。"""
    import tempfile
    import os
    from driving.design_context import check_font_size_chaos
    html = """<html><head><style>
    .a { font-size: 12px; }
    .b { font-size: 14px; }
    .c { font-size: 16px; }
    .d { font-size: 18px; }
    .e { font-size: 24px; }
    .f { font-size: 36px; }
    .g { font-size: 48px; }
    </style></head><body>text</body></html>"""
    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        violations = check_font_size_chaos(td)
    fs_v = [v for v in violations if v["rule"] == "font_size_chaos"]
    assert fs_v == []


def test_check_font_size_chaos_too_many_distinct():
    """超过 8 个不同 font-size 值应报 warning。"""
    import tempfile
    import os
    from driving.design_context import check_font_size_chaos
    html = """<html><head><style>
    .a { font-size: 12px; }
    .b { font-size: 14px; }
    .c { font-size: 16px; }
    .d { font-size: 18px; }
    .e { font-size: 24px; }
    .f { font-size: 30px; }
    .g { font-size: 36px; }
    .h { font-size: 48px; }
    .i { font-size: 64px; }
    </style></head><body>text</body></html>"""
    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        violations = check_font_size_chaos(td)
    fs_v = [v for v in violations if v["rule"] == "font_size_chaos"]
    assert len(fs_v) > 0
    assert "9" in fs_v[0]["message"] or "不同" in fs_v[0]["message"]


def test_check_font_size_chaos_empty_dir():
    """空目录应返回空列表。"""
    import tempfile
    from driving.design_context import check_font_size_chaos
    with tempfile.TemporaryDirectory() as td:
        result = check_font_size_chaos(td)
    assert result == []


def test_lint_design_quality_includes_font_size():
    """lint_design_quality 应包含 font_size_chaos 检测。"""
    import tempfile
    import os
    from driving.design_context import lint_design_quality
    html = """<html><head><style>
    .a { font-size: 13px; }
    </style></head><body>text</body></html>"""
    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        violations = lint_design_quality(td)
    fs_v = [v for v in violations if v["rule"] == "font_size_chaos"]
    assert len(fs_v) > 0


def test_auto_fix_font_size_normalizes():
    """auto_fix_font_size 应将非标准值映射到最近标准值。"""
    import tempfile
    import os
    from driving.design_context import auto_fix_font_size
    html = """<html><head><style>
    .a { font-size: 13px; }
    .b { font-size: 17px; }
    .c { font-size: 23px; }
    </style></head><body>text</body></html>"""
    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        changed = auto_fix_font_size(td)
        assert changed is True
        with open(os.path.join(td, "index.html"), "r") as f:
            content = f.read()
    # 13 -> 14 (距离1, 12和14等距, 取较大值14)
    assert "14px" in content
    # 17 -> 18 (距离1, 16和18等距, 取较大值18)
    assert "18px" in content
    # 23 -> 24 (距离1, 18和24不等距, 24最近)
    assert "24px" in content
    # 原始值不应残留
    assert "13px" not in content
    assert "17px" not in content
    assert "23px" not in content


def test_auto_fix_font_size_no_change_if_clean():
    """已经是标准值时不应修改文件。"""
    import tempfile
    import os
    from driving.design_context import auto_fix_font_size
    html = """<html><head><style>
    .a { font-size: 16px; }
    .b { font-size: 24px; }
    </style></head><body>text</body></html>"""
    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        changed = auto_fix_font_size(td)
        assert changed is False


def test_auto_fix_font_size_empty_dir():
    """空目录应返回 False。"""
    import tempfile
    from driving.design_context import auto_fix_font_size
    with tempfile.TemporaryDirectory() as td:
        changed = auto_fix_font_size(td)
    assert changed is False


def test_auto_fix_font_size_idempotent():
    """多次调用 auto_fix_font_size 应幂等。"""
    import tempfile
    import os
    from driving.design_context import auto_fix_font_size
    html = """<html><head><style>
    .a { font-size: 13px; }
    .b { font-size: 37px; }
    </style></head><body>text</body></html>"""
    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        auto_fix_font_size(td)
        changed2 = auto_fix_font_size(td)
        assert changed2 is False


def test_auto_fix_design_issues_includes_font_size():
    """auto_fix_design_issues 组合函数应包含 font-size 修复。"""
    import tempfile
    import os
    from driving.design_context import auto_fix_design_issues, check_font_size_chaos
    html = """<html><head><meta name="viewport" content="width=device-width">
    <style>
    .a { font-size: 13px; }
    .b { font-size: 23px; }
    </style></head>
    <body><main><section>content</section></main></body></html>"""
    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        auto_fix_design_issues(td)
        violations = check_font_size_chaos(td)
    fs_v = [v for v in violations if v["rule"] == "font_size_chaos"]
    assert fs_v == [], f"组合修复后不应有违规: {fs_v}"


# ---------- M75: line-height 一致性检测 + auto-fix ----------


def test_check_line_height_chaos_no_html():
    """没有 HTML 文件时应返回空列表。"""
    import tempfile
    from driving.design_context import check_line_height_chaos
    with tempfile.TemporaryDirectory() as td:
        result = check_line_height_chaos(td)
    assert result == []


def test_check_line_height_chaos_non_standard():
    """非标准 line-height 值应报 warning。"""
    import tempfile
    import os
    from driving.design_context import check_line_height_chaos
    html = """<html><head><style>
    .a { line-height: 1.3; }
    .b { line-height: 1.45; }
    .c { line-height: 1.67; }
    </style></head><body>text</body></html>"""
    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        violations = check_line_height_chaos(td)
    lh_v = [v for v in violations if v["rule"] == "line_height_chaos"]
    assert len(lh_v) > 0
    assert lh_v[0]["severity"] == "warning"


def test_check_line_height_chaos_clean():
    """标准 line-height 值不应报违规。"""
    import tempfile
    import os
    from driving.design_context import check_line_height_chaos
    html = """<html><head><style>
    .a { line-height: 1; }
    .b { line-height: 1.25; }
    .c { line-height: 1.5; }
    .d { line-height: 1.75; }
    .e { line-height: 2; }
    </style></head><body>text</body></html>"""
    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        violations = check_line_height_chaos(td)
    lh_v = [v for v in violations if v["rule"] == "line_height_chaos"]
    assert lh_v == []


def test_check_line_height_chaos_too_many_distinct():
    """超过 5 个不同 line-height 值应报 warning。"""
    import tempfile
    import os
    from driving.design_context import check_line_height_chaos
    html = """<html><head><style>
    .a { line-height: 1; }
    .b { line-height: 1.25; }
    .c { line-height: 1.5; }
    .d { line-height: 1.75; }
    .e { line-height: 2; }
    .f { line-height: 2.5; }
    </style></head><body>text</body></html>"""
    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        violations = check_line_height_chaos(td)
    lh_v = [v for v in violations if v["rule"] == "line_height_chaos"]
    assert len(lh_v) > 0
    assert "6" in lh_v[-1]["message"] or "不同" in lh_v[-1]["message"]


def test_check_line_height_chaos_empty_dir():
    """空目录应返回空列表。"""
    import tempfile
    from driving.design_context import check_line_height_chaos
    with tempfile.TemporaryDirectory() as td:
        result = check_line_height_chaos(td)
    assert result == []


def test_lint_design_quality_includes_line_height():
    """lint_design_quality 应包含 line_height_chaos 检测。"""
    import tempfile
    import os
    from driving.design_context import lint_design_quality
    html = """<html><head><style>
    .a { line-height: 1.3; }
    </style></head><body>text</body></html>"""
    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        violations = lint_design_quality(td)
    lh_v = [v for v in violations if v["rule"] == "line_height_chaos"]
    assert len(lh_v) > 0


def test_auto_fix_line_height_normalizes():
    """auto_fix_line_height 应将非标准值映射到最近标准值。"""
    import tempfile
    import os
    from driving.design_context import auto_fix_line_height
    html = """<html><head><style>
    .a { line-height: 1.3; }
    .b { line-height: 1.45; }
    .c { line-height: 1.67; }
    </style></head><body>text</body></html>"""
    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        changed = auto_fix_line_height(td)
        assert changed is True
        with open(os.path.join(td, "index.html"), "r") as f:
            content = f.read()
    # 1.3 -> 1.25 (距离 0.05, 1.25 和 1.5 等距 0.2, 取较小值 1.25? 不对)
    # 1.3: |1.3-1|=0.3, |1.3-1.25|=0.05, |1.3-1.5|=0.2 -> 1.25
    assert "1.25" in content
    # 1.45: |1.45-1.25|=0.2, |1.45-1.5|=0.05, |1.45-1.75|=0.3 -> 1.5
    assert "1.5" in content
    # 1.67: |1.67-1.5|=0.17, |1.67-1.75|=0.08, |1.67-2|=0.33 -> 1.75
    assert "1.75" in content
    # 原始值不应残留
    assert "1.3;" not in content
    assert "1.45" not in content
    assert "1.67" not in content


def test_auto_fix_line_height_no_change_if_clean():
    """已经是标准值时不应修改文件。"""
    import tempfile
    import os
    from driving.design_context import auto_fix_line_height
    html = """<html><head><style>
    .a { line-height: 1.5; }
    .b { line-height: 2; }
    </style></head><body>text</body></html>"""
    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        changed = auto_fix_line_height(td)
        assert changed is False


def test_auto_fix_line_height_empty_dir():
    """空目录应返回 False。"""
    import tempfile
    from driving.design_context import auto_fix_line_height
    with tempfile.TemporaryDirectory() as td:
        changed = auto_fix_line_height(td)
    assert changed is False


def test_auto_fix_line_height_idempotent():
    """多次调用 auto_fix_line_height 应幂等。"""
    import tempfile
    import os
    from driving.design_context import auto_fix_line_height
    html = """<html><head><style>
    .a { line-height: 1.3; }
    .b { line-height: 1.9; }
    </style></head><body>text</body></html>"""
    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        auto_fix_line_height(td)
        changed2 = auto_fix_line_height(td)
        assert changed2 is False


def test_auto_fix_design_issues_includes_line_height():
    """auto_fix_design_issues 组合函数应包含 line-height 修复。"""
    import tempfile
    import os
    from driving.design_context import auto_fix_design_issues, check_line_height_chaos
    html = """<html><head><meta name="viewport" content="width=device-width">
    <style>
    .a { line-height: 1.3; }
    .b { line-height: 1.67; }
    </style></head>
    <body><main><section>content</section></main></body></html>"""
    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(html)
        auto_fix_design_issues(td)
        violations = check_line_height_chaos(td)
    lh_v = [v for v in violations if v["rule"] == "line_height_chaos"]
    assert lh_v == [], f"组合修复后不应有违规: {lh_v}"
