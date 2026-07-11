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
    "film_atelier": {
        "name": "Film Atelier 暗房编辑台",
        "colors": {"accent": "#C9A96E", "bg": "#0D0D12", "bg_alt": "#1A1A1E", "surface": "#16161A", "text": "#E8E6E1", "text_muted": "#7A7770"},
        "font": "Inter weight 300-500 / 衬线标题 Playfair Display",
        "headings": "48px / 500 / 1.2 / -0.01em / Playfair Display italic",
        "body": "16px / 300 / 1.7",
        "refs": "Poltrona Frau, Apple Pro Apps, Leica",
        "principles": "暗房隐喻: UI 退居幕后内容为王; 克制物理呼吸式动效(opacity 0→1 800ms ease-out, translateY 12px→0); 微粒子聚合成按钮(mouseclick时粒子向心汇聚); 禁止: 彩虹粒子/大面积闪烁/粒子爆炸/快速闪烁/粒子覆盖文字/粒子数>200/速度>1.0/粗连线/纯白背景/暗角; 配色不超过5种; 深度分层: bg→surface→content 三级; 细发丝边框 rgba(255,255,255,0.06); 圆角 2px 极小; 无毛玻璃隔离层",
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
    # Film Atelier 优先匹配（用户偏好的暗房/编辑台隐喻风格）
    if any(k in pt for k in ("film", "atelier", "暗房", "编辑台", "film_atelier")):
        return "film_atelier"
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
- button/a 必须有文本内容或 aria-label（可访问名称）
- input 必须有关联的 <label for> 或 aria-label
- 标题层级 h1→h2→h3 不跳级，每页只有一个 h1

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
        f"【强制】必须用这些精确 hex 值，禁止替换: "
        f"--color-accent: {accent}; --color-bg: {bg}; --color-text: {text}; "
        f"字体 {font}; 用 CSS variables; 含 hover/active/focus/disabled 状态; "
        f"@media(max-width:768px) 响应式断点; focus-visible 样式; "
        f"WCAG AA 对比度(文字≥4.5:1); button/a 有文本或 aria-label; "
        f"input 有 label 或 aria-label; 标题 h1→h2 不跳级。"
    )


# ---------- M22: WCAG 颜色对比度校验 ----------


def hex_to_rgb(hex_str: str) -> "tuple[int, int, int]":
    """把 #RRGGBB hex 字符串转为 (r, g, b) 元组。"""
    h = hex_str.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def relative_luminance(rgb: "tuple[int, int, int]") -> float:
    """计算 WCAG 2.1 相对亮度（0-1）。

    公式：https://www.w3.org/TR/WCAG21/#dfn-relative-luminance
    """
    def _channel(c: int) -> float:
        s = c / 255.0
        return s / 12.92 if s <= 0.03928 else ((s + 0.055) / 1.055) ** 2.4

    r, g, b = rgb
    return 0.2126 * _channel(r) + 0.7152 * _channel(g) + 0.0722 * _channel(b)


def contrast_ratio(hex1: str, hex2: str) -> float:
    """计算两个颜色之间的 WCAG 对比度比率。

    返回值范围 1.0（同色）到 21.0（黑白）。
    WCAG AA 要求：正常文本 ≥ 4.5:1，大文本(≥18pt 或 ≥14pt bold) ≥ 3:1。
    """
    l1 = relative_luminance(hex_to_rgb(hex1))
    l2 = relative_luminance(hex_to_rgb(hex2))
    lighter, darker = max(l1, l2), min(l1, l2)
    return (lighter + 0.05) / (darker + 0.05)


def check_color_contrast(cwd: str) -> list[dict]:
    """扫描 HTML 文件的 CSS 颜色对比度，返回违规列表。

    提取 CSS 中的 background-color/background 和 color 属性对，
    计算 WCAG 对比度比率，低于 4.5:1 报 error。
    """
    import os as _os
    import re as _re

    violations: list[dict] = []

    for fname in _os.listdir(cwd) if _os.path.exists(cwd) else []:
        if not fname.endswith(".html"):
            continue
        fpath = _os.path.join(cwd, fname)
        if not _os.path.isfile(fpath):
            continue
        try:
            content = open(fpath, "r", encoding="utf-8").read()
        except Exception:
            continue

        # 从 CSS 规则中提取 background + color 配对
        # 匹配 { background(-color)?: #hex; color: #hex; } 模式
        # 也匹配 inline style 中的 background+color
        css_blocks = _re.findall(r"\{[^{}]*\}", content)
        for block in css_blocks:
            bg_match = _re.search(
                r"(?:background-color|background)\s*:\s*(#[0-9A-Fa-f]{6})",
                block, _re.IGNORECASE,
            )
            color_match = _re.search(
                r"(?<!background-)color\s*:\s*(#[0-9A-Fa-f]{6})",
                block, _re.IGNORECASE,
            )
            if bg_match and color_match:
                bg_hex = bg_match.group(1)
                text_hex = color_match.group(1)
                try:
                    ratio = contrast_ratio(text_hex, bg_hex)
                except Exception:
                    continue
                if ratio < 4.5:
                    violations.append({
                        "rule": "color_contrast",
                        "severity": "error",
                        "file": fname,
                        "message": (
                            f"颜色对比度 {ratio:.2f}:1 低于 WCAG AA 标准 4.5:1 "
                            f"(text={text_hex} bg={bg_hex})"
                        ),
                    })

        # 也检查 CSS 变量中的 --color-text 和 --color-bg 配对
        root_match = _re.search(r":root\s*\{([^{}]*)\}", content, _re.IGNORECASE)
        if root_match:
            root_css = root_match.group(1)
            var_text = _re.search(r"--color-text\s*:\s*(#[0-9A-Fa-f]{6})", root_css, _re.IGNORECASE)
            var_bg = _re.search(r"--color-bg\s*:\s*(#[0-9A-Fa-f]{6})", root_css, _re.IGNORECASE)
            if var_text and var_bg:
                text_hex = var_text.group(1)
                bg_hex = var_bg.group(1)
                try:
                    ratio = contrast_ratio(text_hex, bg_hex)
                except Exception:
                    continue
                if ratio < 4.5:
                    # 避免重复报告（CSS 规则已检查过的）
                    already = any(
                        v["file"] == fname and text_hex in v["message"]
                        for v in violations if v["rule"] == "color_contrast"
                    )
                    if not already:
                        violations.append({
                            "rule": "color_contrast",
                            "severity": "error",
                            "file": fname,
                            "message": (
                                f"CSS变量对比度 {ratio:.2f}:1 低于 WCAG AA 标准 4.5:1 "
                                f"(--color-text={text_hex} --color-bg={bg_hex})"
                            ),
                        })

    return violations


# ---------- M23: 间距网格 + 字体比例校验 ----------


# 8px 网格允许的间距值（含半步 4px）
_GRID_VALUES = {0, 2, 4, 8, 12, 16, 20, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160, 192, 224, 256, 320, 384, 480, 640}


def check_spacing_grid(cwd: str) -> list[dict]:
    """检查 CSS 间距值是否遵循 8px 网格系统。

    检查 padding/margin/gap 的 px 值是否在允许的网格值集合中。
    非网格值报 warning（不阻断，但提示设计不一致）。
    """
    import os as _os
    import re as _re

    violations: list[dict] = []

    for fname in _os.listdir(cwd) if _os.path.exists(cwd) else []:
        if not fname.endswith(".html"):
            continue
        fpath = _os.path.join(cwd, fname)
        if not _os.path.isfile(fpath):
            continue
        try:
            content = open(fpath, "r", encoding="utf-8").read()
        except Exception:
            continue

        # 匹配 padding/margin/gap: Npx
        spacing_matches = _re.finditer(
            r"(padding|margin|gap)[\w-]*\s*:\s*(\d+)px",
            content, _re.IGNORECASE,
        )
        seen_values: set[int] = set()
        for m in spacing_matches:
            val = int(m.group(2))
            if val not in _GRID_VALUES and val not in seen_values:
                seen_values.add(val)
                violations.append({
                    "rule": "spacing_grid",
                    "severity": "warning",
                    "file": fname,
                    "message": f"{m.group(1)}: {val}px 不在 8px 网格系统中（建议用 4/8/12/16/24/32/48/64...）",
                })

    return violations


# 模块化字体比例——Major Third (1.250) 常见值
# 基准 16px: 12, 15, 16, 20, 24, 30, 38, 48, 60, 75
# 允许 ±1px 容差
_TYPE_SCALE = {12, 13, 14, 15, 16, 17, 18, 20, 24, 30, 32, 36, 38, 40, 48, 56, 60, 64, 72, 75, 80, 96}


def check_typography_scale(cwd: str) -> list[dict]:
    """检查 CSS font-size 是否遵循模块化比例。

    常见模块化比例（Major Third 1.250, Perfect Fourth 1.333 等）的
    标准字号集合。非标准字号报 warning。
    """
    import os as _os
    import re as _re

    violations: list[dict] = []

    for fname in _os.listdir(cwd) if _os.path.exists(cwd) else []:
        if not fname.endswith(".html"):
            continue
        fpath = _os.path.join(cwd, fname)
        if not _os.path.isfile(fpath):
            continue
        try:
            content = open(fpath, "r", encoding="utf-8").read()
        except Exception:
            continue

        # 匹配 font-size: Npx
        font_matches = _re.finditer(
            r"font-size\s*:\s*(\d+)px",
            content, _re.IGNORECASE,
        )
        seen_values: set[int] = set()
        for m in font_matches:
            val = int(m.group(1))
            if val not in _TYPE_SCALE and val not in seen_values:
                seen_values.add(val)
                violations.append({
                    "rule": "typography_scale",
                    "severity": "warning",
                    "file": fname,
                    "message": f"font-size: {val}px 不在标准模块化比例中（建议用 12/14/16/18/20/24/30/38/48/60...）",
                })

    return violations


# ---------- M24: 间距/字体 auto-fix（post-generation 确定性修复） ----------


def _nearest_value(val: int, allowed: set[int], prefer_smaller_on_tie: bool = True) -> int:
    """找到集合中与 val 最近的值。平局时按 prefer_smaller_on_tie 决定取大或取小。"""
    if val in allowed:
        return val
    return min(allowed, key=lambda v: (abs(val - v), v if prefer_smaller_on_tie else -v))


def auto_fix_spacing_grid(cwd: str) -> bool:
    """自动修正非 8px 网格的间距值为最近的网格值。

    参考 M15 auto-fix 模式：不依赖模型遵守约束，在代码层面强制修正。
    扫描 HTML 文件的 padding/margin/gap px 值，
    非网格值替换为最近网格值（平局取较小值，符合"收紧间距"直觉）。
    返回是否做过修改。
    """
    import os as _os
    import re as _re

    changed = False
    for fname in _os.listdir(cwd) if _os.path.exists(cwd) else []:
        if not fname.endswith(".html"):
            continue
        fpath = _os.path.join(cwd, fname)
        if not _os.path.isfile(fpath):
            continue
        try:
            content = open(fpath, "r", encoding="utf-8").read()
        except Exception:
            continue

        def _replace(m):
            nonlocal changed
            val = int(m.group(2))
            if val in _GRID_VALUES:
                return m.group(0)
            nearest = _nearest_value(val, _GRID_VALUES, prefer_smaller_on_tie=True)
            changed = True
            return f"{m.group(1)}{nearest}{m.group(3)}"

        new_content = _re.sub(
            r"((?:padding|margin|gap)[\w-]*\s*:\s*)(\d+)(px)",
            _replace,
            content,
            flags=_re.IGNORECASE,
        )
        if new_content != content:
            try:
                open(fpath, "w", encoding="utf-8").write(new_content)
            except Exception:
                pass

    return changed


def auto_fix_typography_scale(cwd: str) -> bool:
    """自动修正非标准字号为最近的模块化比例字号。

    平局取较大值（字号偏大可读性更好）。
    返回是否做过修改。
    """
    import os as _os
    import re as _re

    changed = False
    for fname in _os.listdir(cwd) if _os.path.exists(cwd) else []:
        if not fname.endswith(".html"):
            continue
        fpath = _os.path.join(cwd, fname)
        if not _os.path.isfile(fpath):
            continue
        try:
            content = open(fpath, "r", encoding="utf-8").read()
        except Exception:
            continue

        def _replace(m):
            nonlocal changed
            val = int(m.group(2))
            if val in _TYPE_SCALE:
                return m.group(0)
            nearest = _nearest_value(val, _TYPE_SCALE, prefer_smaller_on_tie=False)
            changed = True
            return f"{m.group(1)}{nearest}{m.group(3)}"

        new_content = _re.sub(
            r"(font-size\s*:\s*)(\d+)(px)",
            _replace,
            content,
            flags=_re.IGNORECASE,
        )
        if new_content != content:
            try:
                open(fpath, "w", encoding="utf-8").write(new_content)
            except Exception:
                pass

    return changed


def auto_fix_html_structure(cwd: str) -> bool:
    """自动修正 HTML 结构性问题：meta viewport、html lang、img alt。

    参考 M15 auto-fix 模式：不依赖模型遵守约束，在代码层面强制修正。
    - 缺少 meta viewport → 在 <head> 后注入
    - <html> 缺少 lang 属性 → 添加 lang="zh"
    - <img> 缺少 alt 属性 → 添加 alt=""（空 alt 对装饰性图片是 WCAG 合规的）
    返回是否做过修改。
    """
    import os as _os
    import re as _re

    changed = False
    for fname in _os.listdir(cwd) if _os.path.exists(cwd) else []:
        if not fname.endswith(".html"):
            continue
        fpath = _os.path.join(cwd, fname)
        if not _os.path.isfile(fpath):
            continue
        try:
            content = open(fpath, "r", encoding="utf-8").read()
        except Exception:
            continue

        original = content

        # 1. meta viewport
        if "viewport" not in content.lower() and "<head" in content.lower():
            # 在 <head> 标签后注入 viewport meta
            content = _re.sub(
                r"(<head[^>]*>)",
                r'\1<meta name="viewport" content="width=device-width, initial-scale=1">',
                content,
                count=1,
                flags=_re.IGNORECASE,
            )

        # 2. html lang
        if "<html" in content.lower():
            # 检查 <html> 标签是否已有 lang 属性（匹配 <html> 和 <html ...>）
            html_match = _re.search(r"<html[^>]*>", content, _re.IGNORECASE)
            if html_match and "lang=" not in html_match.group(0).lower():
                # 在 <html 后添加 lang="zh"
                content = _re.sub(
                    r"(<html)(\s|>)",
                    r'\1 lang="zh"\2',
                    content,
                    count=1,
                    flags=_re.IGNORECASE,
                )

        # 3. img alt — 给所有缺少 alt 的 <img> 添加 alt=""
        def _add_alt(m):
            nonlocal changed
            tag = m.group(0)
            if "alt=" in tag.lower():
                return tag
            # 在 <img 后、> 前插入 alt=""
            # 处理自闭合 <img ... /> 和非自闭合 <img ...>
            if tag.endswith("/>"):
                return tag[:-2] + ' alt="" />'
            else:
                return tag[:-1] + ' alt="">'

        new_content = _re.sub(
            r"<img\s+[^>]*>",
            _add_alt,
            content,
            flags=_re.IGNORECASE,
        )
        content = new_content

        if content != original:
            changed = True
            try:
                open(fpath, "w", encoding="utf-8").write(content)
            except Exception:
                pass

    return changed


# transition 允许的性能友好属性（transform/opacity 不会触发重排）
_PERF_OK_PROPS = {"transform", "opacity"}


def auto_fix_animation_performance(cwd: str) -> bool:
    """自动修正 transition 中的非性能友好属性。

    只保留 transform/opacity（不触发重排），移除 margin/padding/left/top/
    width/height 等（会触发重排）。如果整个 transition 都是坏属性，移除整个
    transition 声明。返回是否做过修改。
    """
    import os as _os
    import re as _re

    changed = False
    for fname in _os.listdir(cwd) if _os.path.exists(cwd) else []:
        if not fname.endswith(".html"):
            continue
        fpath = _os.path.join(cwd, fname)
        if not _os.path.isfile(fpath):
            continue
        try:
            content = open(fpath, "r", encoding="utf-8").read()
        except Exception:
            continue

        original = content

        def _fix_transition(m):
            nonlocal changed
            full = m.group(0)  # 整个 transition: ...; 或 transition: ...}
            # 提取 transition 的值部分
            val_match = _re.match(r"(transition\s*:\s*)([^;}]+)([;}])", full, _re.IGNORECASE)
            if not val_match:
                return full
            prefix = val_match.group(1)
            val = val_match.group(2)
            suffix = val_match.group(3)

            # 按逗号分割各个属性 transition
            parts = [p.strip() for p in val.split(",")]
            good_parts = []
            for part in parts:
                # 每部分第一个词是 CSS 属性名
                prop = part.split()[0].lower() if part.split() else ""
                if prop in _PERF_OK_PROPS:
                    good_parts.append(part)
                # else: 坏属性，跳过

            if len(good_parts) == len(parts):
                # 没有移除任何属性，不修改
                return full

            changed = True
            if not good_parts:
                # 全部移除 → 删除整个 transition 声明（包括后面的 ;）
                return suffix if suffix == ";" else ""
            return prefix + ", ".join(good_parts) + suffix

        content = _re.sub(
            r"transition\s*:\s*[^;}]+[;}]",
            _fix_transition,
            content,
            flags=_re.IGNORECASE,
        )

        if content != original:
            changed = True
            try:
                open(fpath, "w", encoding="utf-8").write(content)
            except Exception:
                pass

    return changed


# 默认 CSS 变量系统（dark 风格的值，worker 未定义 --color-* 时注入）
_DEFAULT_CSS_VARS = """  --color-bg: #0D0D12;
  --color-text: #F5F5F5;
  --color-accent: #0A84FF;
  --color-text-muted: #9E9E9E;
  --color-surface: #1E1E2E;
"""


def auto_fix_css_variables(cwd: str) -> bool:
    """自动注入 CSS 变量系统。

    - 有 :root 但缺少 --color-* 变量 → 在 :root 内追加默认 --color-* 变量
    - 完全没有 :root → 在 <style> 开头注入完整 :root { --color-*: ...; }

    默认值用 dark 风格的配色（worker 不提供变量系统时的合理回退）。
    返回是否做过修改。
    """
    import os as _os
    import re as _re

    changed = False
    for fname in _os.listdir(cwd) if _os.path.exists(cwd) else []:
        if not fname.endswith(".html"):
            continue
        fpath = _os.path.join(cwd, fname)
        if not _os.path.isfile(fpath):
            continue
        try:
            content = open(fpath, "r", encoding="utf-8").read()
        except Exception:
            continue

        original = content

        has_root = ":root" in content.lower()
        has_color_vars = "--color-bg" in content and "--color-text" in content

        if has_color_vars:
            # 已有 --color-* 变量，不需要修复
            continue

        if has_root:
            # 有 :root 但缺少 --color-* → 在 :root { 后追加
            def _inject_in_root(m):
                nonlocal changed
                changed = True
                return m.group(1) + _DEFAULT_CSS_VARS + m.group(2)

            content = _re.sub(
                r"(:root\s*\{)(\s*)",
                _inject_in_root,
                content,
                count=1,
                flags=_re.IGNORECASE,
            )
        elif "<style" in content.lower():
            # 没有 :root 但有 <style> → 在 <style> 后注入完整 :root 块
            content = _re.sub(
                r"(<style[^>]*>)",
                r"\1:root {" + _DEFAULT_CSS_VARS + "}",
                content,
                count=1,
                flags=_re.IGNORECASE,
            )
            changed = True

        if content != original:
            changed = True
            try:
                open(fpath, "w", encoding="utf-8").write(content)
            except Exception:
                pass

    return changed


def auto_fix_semantic_html(cwd: str) -> bool:
    """自动注入语义化 HTML 标签：header/main/footer。

    - 缺少 <main> → 把 <body> 的直接内容包裹在 <main>...</main> 中
    - 缺少 <header> → 在 <body> 后注入 <header></header>
    - 缺少 <footer> → 在 </body> 前注入 <footer></footer>
    返回是否做过修改。
    """
    import os as _os
    import re as _re

    changed = False
    for fname in _os.listdir(cwd) if _os.path.exists(cwd) else []:
        if not fname.endswith(".html"):
            continue
        fpath = _os.path.join(cwd, fname)
        if not _os.path.isfile(fpath):
            continue
        try:
            content = open(fpath, "r", encoding="utf-8").read()
        except Exception:
            continue

        original = content
        lower = content.lower()

        # 1. 缺少 <main> → 包裹 body 内容
        if "<main" not in lower and "<body" in lower:
            # 在 <body...> 后插入 <main>，在 </body> 前插入 </main>
            content = _re.sub(
                r"(<body[^>]*>)",
                r"\1<main>",
                content,
                count=1,
                flags=_re.IGNORECASE,
            )
            content = _re.sub(
                r"(</body>)",
                r"</main>\1",
                content,
                count=1,
                flags=_re.IGNORECASE,
            )

        # 2. 缺少 <header> → 在 <body> 后注入
        if "<header" not in content.lower() and "<body" in content.lower():
            content = _re.sub(
                r"(<body[^>]*>)",
                r"\1<header></header>",
                content,
                count=1,
                flags=_re.IGNORECASE,
            )

        # 3. 缺少 <footer> → 在 </body> 前注入
        if "<footer" not in content.lower() and "</body>" in content.lower():
            content = _re.sub(
                r"(</body>)",
                r"<footer></footer>\1",
                content,
                count=1,
                flags=_re.IGNORECASE,
            )

        if content != original:
            changed = True
            try:
                open(fpath, "w", encoding="utf-8").write(content)
            except Exception:
                pass

    return changed


def auto_fix_focus_visible(cwd: str) -> bool:
    """M34: 注入 :focus-visible 样式（如果缺少）。

    键盘导航需要可见的焦点。生成的 HTML 常常忘记加焦点样式，
    这里在 <style> 中注入默认的 :focus-visible 样式。
    """
    import os as _os
    import re as _re

    _FOCUS_CSS = (
        ":focus-visible{outline:2px solid var(--color-accent,#0A84FF);outline-offset:2px}"
    )

    changed = False
    for fname in _os.listdir(cwd):
        if not fname.endswith(".html"):
            continue
        fpath = _os.path.join(cwd, fname)
        if not _os.path.isfile(fpath):
            continue
        try:
            content = open(fpath, "r", encoding="utf-8").read()
        except Exception:
            continue

        lower = content.lower()
        if ":focus" in lower:
            continue  # 已有焦点样式

        # 在 <style> 标签后注入
        if "<style>" in lower:
            content = _re.sub(
                r"(<style[^>]*>)",
                r"\1" + _FOCUS_CSS,
                content, count=1, flags=_re.IGNORECASE,
            )
        elif "</head>" in lower:
            # 在 </head> 前注入 <style>
            style_block = f"<style>{_FOCUS_CSS}</style>"
            content = _re.sub(
                r"(</head>)",
                style_block + r"\1",
                content, count=1, flags=_re.IGNORECASE,
            )
        else:
            continue  # 无 head 也无 style，跳过

        with open(fpath, "w", encoding="utf-8") as f:
            f.write(content)
        changed = True

    return changed


def auto_fix_responsive(cwd: str) -> bool:
    """M35: 注入 @media 响应式断点（如果缺少）。

    原则 7：响应式必须写断点。缺少 @media 时注入 mobile-first 断点。
    """
    import os as _os
    import re as _re

    _RESPONSIVE_CSS = (
        "@media(max-width:768px){body{font-size:14px}}"
        "@media(min-width:1024px){body{max-width:1200px;margin:0 auto}}"
    )

    changed = False
    for fname in _os.listdir(cwd):
        if not fname.endswith(".html"):
            continue
        fpath = _os.path.join(cwd, fname)
        if not _os.path.isfile(fpath):
            continue
        try:
            content = open(fpath, "r", encoding="utf-8").read()
        except Exception:
            continue

        if "@media" in content.lower():
            continue  # 已有响应式断点

        if "<style>" in content.lower():
            content = _re.sub(
                r"(</style>)",
                _RESPONSIVE_CSS + r"\1",
                content, count=1, flags=_re.IGNORECASE,
            )
        elif "</head>" in content.lower():
            style_block = f"<style>{_RESPONSIVE_CSS}</style>"
            content = _re.sub(
                r"(</head>)",
                style_block + r"\1",
                content, count=1, flags=_re.IGNORECASE,
            )
        else:
            continue

        with open(fpath, "w", encoding="utf-8") as f:
            f.write(content)
        changed = True

    return changed


def auto_fix_component_states(cwd: str) -> bool:
    """M35: 注入交互组件状态样式（如果缺少）。

    原则 6：组件必须有状态（hover/active/focus/disabled）。
    检测到 button/a/input/select/textarea 但缺少状态样式时注入。
    """
    import os as _os
    import re as _re

    _STATES_CSS = (
        "button:hover,a:hover,input:hover{opacity:0.85}"
        "button:active,a:active,input:active{transform:scale(0.98)}"
        "button:focus,a:focus,input:focus{outline:2px solid var(--color-accent,#0A84FF);outline-offset:2px}"
        "button:disabled,input:disabled{opacity:0.5;cursor:not-allowed}"
    )

    changed = False
    for fname in _os.listdir(cwd):
        if not fname.endswith(".html"):
            continue
        fpath = _os.path.join(cwd, fname)
        if not _os.path.isfile(fpath):
            continue
        try:
            content = open(fpath, "r", encoding="utf-8").read()
        except Exception:
            continue

        lower = content.lower()
        # 无交互元素则跳过
        if not _re.search(r"<(?:button|a|input|select|textarea)\b", content, _re.IGNORECASE):
            continue

        # 检查是否所有状态都已存在
        all_present = all(s in lower for s in (":hover", ":active", ":focus", ":disabled"))
        if all_present:
            continue

        if "<style>" in lower:
            content = _re.sub(
                r"(</style>)",
                _STATES_CSS + r"\1",
                content, count=1, flags=_re.IGNORECASE,
            )
        elif "</head>" in lower:
            style_block = f"<style>{_STATES_CSS}</style>"
            content = _re.sub(
                r"(</head>)",
                style_block + r"\1",
                content, count=1, flags=_re.IGNORECASE,
            )
        else:
            continue

        with open(fpath, "w", encoding="utf-8") as f:
            f.write(content)
        changed = True

    return changed


def auto_fix_aria_label(cwd: str) -> bool:
    """M38: 为缺少可访问名称的 button/a 注入 aria-label。

    axe-core 启发：交互元素无文本内容且无 aria-label 时，
    自动注入 aria-label="button" / aria-label="link"。
    """
    import os as _os
    import re as _re

    changed = False
    for fname in _os.listdir(cwd):
        if not fname.endswith(".html"):
            continue
        fpath = _os.path.join(cwd, fname)
        if not _os.path.isfile(fpath):
            continue
        try:
            content = open(fpath, "r", encoding="utf-8").read()
        except Exception:
            continue

        new_content = content
        for tag in ("button", "a"):
            # 匹配 <button ...>内容</button> 或 <a ...>内容</a>
            def _inject(m):
                attrs = m.group(1) or ""
                inner = m.group(2) or ""
                if "aria-label" in attrs.lower():
                    return m.group(0)  # 已有 aria-label
                text_content = _re.sub(r"<[^>]+>", "", inner).strip()
                if text_content:
                    return m.group(0)  # 有文本内容
                # 注入 aria-label
                label_val = "button" if tag == "button" else "link"
                return f"<{tag}{attrs} aria-label=\"{label_val}\">{inner}</{tag}>"

            new_content = _re.sub(
                rf"<{tag}\b([^>]*)>(.*?)</{tag}>",
                _inject,
                new_content,
                flags=_re.IGNORECASE | _re.DOTALL,
            )

        if new_content != content:
            with open(fpath, "w", encoding="utf-8") as f:
                f.write(new_content)
            changed = True

    return changed


def auto_fix_form_label(cwd: str) -> bool:
    """M38: 为缺少 label 的 input 注入 aria-label。

    axe-core 启发：input 无关联 label 且无 aria-label 时，
    自动注入 aria-label（基于 name 属性或通用值）。
    """
    import os as _os
    import re as _re

    changed = False
    for fname in _os.listdir(cwd):
        if not fname.endswith(".html"):
            continue
        fpath = _os.path.join(cwd, fname)
        if not _os.path.isfile(fpath):
            continue
        try:
            content = open(fpath, "r", encoding="utf-8").read()
        except Exception:
            continue

        # 提取所有 label for 的 id
        label_for_ids = set(
            _re.findall(r'<label\b[^>]*for\s*=\s*["\']([^"\']+)["\']', content, _re.IGNORECASE)
        )

        def _inject_input(m):
            full_match = m.group(0)
            attrs = m.group(1) or ""
            attrs_lower = attrs.lower()
            # 已有 aria-label
            if "aria-label" in attrs_lower:
                return full_match
            # hidden 类型跳过
            if 'type="hidden"' in attrs_lower or "type='hidden'" in attrs_lower:
                return full_match
            # 有 label for 关联
            id_match = _re.search(r'\bid\s*=\s*["\']([^"\']+)["\']', attrs, _re.IGNORECASE)
            if id_match and id_match.group(1) in label_for_ids:
                return full_match
            # 注入 aria-label（基于 name 属性）
            name_match = _re.search(r'\bname\s*=\s*["\']([^"\']+)["\']', attrs, _re.IGNORECASE)
            label_val = name_match.group(1) if name_match else "input"
            return f"<input{attrs} aria-label=\"{label_val}\">"

        new_content = _re.sub(
            r"<input\b([^>]*)>",
            _inject_input,
            content,
            flags=_re.IGNORECASE,
        )

        if new_content != content:
            with open(fpath, "w", encoding="utf-8") as f:
                f.write(new_content)
            changed = True

    return changed


# ---------- M48: auto_fix_color_palette — 配色超过 5 种时合并 ----------


_BW_COLORS = {"#000000", "#FFFFFF", "#FFF", "#000"}


def _rgb_distance(c1: str, c2: str) -> int:
    """计算两个 hex 颜色之间的 RGB 欧氏距离平方。"""
    r1, g1, b1 = int(c1[1:3], 16), int(c1[3:5], 16), int(c1[5:7], 16)
    r2, g2, b2 = int(c2[1:3], 16), int(c2[3:5], 16), int(c2[5:7], 16)
    return (r1 - r2) ** 2 + (g1 - g2) ** 2 + (b1 - b2) ** 2


def _normalize_hex(h: str) -> str:
    """统一 hex 为大写 6 位 #RRGGBB。"""
    h = h.upper()
    if len(h) == 4:  # #ABC → #AABBCC
        h = "#" + h[1] * 2 + h[2] * 2 + h[3] * 2
    return h


def auto_fix_color_palette(cwd: str) -> bool:
    """配色超过 5 种设计色时，合并到 top-5 最常用色。

    策略：按出现频次排序保留 top-5，剩余颜色替换为 RGB 距离最近的保留色。
    黑白（#000000/#FFFFFF）不计入设计色。
    """
    import os as _os
    import re as _re
    from collections import Counter

    changed = False
    for fname in _os.listdir(cwd) if _os.path.exists(cwd) else []:
        if not fname.endswith(".html"):
            continue
        fpath = _os.path.join(cwd, fname)
        if not _os.path.isfile(fpath):
            continue
        try:
            content = open(fpath, "r", encoding="utf-8").read()
        except Exception:
            continue

        # 收集所有 hex 颜色（6 位和 3 位）
        raw_colors = _re.findall(r"#[0-9A-Fa-f]{6}\b|#[0-9A-Fa-f]{3}\b", content)
        if not raw_colors:
            continue

        # 统一为大写 6 位
        norm_colors = [_normalize_hex(c) for c in raw_colors]
        counter = Counter(norm_colors)

        # 排除黑白
        design_colors = {c for c in counter if c not in _BW_COLORS}
        if len(design_colors) <= 5:
            continue

        # 按频次排序，保留 top-5
        sorted_colors = sorted(design_colors, key=lambda c: counter[c], reverse=True)
        keep = set(sorted_colors[:5])
        replace = sorted_colors[5:]

        # 为每个被替换的颜色找最近的保留色
        replace_map: dict[str, str] = {}
        for rc in replace:
            nearest = min(keep, key=lambda kc: _rgb_distance(rc, kc))
            replace_map[rc] = nearest

        if not replace_map:
            continue

        # 执行替换：需要处理大小写和 3 位/6 位变体
        new_content = content
        for old_hex, new_hex in replace_map.items():
            # 替换大写 6 位
            new_content = new_content.replace(old_hex, new_hex)
            # 替换小写 6 位
            new_content = new_content.replace(old_hex.lower(), new_hex.lower())
            # 替换 3 位简写（如果原始是 3 位形式，如 #0AF）
            if old_hex[1] == old_hex[2] and old_hex[3] == old_hex[4] and old_hex[5] == old_hex[6]:
                short_old = "#" + old_hex[1] + old_hex[3] + old_hex[5]
                short_new = "#" + new_hex[1] + new_hex[3] + new_hex[5]
                new_content = new_content.replace(short_old, short_new)
                new_content = new_content.replace(short_old.lower(), short_new.lower())

        if new_content != content:
            with open(fpath, "w", encoding="utf-8") as f:
                f.write(new_content)
            changed = True

    return changed


# ---------- M53: 入场动画 lint + auto-fix（scroll-reveal / stagger fade-in） ----------


def check_scroll_animation(cwd: str) -> list[dict]:
    """检查 HTML 是否有入场动画（@keyframes + animation: + opacity/transform）。

    AI 生成的页面常常是静态的，缺少入场动画。设计文档明确要求
    "stagger fade-in with 100ms delay" 和 "scroll reveal" 等专业动效术语。
    缺少入场动画 → warning。

    检测策略（启发式，不解析嵌套花括号）：
    1. 有 @keyframes 定义
    2. 有元素使用 animation: 引用
    3. CSS 中包含 opacity 或 transform（好动画用这些属性）
    三者都满足才算"有入场动画"，否则报 violation。
    """
    import os as _os
    import re as _re

    violations: list[dict] = []

    for fname in _os.listdir(cwd) if _os.path.exists(cwd) else []:
        if not fname.endswith(".html"):
            continue
        fpath = _os.path.join(cwd, fname)
        if not _os.path.isfile(fpath):
            continue
        try:
            content = open(fpath, "r", encoding="utf-8").read()
        except Exception:
            continue

        lower = content.lower()
        has_keyframes = "@keyframes" in lower
        has_animation = bool(_re.search(r"animation\s*:", content, _re.IGNORECASE))
        has_good_props = "opacity" in lower or "transform" in lower

        if not (has_keyframes and has_animation and has_good_props):
            violations.append({
                "rule": "scroll_animation",
                "severity": "warning",
                "file": fname,
                "message": "缺少入场动画（@keyframes + animation: + opacity/transform）",
            })

    return violations


def auto_fix_scroll_animation(cwd: str) -> bool:
    """M53: 注入入场动画（如果缺少）。

    克制的物理呼吸式动效（对齐用户偏好）：
    - @keyframes fadeInUp: opacity 0→1 + translateY(20px→0)
    - 应用于 main > *, section, article
    - 0.8s ease-out both（克制，非快速闪烁）
    """
    import os as _os
    import re as _re

    _ANIM_CSS = (
        "@keyframes fadeInUp{from{opacity:0;transform:translateY(20px)}"
        "to{opacity:1;transform:translateY(0)}}"
        "main>*,section,article{animation:fadeInUp 0.8s ease-out both}"
    )

    changed = False
    for fname in _os.listdir(cwd) if _os.path.exists(cwd) else []:
        if not fname.endswith(".html"):
            continue
        fpath = _os.path.join(cwd, fname)
        if not _os.path.isfile(fpath):
            continue
        try:
            content = open(fpath, "r", encoding="utf-8").read()
        except Exception:
            continue

        # 检查是否已有入场动画
        violations = check_scroll_animation(_os.path.dirname(fpath))
        has_violation = any(
            v["file"] == fname and v["rule"] == "scroll_animation"
            for v in violations
        )
        if not has_violation:
            continue  # 已有入场动画，跳过

        lower = content.lower()
        if "<style>" in lower:
            # 在 </style> 前注入
            content = _re.sub(
                r"(</style>)",
                _ANIM_CSS + r"\1",
                content, count=1, flags=_re.IGNORECASE,
            )
        elif "</head>" in lower:
            # 在 </head> 前注入 <style>
            style_block = f"<style>{_ANIM_CSS}</style>"
            content = _re.sub(
                r"(</head>)",
                style_block + r"\1",
                content, count=1, flags=_re.IGNORECASE,
            )
        else:
            continue  # 无 head 也无 style，跳过

        with open(fpath, "w", encoding="utf-8") as f:
            f.write(content)
        changed = True

    return changed


def auto_fix_design_issues(cwd: str) -> bool:
    """组合调用所有 auto-fix 函数，返回是否做过任何修改。"""
    changed1 = auto_fix_spacing_grid(cwd)
    changed2 = auto_fix_typography_scale(cwd)
    changed3 = auto_fix_html_structure(cwd)
    changed4 = auto_fix_animation_performance(cwd)
    changed5 = auto_fix_css_variables(cwd)
    changed6 = auto_fix_semantic_html(cwd)
    changed7 = auto_fix_focus_visible(cwd)
    changed8 = auto_fix_responsive(cwd)
    changed9 = auto_fix_component_states(cwd)
    changed10 = auto_fix_aria_label(cwd)
    changed11 = auto_fix_form_label(cwd)
    changed12 = auto_fix_color_palette(cwd)
    changed13 = auto_fix_scroll_animation(cwd)
    return (
        changed1 or changed2 or changed3 or changed4 or changed5
        or changed6 or changed7 or changed8 or changed9 or changed10 or changed11
        or changed12 or changed13
    )


# ---------- M19: 设计质量校验器 ----------

def lint_design_quality(cwd: str) -> list[dict]:
    """扫描 HTML 文件的设计质量问题，返回违规列表。

    检查项（确定性，不依赖 LLM）：
    - 语义化 HTML：是否有 <header>/<main>/<section>/<footer>
    - meta viewport：是否有 <meta name="viewport">
    - CSS 变量使用：是否用 :root 定义 --color-* 变量
    - 内联 vs 外部 CSS：是否使用 <style> 内联（单文件场景 OK）
    - 图片 alt 属性：所有 <img> 是否有 alt
    - 按钮无障碍：所有 <button>/<a role=button> 是否有可访问文本
    - 动画性能：animation/transition 是否优先用 transform/opacity
    """
    violations: list[dict] = []
    import os as _os
    import re as _re

    for fname in _os.listdir(cwd):
        if not fname.endswith(".html"):
            continue
        fpath = _os.path.join(cwd, fname)
        if not _os.path.isfile(fpath):
            continue
        try:
            content = open(fpath, "r", encoding="utf-8").read()
        except Exception:
            continue
        lower = content.lower()

        # 1. 语义化 HTML
        if "<header" not in lower and "<nav" not in lower:
            violations.append({
                "rule": "semantic_html",
                "severity": "warning",
                "file": fname,
                "message": "缺少 <header> 或 <nav> 语义标签",
            })
        if "<main" not in lower and "<section" not in lower:
            violations.append({
                "rule": "semantic_html",
                "severity": "warning",
                "file": fname,
                "message": "缺少 <main> 或 <section> 语义标签",
            })
        if "<footer" not in lower:
            violations.append({
                "rule": "semantic_html",
                "severity": "warning",
                "file": fname,
                "message": "缺少 <footer> 语义标签",
            })

        # 2. meta viewport
        if "viewport" not in lower:
            violations.append({
                "rule": "meta_viewport",
                "severity": "error",
                "file": fname,
                "message": "缺少 <meta name='viewport'>，移动端不会正确缩放",
            })

        # 3. CSS 变量
        if ":root" in lower and "--color-" not in lower:
            violations.append({
                "rule": "css_variables",
                "severity": "warning",
                "file": fname,
                "message": "有 :root 但未定义 --color-* 主题变量",
            })

        # 4. 图片 alt 属性
        img_matches = _re.findall(r"<img\s+[^>]*>", content, _re.IGNORECASE)
        for img_tag in img_matches:
            if "alt=" not in img_tag.lower():
                violations.append({
                    "rule": "img_alt_missing",
                    "severity": "error",
                    "file": fname,
                    "message": f"<img> 缺少 alt 属性: {img_tag[:80]}",
                })

        # 5. 动画性能：检查是否有 margin/padding/left/top 的 transition
        # （应该用 transform/opacity）
        bad_transitions = _re.findall(
            r"transition\s*:\s*[^;]*(?:margin|padding|left|top|width|height)[^;]*",
            content, _re.IGNORECASE,
        )
        if bad_transitions:
            violations.append({
                "rule": "animation_performance",
                "severity": "warning",
                "file": fname,
                "message": f"transition 使用了非 transform/opacity 属性（可能触发重排）: {bad_transitions[0][:80]}",
            })

        # 6. lang 属性
        if "<html" in lower and "lang=" not in lower:
            violations.append({
                "rule": "html_lang",
                "severity": "warning",
                "file": fname,
                "message": "<html> 缺少 lang 属性",
            })

        # 7. M34: 标题层级检查（h1-h6 不跳级）
        headings = _re.findall(r"<(h[1-6])\b", content, _re.IGNORECASE)
        levels = [int(h[1]) for h in headings]
        if levels:
            # 多个 h1
            if levels.count(1) > 1:
                violations.append({
                    "rule": "heading_hierarchy",
                    "severity": "warning",
                    "file": fname,
                    "message": f"页面有 {levels.count(1)} 个 <h1>，应只有一个主标题",
                })
            # 跳级检查
            prev_level = 0
            for level in levels:
                if prev_level > 0 and level > prev_level + 1:
                    violations.append({
                        "rule": "heading_hierarchy",
                        "severity": "warning",
                        "file": fname,
                        "message": f"标题层级跳级：h{prev_level} → h{level}（应按 h{prev_level} → h{prev_level+1}）",
                    })
                    break  # 只报第一个跳级
                prev_level = level

        # 8. M34: 键盘焦点可见性检查
        if ":focus" not in lower and ":focus-visible" not in lower:
            violations.append({
                "rule": "focus_visible",
                "severity": "warning",
                "file": fname,
                "message": "缺少 :focus/:focus-visible 样式，键盘导航时焦点不可见",
            })

        # 9. M35: 响应式断点检查（原则 7：响应式必须写断点）
        if "@media" not in lower:
            violations.append({
                "rule": "responsive_breakpoints",
                "severity": "warning",
                "file": fname,
                "message": "缺少 @media 响应式断点，应覆盖 mobile/tablet/desktop",
            })

        # 10. M35: 组件状态检查（原则 6：组件必须有状态）
        has_interactive = _re.search(r"<(?:button|a|input|select|textarea)\b", content, _re.IGNORECASE)
        if has_interactive:
            missing_states = []
            for state in (":hover", ":active", ":focus", ":disabled"):
                if state not in lower:
                    missing_states.append(state)
            if missing_states:
                violations.append({
                    "rule": "component_states",
                    "severity": "warning",
                    "file": fname,
                    "message": f"交互元素缺少状态样式: {', '.join(missing_states)}",
                })

        # 11. M37: 可访问名称检查（axe-core 启发）
        # button/a 元素应有文本内容或 aria-label
        for tag in ("button", "a"):
            for match in _re.finditer(
                rf"<{tag}\b([^>]*)>(.*?)</{tag}>",
                content, _re.IGNORECASE | _re.DOTALL,
            ):
                attrs = match.group(1) or ""
                inner = match.group(2) or ""
                # 有 aria-label 则合规
                if "aria-label" in attrs.lower():
                    continue
                # 有文本内容（去除 HTML 标签后非空）则合规
                text_content = _re.sub(r"<[^>]+>", "", inner).strip()
                if text_content:
                    continue
                violations.append({
                    "rule": "aria_label",
                    "severity": "warning",
                    "file": fname,
                    "message": f"<{tag}> 缺少可访问名称（文本内容或 aria-label）",
                })

        # 12. M37: 表单标签检查（axe-core 启发）
        # input 元素应有关联的 <label for="..."> 或 aria-label
        input_matches = _re.findall(
            r"<input\b([^>]*)>",
            content, _re.IGNORECASE,
        )
        if input_matches:
            # 提取所有 label for 的 id
            label_for_ids = set(
                _re.findall(r'<label\b[^>]*for\s*=\s*["\']([^"\']+)["\']', content, _re.IGNORECASE)
            )
            # 提取所有 input 的 id
            for input_attrs in input_matches:
                attrs_lower = input_attrs.lower()
                # 有 aria-label 则合规
                if "aria-label" in attrs_lower:
                    continue
                # 有 type=hidden 则跳过
                if 'type="hidden"' in attrs_lower or "type='hidden'" in attrs_lower:
                    continue
                # 检查是否有 label for 关联
                id_match = _re.search(r'\bid\s*=\s*["\']([^"\']+)["\']', input_attrs, _re.IGNORECASE)
                if id_match and id_match.group(1) in label_for_ids:
                    continue  # 有 label for 关联
                violations.append({
                    "rule": "form_label",
                    "severity": "warning",
                    "file": fname,
                    "message": "<input> 缺少关联的 <label> 或 aria-label",
                })

    # 7. M22: WCAG 颜色对比度
    try:
        violations.extend(check_color_contrast(cwd))
    except Exception:
        pass

    # 8. M23: 间距网格 + 字体比例
    try:
        violations.extend(check_spacing_grid(cwd))
        violations.extend(check_typography_scale(cwd))
    except Exception:
        pass

    # 9. M53: 入场动画
    try:
        violations.extend(check_scroll_animation(cwd))
    except Exception:
        pass

    return violations


def design_score(cwd: str) -> "tuple[int, list[str]]":
    """计算 HTML 文件的设计质量评分（0-100），返回 (分数, 评语列表)。

    M36 评分维度（每项权重不同，含 M34/M35 新维度）：
    - 语义化HTML结构 (15分)：header/main/section/footer 齐全
    - meta 标签 (10分)：viewport + charset
    - CSS 变量系统 (10分)：:root 定义 --color-* 变量
    - 响应式 (15分)：viewport meta (5分) + @media 断点 (10分) [M35]
    - 无障碍 (15分)：img alt + html lang + 颜色对比度 + :focus 样式 [M34]
    - 标题层级 (5分)：h1-h6 不跳级 [M34]
    - 组件状态 (10分)：hover/active/focus/disabled [M35]
    - 动画性能 (10分)：transition 用 transform/opacity
    - 设计一致性 (10分)：配色不超过5种 hex 值
    """
    import os as _os
    import re as _re

    # 先检查是否有 HTML 文件
    has_html = any(
        fname.endswith(".html") and _os.path.isfile(_os.path.join(cwd, fname))
        for fname in _os.listdir(cwd)
    ) if _os.path.exists(cwd) else False
    if not has_html:
        return 0, ["未找到HTML文件"]

    score = 0
    notes: list[str] = []
    violations = lint_design_quality(cwd)
    error_rules = {v["rule"] for v in violations if v["severity"] == "error"}
    warning_rules = {v["rule"] for v in violations if v["severity"] == "warning"}

    # 1. 语义化HTML (15分)
    if "semantic_html" not in warning_rules:
        score += 15
    else:
        score += 8
        notes.append("语义化HTML不完整(-7)")

    # 2. meta 标签 (10分)
    if "meta_viewport" not in error_rules:
        score += 10
    else:
        notes.append("缺少viewport meta(-10)")

    # 3. CSS 变量 (10分)
    if "css_variables" not in warning_rules:
        score += 10
    else:
        score += 5
        notes.append("CSS变量使用不充分(-5)")

    # 4. 响应式 (15分) — M35: viewport meta (5分) + @media 断点 (10分)
    if "meta_viewport" not in error_rules:
        score += 5
    else:
        notes.append("缺少viewport meta(-5)")
    if "responsive_breakpoints" not in warning_rules:
        score += 10
    else:
        score += 0
        notes.append("缺少@media响应式断点(-10)")

    # 5. 无障碍 (15分) — M34: 含 :focus 样式检查; M38: 含 aria_label + form_label
    a11y_score = 15
    if "img_alt_missing" in error_rules:
        a11y_score -= 4
        notes.append("img缺少alt(-4)")
    if "html_lang" in warning_rules:
        a11y_score -= 2
        notes.append("缺少html lang(-2)")
    if "color_contrast" in error_rules:
        a11y_score -= 3
        notes.append("颜色对比度不足(-3)")
    if "focus_visible" in warning_rules:
        a11y_score -= 2
        notes.append("缺少:focus样式(-2)")
    if "aria_label" in warning_rules:
        a11y_score -= 2
        notes.append("交互元素缺少aria-label(-2)")
    if "form_label" in warning_rules:
        a11y_score -= 2
        notes.append("input缺少label(-2)")
    score += max(0, a11y_score)

    # 6. 标题层级 (5分) — M34
    if "heading_hierarchy" not in warning_rules:
        score += 5
    else:
        score += 0
        notes.append("标题层级跳级或多个h1(-5)")

    # 7. 组件状态 (10分) — M35
    if "component_states" not in warning_rules:
        score += 10
    else:
        score += 0
        notes.append("交互组件缺少状态样式(-10)")

    # 8. 动画性能 (10分) — M53: 含入场动画检查（5+5 分）
    anim_score = 10
    if "animation_performance" in warning_rules:
        anim_score -= 5
        notes.append("动画性能待优化(-5)")
    if "scroll_animation" in warning_rules:
        anim_score -= 5
        notes.append("缺少入场动画(-5)")
    score += max(0, anim_score)

    # 9. 设计一致性 (10分) — 检查 hex 颜色数量
    for fname in _os.listdir(cwd):
        if not fname.endswith(".html"):
            continue
        fpath = _os.path.join(cwd, fname)
        if not _os.path.isfile(fpath):
            continue
        try:
            content = open(fpath, "r", encoding="utf-8").read()
        except Exception:
            continue
        hex_colors = set(_re.findall(r"#[0-9A-Fa-f]{6}\b", content))
        design_colors = {
            c for c in hex_colors
            if c.upper() not in ("#000000", "#FFFFFF", "#FFF", "#000")
        }
        if len(design_colors) <= 5:
            score += 10
        else:
            score += 5
            notes.append(f"配色过多({len(design_colors)}种，建议≤5)(-5)")
        break

    if not notes:
        notes.append("设计质量良好")
    return score, notes
