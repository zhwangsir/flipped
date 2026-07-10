"""设计系统注入（M10.1）。

把 AI-Design-System-Prompt.md 的设计准则注入到 worker 上下文，
让生成的 UI 代码遵循设计系统，达到产品级 UI/UX 质量。

注入点：factory_loop 的 default_orchestrator_fn 把 design_brief 加到 project_rules，
worker（Kimi）执行任务时就能看到设计约束，生成的代码自带设计系统规范。
"""
from __future__ import annotations

from pathlib import Path

_DESIGN_DOC_CACHE: str | None = None

# 10 种风格精简数据（从 AI-Design-System-Prompt.md 提炼，含具体 hex 值）
STYLE_BRIEFS: dict[str, dict] = {
    "minimalism": {
        "name": "极简主义 Minimalism",
        "colors": {"accent": "#0071E3", "bg": "#FFFFFF", "bg_alt": "#FAFAFA", "text": "#1D1D1F", "text_muted": "#86868B"},
        "font": "Inter / SF Pro Display",
        "headings": "72px / 800 / 1.1 / -0.02em",
        "body": "17px / 300 / 1.6",
        "refs": "Apple, Linear, Notion",
        "principles": "whitespace-driven, single accent for CTAs only, no shadows/borders, 100-200px section gaps, content-first",
    },
    "dark": {
        "name": "暗黑模式 Dark Mode",
        "colors": {"accent": "#0A84FF", "bg": "#0D0D12", "bg_alt": "#1A1A2E", "surface": "#1E1E2E", "text": "#F5F5F5", "text_muted": "#9E9E9E"},
        "font": "Inter",
        "headings": "48px / 700 / 1.2 / -0.01em",
        "body": "16px / 400 / 1.6",
        "refs": "Linear, GitHub Dark, Vercel, Superhuman",
        "principles": "elevated surface ladder, brand glow box-shadow 0 0 20px rgba(10,132,255,0.3), subtle borders + surface lifts, high contrast",
    },
    "glassmorphism": {
        "name": "毛玻璃 Glassmorphism",
        "colors": {"glass": "rgba(255,255,255,0.1)", "border": "rgba(255,255,255,0.2)", "bg": "gradient", "text": "#FFFFFF"},
        "font": "Inter",
        "headings": "40px / 700 / 1.2",
        "body": "16px / 400 / 1.6",
        "refs": "Apple iOS, Windows 11 Acrylic",
        "principles": "backdrop-filter blur(16px), frosted glass panels, rounded-2xl, use as accent not full layout",
    },
    "bento": {
        "name": "Bento Box 网格布局",
        "colors": {"accent": "#0071E3", "bg": "#F5F5F7", "card": "#FFFFFF", "text": "#1D1D1F", "text_muted": "#86868B"},
        "font": "SF Pro Display",
        "headings": "56px / 800 / 1.1",
        "body": "17px / 400 / 1.6",
        "refs": "Apple 产品页, Stripe, Linear",
        "principles": "modular cards, asymmetric grid with col-span, uniform 16px gap, rounded-2xl, hover lift translateY(-2px)",
    },
    "neumorphism": {
        "name": "新拟态 Neumorphism",
        "colors": {"bg": "#E0E5EC", "text": "#6B7280"},
        "font": "Inter",
        "headings": "32px / 600 / 1.3",
        "body": "16px / 400 / 1.6",
        "refs": "概念设计/作品集",
        "principles": "dual shadows 8px 8px 16px #A3B1C6 -8px -8px 16px #FFFFFF, rounded-2xl, low contrast",
    },
    "cyberpunk": {
        "name": "赛博朋克 Cyberpunk",
        "colors": {"neon_cyan": "#00FFF5", "neon_pink": "#FF0080", "neon_green": "#00FF41", "bg": "#0A0A0F", "text": "#F5F5F5"},
        "font": "JetBrains Mono / Rajdhani",
        "headings": "48px / 700 / uppercase",
        "body": "14px / 400 / 1.5 / JetBrains Mono",
        "refs": "Warp, Cyberpunk 2077, DeFi platforms",
        "principles": "cut-corner clip-path, scan line overlay, glowing borders, terminal aesthetic",
    },
    "organic": {
        "name": "自然有机风 Organic",
        "colors": {"primary": "#A47F6C", "secondary": "#8B9E7E", "accent": "#D4A843", "bg": "#FAF8F5", "text": "#3D3326"},
        "font": "Lora / Playfair Display + 手写体",
        "headings": "40px / italic / 1.3",
        "body": "16px / 400 / 1.7",
        "refs": "Kinfield, Apartamento Magazine",
        "principles": "organic blob shapes, wavy dividers, botanical line illustrations, rounded-3xl cards",
    },
    "retro": {
        "name": "复古怀旧风 Retro",
        "colors": {"primary": "#C4622D", "accent": "#D4A843", "secondary": "#5C7A4B", "warm_red": "#B54B4B", "bg": "#FDF6E3"},
        "font": "Garamond / Caslon / Courier",
        "headings": "36px / 700 / Garamond",
        "body": "15px / 400 / 1.6 / Courier",
        "refs": "Mountain Dew vintage, 网易云音乐复古活动页",
        "principles": "grain texture, polaroid-style cards with slight rotation, tape decorations, thick borders",
    },
    "brutalism": {
        "name": "粗野主义 Brutalism",
        "colors": {"bg": "#FFFFFF", "bg_alt": "#FFFF00", "border": "#000000", "text": "#000000"},
        "font": "Arial Black / Courier / Times New Roman",
        "headings": "64px / 900 / uppercase / Arial Black",
        "body": "16px / 400 / 1.5 / Courier",
        "refs": "Bloomberg Businessweek, Balenciaga, Hype4 Agency",
        "principles": "thick 3px solid #000 borders, offset hard shadows 4px 4px 0 #000, broken grid, no rounded corners",
    },
    "immersive": {
        "name": "3D 沉浸式 Immersive",
        "colors": {"bg": "#111111", "accent": "#C9A96E", "text": "#F5F5F5"},
        "font": "Inter weight 300-600",
        "headings": "56px / 600 / 1.1",
        "body": "17px / 300 / 1.7",
        "refs": "Tiffany & Co., Poltrona Frau, Apple 产品页",
        "principles": "CSS 3D transforms perspective:1200px, mouse-follow rotation, parallax layers 0.2x/0.5x/1x, cards 3D tilt on hover translateZ(20px)",
    },
}


def load_design_system() -> str:
    """加载 AI-Design-System-Prompt.md 全文（缓存）。"""
    global _DESIGN_DOC_CACHE
    if _DESIGN_DOC_CACHE is not None:
        return _DESIGN_DOC_CACHE
    doc_path = Path(__file__).resolve().parent.parent.parent / "AI-Design-System-Prompt.md"
    try:
        _DESIGN_DOC_CACHE = doc_path.read_text(encoding="utf-8")
    except OSError:
        _DESIGN_DOC_CACHE = ""
    return _DESIGN_DOC_CACHE


def list_styles() -> list[str]:
    """返回所有可用风格名。"""
    return list(STYLE_BRIEFS.keys())


def infer_style(product_type: str = "") -> str:
    """根据产品类型推断合适的风格。更具体的关键词优先匹配。"""
    pt = product_type.lower()
    # 有机/自然先匹配（"organic food brand" 不应匹配 "brand" → bento）
    if any(k in pt for k in ("有机", "自然", "食品", "organic", "nature", "food")):
        return "organic"
    if any(k in pt for k in ("3d", "沉浸", "immersive", "展示", "showcase")):
        return "immersive"
    if any(k in pt for k in ("游戏", "game", "赛博", "cyber")):
        return "cyberpunk"
    if any(k in pt for k in ("终端", "terminal", "ide", "编辑器", "developer", "开发者", "工厂", "factory")):
        return "dark"
    if any(k in pt for k in ("landing", "落地", "营销", "marketing", "品牌", "brand")):
        return "bento"
    if any(k in pt for k in ("dashboard", "仪表", "后台", "admin", "监控", "monitor")):
        return "dark"
    if any(k in pt for k in ("社交", "social", "社区", "community")):
        return "minimalism"
    if any(k in pt for k in ("金融", "finance", "fintech", "支付", "payment")):
        return "dark"
    # 默认：开发者工具用暗黑模式
    return "dark"


def build_design_brief(
    style: str = "auto",
    product_type: str = "",
    constraints: str = "",
) -> str:
    """生成设计简报，注入 worker 上下文。

    输出格式对齐 AI-Design-System-Prompt.md 的万能模板，
    包含具体 hex 值、字体、动效关键词、组件状态、响应式、无障碍要求。
    worker 看到这段约束后，生成的 UI 代码会遵循设计系统。
    """
    if style == "auto":
        style = infer_style(product_type)
    brief = STYLE_BRIEFS.get(style)
    if brief is None:
        style = infer_style(product_type)
        brief = STYLE_BRIEFS[style]

    c = brief["colors"]
    # 构造配色行
    color_lines = []
    for label, hex_val in c.items():
        color_lines.append(f"- {label}: {hex_val}")
    colors_block = "\n".join(color_lines)

    extra = f"\n\n额外约束:\n{constraints}" if constraints else ""

    return f"""【UI/UX 设计系统约束 — 必须严格遵循，禁止自行发明颜色/字体/组件样式】

设计风格: {brief["name"]}
参考品牌: {brief["refs"]}

配色方案 (必须用这些 hex 值):
{colors_block}

字体:
- family: {brief["font"]}
- 标题: {brief["headings"]}
- 正文: {brief["body"]}

设计原则:
{brief["principles"]}

组件状态 (每个交互组件必须包含):
- default / hover / active / focus / disabled

动效 (使用专业术语):
- stagger fade-in with 100ms delay
- card hover lift: translateY(-2px)
- scroll reveal: opacity 0→1, translateY(20px→0)

响应式断点:
- mobile: < 768px (默认)
- tablet: 768px–1024px
- desktop: > 1024px

无障碍:
- WCAG AA: 正文对比度 >= 4.5:1, 大文本 >= 3:1
- 所有交互元素必须有 focus-visible 样式

技术约束:
- 使用 CSS variables 定义主题色 (如 --color-accent: #0A84FF)
- 所有颜色值必须用 hex，禁止用英文颜色名 (如 "blue")
- 动画优先用 CSS transform/opacity，避免触发重排{extra}
"""


def build_design_brief_compact(style: str = "auto", product_type: str = "") -> str:
    """精简版设计约束（~200 字符），避免长 prompt 导致 Kimi 陷入 reasoning 循环。

    M10.5 根因修复：完整 build_design_brief 输出 924 字符，加上任务描述和格式说明后
    prompt 总长 1400+ 字符，导致 Kimi-K2.7-Code 在 exo 上 reasoning_tokens 占满
    max_tokens（4096 tokens 中 4095 给了 reasoning，content 只剩 1-2 字节）。
    精简版只保留核心 hex 值 + 字体 + 格式要求，实测能让 Kimi 正常输出完整 HTML。
    """
    if style == "auto":
        style = infer_style(product_type)
    brief = STYLE_BRIEFS.get(style)
    if brief is None:
        style = infer_style(product_type)
        brief = STYLE_BRIEFS[style]

    c = brief["colors"]
    accent = c.get("accent", "#0A84FF")
    bg = c.get("bg", "#0D0D12")
    text = c.get("text", "#F5F5F5")
    font = brief["font"].split(" /")[0]

    return (
        f"设计约束: CSS 变量必须用 --color-accent: {accent}; --color-bg: {bg}; --color-text: {text}; "
        f"字体 {font}; 用 CSS variables; 含 hover/focus 状态; "
        f"响应式 768px; focus-visible; WCAG AA 对比度(文字≥4.5:1); "
        f"按钮文字色须与背景对比度≥4.5:1。"
    )
