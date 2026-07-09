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


def test_list_styles_has_ten():
    from driving.design_context import list_styles
    styles = list_styles()
    assert len(styles) == 10
    for s in ("minimalism", "dark", "glassmorphism", "bento", "cyberpunk"):
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
