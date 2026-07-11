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


# ---------- M54: placeholder text lint ----------

# 占位文本模式（AI 生成 UI 头号破绽）
# 只检查可见文本（剥离 <script>/<style> 和 HTML 标签后）
_PLACEHOLDER_PATTERNS: list[tuple[str, str]] = [
    (r"lorem\s+ipsum", "Lorem ipsum 占位文本"),
    (r"示例(标题|文本|内容|文字|描述)", "中文示例占位文本"),
    (r"(内容|标题|文字|描述)\1{2,}", "重复中文占位词"),
    (r"sample\s*(text|content|title|description)", "英文 Sample 占位文本"),
    (r"click\s+here", "无信息量按钮文案 'Click here'"),
    (r"点击(这里|此处|这里了)", "无信息量按钮文案 '点击这里'"),
    (r"(your|这里)\s*(content|text|title)\s*(here|这里|)", "Your content here 占位"),
    (r"placeholder\s*(text|content)?", "Placeholder 占位文本"),
    (r"占位(文本|内容|文字)", "中文占位文本"),
    (r"(todo|tbd|fixme)", "未完成标记（TODO/TBD/FIXME）"),
]


def _extract_visible_text(html: str) -> str:
    """提取 HTML 可见文本（去除 script/style/标签）。"""
    import re as _re
    # 去 script/style 块
    text = _re.sub(r"<(script|style)\b[^>]*>.*?</\1>", "", html, flags=_re.IGNORECASE | _re.DOTALL)
    # 去 HTML 标签
    text = _re.sub(r"<[^>]+>", " ", text)
    # 压缩空白
    text = _re.sub(r"\s+", " ", text).strip()
    return text


def check_placeholder_text(cwd: str) -> list[dict]:
    """M54: 检测 AI 生成 UI 的头号破绽——占位文本。

    检测模式：
    - Lorem ipsum（经典占位）
    - 示例标题/示例文本/示例内容（中文占位）
    - 内容内容内容/标题标题（重复中文词）
    - Sample text/content（英文占位）
    - Click here / 点击这里（无信息量按钮文案）
    - Placeholder / 占位文本
    - TODO / TBD / FIXME（未完成标记）
    - 连续重复字符 ≥5（xxxxx / ..... / -----）

    只检查可见文本，不检查属性/CSS/JS。
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

        visible = _extract_visible_text(content)

        found_patterns: list[str] = []
        for pattern, desc in _PLACEHOLDER_PATTERNS:
            if _re.search(pattern, visible, _re.IGNORECASE):
                found_patterns.append(desc)

        # 重复字符检测：同一字符连续出现 ≥5 次
        if _re.search(r"(.)\1{4,}", visible) and not _re.match(r"^\s*$", visible):
            # 排除合法空白
            found_patterns.append("重复字符占位（≥5个相同字符连续）")

        if found_patterns:
            violations.append({
                "rule": "placeholder_text",
                "severity": "error",
                "file": fname,
                "message": f"检测到占位文本: {', '.join(found_patterns)}",
            })

    return violations


# 占位文本替换映射（只作用于文本节点，不碰属性/CSS/JS）
_PLACEHOLDER_REPLACEMENTS: list[tuple[str, str]] = [
    (r"lorem\s+ipsum(?:\s+\w+)*", "这是页面内容区域，请替换为实际文案"),
    (r"示例标题", "页面标题"),
    (r"示例(文本|内容|文字|描述)", "页面内容"),
    (r"(内容|标题|文字|描述)\1{2,}", "页面内容"),
    (r"sample\s*(?:text|content|title|description)", "Page content"),
    (r"click\s+here", "了解更多"),
    (r"点击(这里|此处|这里了)", "查看详情"),
    (r"(?:your|这里)\s*(?:content|text|title)\s*(?:here|这里|)", "Page content"),
    (r"placeholder\s*(?:text|content)?", "页面内容"),
    (r"占位(文本|内容|文字)", "页面内容"),
    (r"(?:TODO|TBD|FIXME)", ""),
]


def auto_fix_placeholder_text(cwd: str) -> bool:
    """M55: 替换占位文本为中性文案（只修改文本节点，不碰属性/CSS/JS）。

    替换映射：
    - Lorem ipsum... → 中性中文文案
    - 示例标题/文本/内容 → 页面标题/页面内容
    - 重复中文词 → 页面内容
    - Sample text/content → Page content
    - Click here → 了解更多
    - 点击这里 → 查看详情
    - Your content here → Page content
    - placeholder → 页面内容
    - 占位文本 → 页面内容
    - TODO/TBD/FIXME → 移除
    - 连续重复字符≥5 → 页面内容
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

        # 先检查是否有违规
        violations = check_placeholder_text(_os.path.dirname(fpath))
        has_violation = any(
            v["file"] == fname and v["rule"] == "placeholder_text"
            for v in violations
        )
        if not has_violation:
            continue

        # 保存 script/style 块，避免替换其中的内容
        saved_blocks: list[str] = []

        def _save_block(m):
            saved_blocks.append(m.group(0))
            return f"\x00SAVED_BLOCK_{len(saved_blocks) - 1}\x00"

        protected = _re.sub(
            r"<(?:script|style)\b[^>]*>.*?</(?:script|style)>",
            _save_block, content, flags=_re.IGNORECASE | _re.DOTALL,
        )

        # 只在文本节点（> 和 < 之间）做替换
        parts = _re.split(r"(<[^>]+>)", protected)
        for i, part in enumerate(parts):
            if part.startswith("<"):
                continue  # 标签，跳过
            new_part = part
            for pattern, replacement in _PLACEHOLDER_REPLACEMENTS:
                new_part = _re.sub(pattern, replacement, new_part, flags=_re.IGNORECASE)
            # 重复字符检测：≥5 个相同字符 → 页面内容
            new_part = _re.sub(r"(.)\1{4,}", "页面内容", new_part)
            parts[i] = new_part

        new_content = "".join(parts)

        # 恢复 script/style 块
        for idx, block in enumerate(saved_blocks):
            new_content = new_content.replace(f"\x00SAVED_BLOCK_{idx}\x00", block)

        if new_content != content:
            with open(fpath, "w", encoding="utf-8") as f:
                f.write(new_content)
            changed = True

    return changed


def check_empty_links(cwd: str) -> list[dict]:
    """M56: 检测空链接/无效 href。

    AI 生成 UI 常见破绽：
    - href="#" （空锚点）
    - href="javascript:void(0)" （过时模式）
    - <a> 缺少 href 属性

    合法链接（不报违规）：
    - /path（相对路径）
    - https://... （外部 URL）
    - #section-id（锚点跳转，有对应 id 存在）
    - mailto: / tel:
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

        # 提取所有 id 用于锚点验证
        ids = set(_re.findall(r'\bid\s*=\s*["\']([^"\']+)["\']', content, _re.IGNORECASE))

        # 找所有 <a> 标签
        for match in _re.finditer(r"<a\b([^>]*)>", content, _re.IGNORECASE):
            attrs = match.group(1) or ""

            # 提取 href
            href_match = _re.search(r'\bhref\s*=\s*["\']([^"\']*)["\']', attrs, _re.IGNORECASE)

            if not href_match:
                # 无 href 属性
                violations.append({
                    "rule": "empty_link",
                    "severity": "warning",
                    "file": fname,
                    "message": "<a> 缺少 href 属性",
                })
                continue

            href = href_match.group(1).strip()

            # 空 href
            if not href:
                violations.append({
                    "rule": "empty_link",
                    "severity": "warning",
                    "file": fname,
                    "message": "href 为空字符串",
                })
                continue

            # href="#" — 纯锚点无目标
            if href == "#":
                violations.append({
                    "rule": "empty_link",
                    "severity": "warning",
                    "file": fname,
                    "message": "href='#' 空锚点链接",
                })
                continue

            # href="#section" — 锚点跳转，检查目标 id 是否存在
            if href.startswith("#"):
                anchor_id = href[1:]
                if anchor_id and anchor_id not in ids:
                    violations.append({
                        "rule": "empty_link",
                        "severity": "warning",
                        "file": fname,
                        "message": f"href='{href}' 锚点目标 id 不存在",
                    })
                # 锚点存在则合法，不报
                continue

            # javascript: 协议
            if href.lower().startswith("javascript:"):
                violations.append({
                    "rule": "empty_link",
                    "severity": "warning",
                    "file": fname,
                    "message": "href 使用 javascript: 协议（过时模式）",
                })
                continue

            # 其他合法链接：/path, https://, http://, mailto:, tel:
            # 不报违规

    return violations


def check_inline_styles(cwd: str) -> list[dict]:
    """M57: 检测内联样式 style="..."（AI 应该用 CSS class 而非 inline style）。

    内联样式是 AI 生成 UI 的常见破绽：
    - 难以维护（无法全局修改）
    - 违反关注点分离原则
    - 无法利用 CSS 变量和媒体查询

    注意：<style> 标签内的 CSS 不是内联样式，不报违规。
    只检测 HTML 标签上的 style="..." 属性。
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

        # 先剥离 <style>...</style> 块，避免误报
        stripped = _re.sub(
            r"<style\b[^>]*>.*?</style>", "", content,
            flags=_re.IGNORECASE | _re.DOTALL,
        )

        # 找所有 HTML 标签上的 style="..." 属性
        # 匹配 <tag ... style="..." ...>
        for match in _re.finditer(
            r"<(\w+)\b[^>]*\bstyle\s*=\s*[\"'][^\"']*[\"'][^>]*>",
            stripped, _re.IGNORECASE,
        ):
            tag_name = match.group(1)
            # 忽略 <style> 标签本身（虽然已剥离，双保险）
            if tag_name.lower() == "style":
                continue
            violations.append({
                "rule": "inline_style",
                "severity": "warning",
                "file": fname,
                "message": f"<{tag_name}> 使用内联样式 style=\"...\"（应改用 CSS class）",
            })

    return violations


def check_console_log(cwd: str) -> list[dict]:
    """M58: 检测 <script> 块中的 console.log 调试残留。

    AI 生成代码常遗留 console.log 调试语句，这是生产环境的破绽。
    只检测 <script>...</script> 块内的 console.log，不检测文本内容。
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

        # 只提取 <script> 块内容
        script_blocks = _re.findall(
            r"<script\b[^>]*>(.*?)</script>",
            content, _re.IGNORECASE | _re.DOTALL,
        )

        for block in script_blocks:
            # 找所有 console.log 调用
            logs = _re.findall(r"console\.log\s*\(", block)
            for _ in logs:
                violations.append({
                    "rule": "console_log",
                    "severity": "warning",
                    "file": fname,
                    "message": "<script> 中有 console.log 调试残留（生产环境应移除）",
                })

    return violations


def _remove_console_log_from_js(js: str) -> str:
    """从 JS 代码中移除所有 console.log(...) 语句。

    使用括号计数法处理嵌套括号，移除语句后的分号和换行。
    保留其他 JS 代码不变。
    """
    import re as _re

    result: list[str] = []
    i = 0
    while i < len(js):
        match = _re.search(r"console\.log\s*\(", js[i:])
        if not match:
            result.append(js[i:])
            break

        # 添加 console.log 之前的内容
        start = i + match.start()
        result.append(js[i:start])

        # 找到匹配的右括号（处理嵌套括号）
        paren_open = i + match.end() - 1  # 指向 (
        depth = 1
        j = paren_open + 1
        while j < len(js) and depth > 0:
            if js[j] == "(":
                depth += 1
            elif js[j] == ")":
                depth -= 1
            j += 1
        # j 指向 ) 之后

        # 跳过尾随空格和分号
        while j < len(js) and js[j] in " \t":
            j += 1
        if j < len(js) and js[j] == ";":
            j += 1
        # 跳过行尾换行（只跳一个，避免吞多行）
        if j < len(js) and js[j] == "\n":
            j += 1

        i = j

    return "".join(result)


def check_zindex_chaos(cwd: str) -> list[dict]:
    """M69: 检测 z-index 堆叠混乱。

    AI 生成 CSS 常见破绽：z-index 军备竞赛（9999/999/500）或过多不同值。
    报 warning 当：
    - 任意 z-index 值 > 100（典型 AI hack: 9999/999/500）
    - 或超过 5 个不同 z-index 值（堆叠混乱，缺系统性）
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

        # 提取所有 z-index: <number> 声明
        matches = _re.findall(r"z-index\s*:\s*(\d+)", content, _re.IGNORECASE)
        if not matches:
            continue

        values = [int(m) for m in matches]
        distinct = sorted(set(values))

        # 规则1: 任意值 > 100
        high_values = [v for v in distinct if v > 100]
        if high_values:
            violations.append({
                "rule": "zindex_chaos",
                "severity": "warning",
                "file": fname,
                "message": f"z-index 值过大（>100）：{high_values}，应使用 0/10/20 系统化层级",
            })
            continue  # 已报违规，不再重复报

        # 规则2: 超过 5 个不同值
        if len(distinct) > 5:
            violations.append({
                "rule": "zindex_chaos",
                "severity": "warning",
                "file": fname,
                "message": f"z-index 有 {len(distinct)} 个不同值：{distinct}，应精简到 ≤5 个系统化层级",
            })

    return violations


def check_border_radius_chaos(cwd: str) -> list[dict]:
    """M70: 检测 border-radius 一致性问题。

    AI 生成 CSS 常见破绽：随机 border-radius 值（7px/13px/25px）无系统性。
    标准值集合：{0, 2, 4, 6, 8, 12, 16, 24, 32}（px）。
    报 warning 当：
    - 任意 px 值不在标准集合中
    - 或超过 6 个不同 border-radius 值
    """
    import os as _os
    import re as _re

    STANDARD_RADII = {0, 2, 4, 6, 8, 12, 16, 24, 32}
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

        # 提取所有 border-radius: <number>px 声明
        matches = _re.findall(r"border-radius\s*:\s*(\d+)px", content, _re.IGNORECASE)
        if not matches:
            continue

        values = [int(m) for m in matches]
        distinct = sorted(set(values))

        # 规则1: 非标准值
        non_standard = [v for v in distinct if v not in STANDARD_RADII and v <= 100]
        if non_standard:
            violations.append({
                "rule": "border_radius_chaos",
                "severity": "warning",
                "file": fname,
                "message": f"非标准 border-radius 值：{non_standard}，应使用 0/2/4/6/8/12/16/24/32 系统化圆角",
            })
            continue

        # 规则2: 超过 6 个不同值
        if len(distinct) > 6:
            violations.append({
                "rule": "border_radius_chaos",
                "severity": "warning",
                "file": fname,
                "message": f"border-radius 有 {len(distinct)} 个不同值：{distinct}，应精简到 ≤6 个系统化圆角",
            })

    return violations


def auto_fix_console_log(cwd: str) -> bool:
    """M59: 移除 <script> 块中的 console.log 调试残留。

    只处理 <script>...</script> 块内的 console.log 调用，
    使用括号计数法移除整个语句（含参数和分号），保留其他 JS 代码。
    幂等：无 console.log 时返回 False 不修改。
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

        # 先检查是否有 console.log 违规
        violations = check_console_log(_os.path.dirname(fpath))
        has_violation = any(
            v["file"] == fname and v["rule"] == "console_log"
            for v in violations
        )
        if not has_violation:
            continue

        # 处理每个 <script> 块，移除 console.log 语句
        def _process_script(m):
            script_open = m.group(1)
            script_body = m.group(2)
            script_close = m.group(3)
            new_body = _remove_console_log_from_js(script_body)
            return script_open + new_body + script_close

        new_content = _re.sub(
            r"(<script\b[^>]*>)(.*?)(</script>)",
            _process_script,
            content, flags=_re.IGNORECASE | _re.DOTALL,
        )

        if new_content != content:
            with open(fpath, "w", encoding="utf-8") as f:
                f.write(new_content)
            changed = True

    return changed


def auto_fix_empty_links(cwd: str) -> bool:
    """M60: 修复空链接/无效 href。

    将 href="#" / href="javascript:void(0)" / href="" / href="#nonexistent"
    的 <a> 标签转为 <span>（保留其他属性和内容），移除 href 属性。
    这样 check_empty_links 不再报告违规（因为不再是 <a> 标签）。

    缺少 href 的 <a> 也转为 <span>。
    幂等：无空链接时返回 False 不修改。
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

        # 先检查是否有违规
        violations = check_empty_links(_os.path.dirname(fpath))
        has_violation = any(
            v["file"] == fname and v["rule"] == "empty_link"
            for v in violations
        )
        if not has_violation:
            continue

        # 提取所有 id 用于判断锚点是否有效
        ids = set(_re.findall(r'\bid\s*=\s*["\']([^"\']+)["\']', content, _re.IGNORECASE))

        def _is_bad_href(opening_tag: str) -> bool:
            """判断 <a> 标签的 href 是否为空/无效。"""
            href_match = _re.search(r'\bhref\s*=\s*["\']([^"\']*)["\']', opening_tag, _re.IGNORECASE)
            if not href_match:
                return True  # 无 href
            href = href_match.group(1).strip()
            if not href:
                return True  # 空字符串
            if href == "#":
                return True  # 纯锚点
            if href.startswith("#") and href[1:] and href[1:] not in ids:
                return True  # 不存在的锚点
            if href.lower().startswith("javascript:"):
                return True  # javascript: 协议
            return False

        def _fix_link(m):
            opening_tag = m.group(1)
            inner_content = m.group(2)

            if not _is_bad_href(opening_tag):
                return m.group(0)  # 好链接，不改

            # 将 <a> 转为 <span>，移除 href 属性
            new_opening = _re.sub(r"<a\b", "<span", opening_tag, flags=_re.IGNORECASE)
            new_opening = _re.sub(
                r'\s*href\s*=\s*["\'][^"\']*["\']',
                "",
                new_opening,
                flags=_re.IGNORECASE,
            )
            return new_opening + inner_content + "</span>"

        new_content = _re.sub(
            r"(<a\b[^>]*>)(.*?)(</a>)",
            _fix_link,
            content, flags=_re.IGNORECASE | _re.DOTALL,
        )

        if new_content != content:
            with open(fpath, "w", encoding="utf-8") as f:
                f.write(new_content)
            changed = True

    return changed


def auto_fix_inline_styles(cwd: str) -> bool:
    """M61: 将内联 style="..." 提取为 CSS class。

    策略：
    1. 保护 <style> 块避免误匹配
    2. 找所有带 style="..." 的 HTML 标签
    3. 用 md5(style内容)[:8] 生成 class 名 "auto-style-xxxxxxxx"
    4. 移除 style="..." 属性，追加 class 到元素
    5. 将 CSS 规则添加到 <style> 块（已有则追加，无则新建）
    6. 相同样式复用同一 class（去重）

    幂等：无内联样式时返回 False 不修改。
    """
    import os as _os
    import re as _re
    import hashlib as _hashlib

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

        # 先检查是否有违规
        violations = check_inline_styles(_os.path.dirname(fpath))
        has_violation = any(
            v["file"] == fname and v["rule"] == "inline_style"
            for v in violations
        )
        if not has_violation:
            continue

        # 保护 <style> 块
        saved_blocks: list[str] = []

        def _save_block(m):
            saved_blocks.append(m.group(0))
            return f"\x00STYLE_BLOCK_{len(saved_blocks) - 1}\x00"

        protected = _re.sub(
            r"<style\b[^>]*>.*?</style>",
            _save_block, content, flags=_re.IGNORECASE | _re.DOTALL,
        )

        # style 内容 → class 名映射（去重）
        style_to_class: dict[str, str] = {}
        css_rules: list[str] = []

        def _process_tag(m):
            full_tag = m.group(0)

            # 提取 style="..."
            style_match = _re.search(
                r'\s*style\s*=\s*["\']([^"\']*)["\']',
                full_tag, _re.IGNORECASE,
            )
            if not style_match:
                return full_tag

            style_content = style_match.group(1).strip()
            if not style_content:
                # 空样式，直接移除
                return full_tag[:style_match.start()] + full_tag[style_match.end():]

            # 生成 class 名（基于 style 内容的 hash）
            style_hash = _hashlib.md5(style_content.encode()).hexdigest()[:8]
            class_name = f"auto-style-{style_hash}"

            # 记录 CSS 规则（去重）
            if style_content not in style_to_class:
                style_to_class[style_content] = class_name
                css_rules.append(f".{class_name} {{ {style_content} }}")
            else:
                class_name = style_to_class[style_content]

            # 移除 style="..." 属性
            new_tag = full_tag[:style_match.start()] + full_tag[style_match.end():]

            # 添加 class
            class_match = _re.search(
                r'\bclass\s*=\s*["\']([^"\']*)["\']',
                new_tag, _re.IGNORECASE,
            )
            if class_match:
                # 追加到现有 class
                existing_class = class_match.group(1)
                new_class = f"{existing_class} {class_name}"
                new_tag = (
                    new_tag[:class_match.start()]
                    + f'class="{new_class}"'
                    + new_tag[class_match.end():]
                )
            else:
                # 添加新 class 属性（在标签名后）
                new_tag = _re.sub(
                    r"(<\w+)",
                    rf'\1 class="{class_name}"',
                    new_tag,
                    count=1,
                )

            return new_tag

        # 只匹配带 style= 的标签
        new_protected = _re.sub(
            r"<\w+\b[^>]*\bstyle\s*=\s*[\"'][^\"']*[\"'][^>]*>",
            _process_tag,
            protected,
            flags=_re.IGNORECASE,
        )

        # 恢复 <style> 块
        for idx, block in enumerate(saved_blocks):
            new_protected = new_protected.replace(f"\x00STYLE_BLOCK_{idx}\x00", block)

        # 添加 CSS 规则到 <style> 块
        if css_rules:
            css_block = "\n".join(css_rules)
            style_block_match = _re.search(
                r"(<style\b[^>]*>)(.*?)(</style>)",
                new_protected, _re.IGNORECASE | _re.DOTALL,
            )
            if style_block_match:
                # 追加到现有 <style> 块
                existing_css = style_block_match.group(2)
                new_css = existing_css.rstrip() + "\n" + css_block + "\n"
                new_protected = (
                    new_protected[:style_block_match.start()]
                    + style_block_match.group(1)
                    + new_css
                    + style_block_match.group(3)
                    + new_protected[style_block_match.end():]
                )
            else:
                # 在 </head> 前创建新的 <style> 块
                head_close = _re.search(r"</head>", new_protected, _re.IGNORECASE)
                style_tag = f"<style>\n{css_block}\n</style>\n"
                if head_close:
                    insert_pos = head_close.start()
                    new_protected = (
                        new_protected[:insert_pos]
                        + style_tag
                        + new_protected[insert_pos:]
                    )
                else:
                    # 没有 <head>，在文件开头添加
                    new_protected = style_tag + new_protected

        if new_protected != content:
            with open(fpath, "w", encoding="utf-8") as f:
                f.write(new_protected)
            changed = True

    return changed


# ---------- M62: 颜色对比度自动修复 ----------


def _adjust_color_for_contrast(text_hex: str, bg_hex: str, target_ratio: float = 4.5) -> "str | None":
    """调整 text_hex 使其与 bg_hex 的对比度 >= target_ratio。

    根据 bg 亮度决定向黑（#000000）还是向白（#FFFFFF）混合，
    二分搜索最小调整量。返回新 hex（大写），无法达标时返回 None。
    """
    bg_lum = relative_luminance(hex_to_rgb(bg_hex))
    # bg 亮 → 文本向黑混合；bg 暗 → 文本向白混合
    # 阈值 0.179：此亮度下纯黑/纯白文本对比度恰约 4.58:1，保证极端色可达标
    target_hex = "#000000" if bg_lum > 0.179 else "#FFFFFF"
    text_rgb = hex_to_rgb(text_hex)
    target_rgb = hex_to_rgb(target_hex)

    def blend_hex(t: float) -> str:
        r = round(text_rgb[0] * (1 - t) + target_rgb[0] * t)
        g = round(text_rgb[1] * (1 - t) + target_rgb[1] * t)
        b = round(text_rgb[2] * (1 - t) + target_rgb[2] * t)
        return f"#{r:02X}{g:02X}{b:02X}"

    # 确认极端色能达标
    try:
        if contrast_ratio(blend_hex(1.0), bg_hex) < target_ratio:
            return None
    except Exception:
        return None

    # 二分搜索最小 t 使对比度达标
    lo, hi = 0.0, 1.0
    for _ in range(50):
        mid = (lo + hi) / 2
        try:
            r = contrast_ratio(blend_hex(mid), bg_hex)
        except Exception:
            lo = mid
            continue
        if r >= target_ratio:
            hi = mid
        else:
            lo = mid
    return blend_hex(hi)


def auto_fix_color_contrast(cwd: str) -> bool:
    """M62: 自动调整低对比度颜色对，使其满足 WCAG AA 标准 (>=4.5:1)。

    遍历 HTML 文件的 CSS 规则块 { ... }，找到 background + color 配对，
    计算对比度。低于 4.5:1 时：
    - 浅色背景 → 加深文本颜色（向 #000000 混合）
    - 深色背景 → 提亮文本颜色（向 #FFFFFF 混合）
    二分搜索找到最小调整量，保证幂等性（修复后再次运行不再修改）。
    """
    import os as _os
    import re as _re

    changed = False
    if not _os.path.exists(cwd):
        return False

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
        # 收集所有需要替换的块（start, end, new_block），逆序应用避免偏移
        replacements: list[tuple[int, int, str]] = []
        for block_match in _re.finditer(r"\{[^{}]*\}", content):
            block = block_match.group(0)
            bg_match = _re.search(
                r"(?:background-color|background)\s*:\s*(#[0-9A-Fa-f]{6})",
                block, _re.IGNORECASE,
            )
            color_match = _re.search(
                r"(?<!background-)color\s*:\s*(#[0-9A-Fa-f]{6})",
                block, _re.IGNORECASE,
            )
            if not (bg_match and color_match):
                continue
            bg_hex = bg_match.group(1)
            text_hex = color_match.group(1)
            try:
                ratio = contrast_ratio(text_hex, bg_hex)
            except Exception:
                continue
            if ratio >= 4.5:
                continue
            new_text_hex = _adjust_color_for_contrast(text_hex, bg_hex, 4.5)
            if not new_text_hex or new_text_hex.upper() == text_hex.upper():
                continue
            # 仅替换 color 属性内的 hex 值，保留原格式
            old_color_str = color_match.group(0)
            new_color_str = old_color_str.replace(text_hex, new_text_hex)
            new_block = block[:color_match.start()] + new_color_str + block[color_match.end():]
            replacements.append((block_match.start(), block_match.end(), new_block))

        # 逆序应用替换，避免偏移
        for start, end, new_block in sorted(replacements, key=lambda x: x[0], reverse=True):
            new_content = new_content[:start] + new_block + new_content[end:]

        if new_content != content:
            with open(fpath, "w", encoding="utf-8") as f:
                f.write(new_content)
            changed = True

    return changed


def auto_fix_zindex(cwd: str) -> bool:
    """M69: 规范化 z-index 值为 0/10/20/30... 系统化层级。

    收集所有 z-index 值，排序后按排名映射到 10 的倍数。
    保留堆叠顺序，消除 9999/999 等 AI hack 和过多不同值。
    幂等：规范化后再次运行不修改（0/10/20 已是 10 的倍数）。
    """
    import os as _os
    import re as _re

    changed = False
    if not _os.path.exists(cwd):
        return False

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

        # 先检查是否有违规
        violations = check_zindex_chaos(_os.path.dirname(fpath))
        has_violation = any(
            v["file"] == fname and v["rule"] == "zindex_chaos"
            for v in violations
        )
        if not has_violation:
            continue

        # 收集所有 z-index 值，排序去重
        matches = _re.findall(r"z-index\s*:\s*(\d+)", content, _re.IGNORECASE)
        distinct = sorted(set(int(m) for m in matches))

        # 映射：按排名 → rank * 10
        value_map = {val: idx * 10 for idx, val in enumerate(distinct)}

        # 替换每个 z-index 值
        def _replace_zindex(m):
            val = int(m.group(1))
            return f"z-index: {value_map[val]}"

        new_content = _re.sub(
            r"z-index\s*:\s*(\d+)",
            _replace_zindex,
            content,
        )

        if new_content != content:
            with open(fpath, "w", encoding="utf-8") as f:
                f.write(new_content)
            changed = True

    return changed


def auto_fix_border_radius(cwd: str) -> bool:
    """M70: 规范化 border-radius 值到标准集合 {0,2,4,6,8,12,16,24,32}。

    非标准值映射到最近的标准值（7→8, 13→12, 25→24）。
    消除 AI 生成的随机圆角值，建立系统化圆角层级。
    幂等：标准值再次运行不修改（已是标准集合内的值）。
    """
    import os as _os
    import re as _re

    STANDARD_RADII = (0, 2, 4, 6, 8, 12, 16, 24, 32)

    def _nearest_standard(val: int) -> int:
        """返回标准集合中最近的值（距离相等时取较大值，符合四舍五入惯例）。"""
        best = STANDARD_RADII[0]
        best_dist = abs(best - val)
        for s in STANDARD_RADII[1:]:
            d = abs(s - val)
            if d < best_dist or (d == best_dist and s > best):
                best, best_dist = s, d
        return best

    changed = False
    if not _os.path.exists(cwd):
        return False

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

        # 先检查是否有违规
        violations = check_border_radius_chaos(_os.path.dirname(fpath))
        has_violation = any(
            v["file"] == fname and v["rule"] == "border_radius_chaos"
            for v in violations
        )
        if not has_violation:
            continue

        # 替换每个非标准 border-radius px 值为最近标准值
        def _replace_radius(m):
            val = int(m.group(1))
            new_val = _nearest_standard(val)
            return f"border-radius: {new_val}px"

        new_content = _re.sub(
            r"border-radius\s*:\s*(\d+)px",
            _replace_radius,
            content,
            flags=_re.IGNORECASE,
        )

        if new_content != content:
            with open(fpath, "w", encoding="utf-8") as f:
                f.write(new_content)
            changed = True

    return changed


# ---------- M71: box-shadow elevation 混乱检测 + auto-fix ----------

# 标准 elevation scale（blur 值 → 完整 shadow 值）
_STANDARD_SHADOW_BLURS = (2, 6, 15, 25)
_STANDARD_SHADOWS: dict[int, str] = {
    2: "0 1px 2px rgba(0,0,0,0.05)",     # sm
    6: "0 4px 6px rgba(0,0,0,0.07)",      # md
    15: "0 10px 15px rgba(0,0,0,0.1)",     # lg
    25: "0 20px 25px rgba(0,0,0,0.15)",    # xl
}


def _extract_shadow_blur(shadow_val: str) -> "int | None":
    """从 box-shadow 值中提取 blur radius（第3个空格分隔 token 的 px 值）。

    box-shadow 格式: offset-x offset-y blur spread color
    例: "0 3px 7px rgba(0,0,0,0.1)" → blur=7
    """
    tokens = shadow_val.strip().split()
    # 跳过 inset 关键词
    tokens = [t for t in tokens if t.lower() != "inset"]
    if len(tokens) < 3:
        return None
    blur_token = tokens[2]
    # 提取数字（可能带 - 前缀和 px 后缀）
    import re as _re
    m = _re.match(r"-?(\d+)px", blur_token)
    if m:
        return int(m.group(1))
    return None


def check_box_shadow_chaos(cwd: str) -> list[dict]:
    """M71: 检测 box-shadow elevation 混乱。

    AI 生成 CSS 常见破绽：随机 box-shadow 值（3px/7px/13px blur）无系统性 elevation scale。
    标准 blur 值集合：{2, 6, 15, 25}（对应 sm/md/lg/xl）。
    报 warning 当：
    - 任意 blur 值不在标准集合中
    - 或超过 4 个不同 blur 值（elevation 过多）
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
        # 匹配 box-shadow: <value>;
        shadow_matches = _re.findall(
            r"box-shadow\s*:\s*([^;]+)", content, _re.IGNORECASE,
        )
        if not shadow_matches:
            continue
        blurs: list[int] = []
        for shadow_val in shadow_matches:
            blur = _extract_shadow_blur(shadow_val.strip())
            if blur is not None:
                blurs.append(blur)
        if not blurs:
            continue
        distinct = sorted(set(blurs))
        non_standard = [b for b in distinct if b not in _STANDARD_SHADOW_BLURS]
        if non_standard:
            violations.append({
                "rule": "box_shadow_chaos",
                "severity": "warning",
                "file": fname,
                "message": f"非标准 box-shadow blur 值：{non_standard}，应使用 2/6/15/25 系统化 elevation",
            })
            continue
        if len(distinct) > 4:
            violations.append({
                "rule": "box_shadow_chaos",
                "severity": "warning",
                "file": fname,
                "message": f"box-shadow 有 {len(distinct)} 个不同 blur 值：{distinct}，应精简到 ≤4 个系统化 elevation",
            })
    return violations


def auto_fix_box_shadow(cwd: str) -> bool:
    """M71: 规范化 box-shadow 值到标准 elevation scale。

    非标准 blur 值映射到最近标准值（距离相等取较大值），并替换完整 shadow 值。
    标准 scale: 2px(sm) / 6px(md) / 15px(lg) / 25px(xl)。
    幂等：标准值再次运行不修改。
    """
    import os as _os
    import re as _re

    def _nearest_standard_blur(val: int) -> int:
        best = _STANDARD_SHADOW_BLURS[0]
        best_dist = abs(best - val)
        for s in _STANDARD_SHADOW_BLURS[1:]:
            d = abs(s - val)
            if d < best_dist or (d == best_dist and s > best):
                best, best_dist = s, d
        return best

    changed = False
    if not _os.path.exists(cwd):
        return False

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

        # 先检查是否有违规
        violations = check_box_shadow_chaos(_os.path.dirname(fpath))
        has_violation = any(
            v["file"] == fname and v["rule"] == "box_shadow_chaos"
            for v in violations
        )
        if not has_violation:
            continue

        # 替换每个非标准 box-shadow 值
        def _replace_shadow(m):
            shadow_val = m.group(1).strip()
            blur = _extract_shadow_blur(shadow_val)
            if blur is None or blur in _STANDARD_SHADOW_BLURS:
                return m.group(0)  # 不修改
            std_blur = _nearest_standard_blur(blur)
            std_shadow = _STANDARD_SHADOWS[std_blur]
            return f"box-shadow: {std_shadow}"

        new_content = _re.sub(
            r"box-shadow\s*:\s*([^;]+)",
            _replace_shadow,
            content,
            flags=_re.IGNORECASE,
        )

        if new_content != content:
            with open(fpath, "w", encoding="utf-8") as f:
                f.write(new_content)
            changed = True

    return changed


# ---------- M72: transition duration 一致性检测 + auto-fix ----------

# 标准 transition 时长集合（ms）：fast=150, normal=200, slow=300, slower=500
_STANDARD_TRANSITION_MS = (0, 150, 200, 300, 500)


def _parse_duration_to_ms(num_str: str, unit: str) -> int:
    """把时长值+单位转为毫秒整数。"""
    val = float(num_str)
    return int(val * 1000) if unit == "s" else int(val)


def _ms_to_str(ms: int, unit: str) -> str:
    """把毫秒值转回带单位的字符串。"""
    if unit == "s":
        return f"{ms / 1000:g}s"
    return f"{ms}ms"


def check_transition_chaos(cwd: str) -> list[dict]:
    """M72: 检测 transition duration 一致性问题。

    AI 生成 CSS 常见破绽：随机过渡时长（0.25s/0.35s/0.45s）无系统性。
    标准时长集合（ms）：{0, 150, 200, 300, 500}（对应 instant/fast/normal/slow/slower）。
    报 warning 当：
    - 任意 duration 值不在标准集合中
    - 或超过 4 个不同 duration 值
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
        # 匹配 transition: <value>; （不含 transition-duration 等子属性）
        transition_matches = _re.findall(
            r"\btransition\s*:\s*([^;]+)", content, _re.IGNORECASE,
        )
        if not transition_matches:
            continue
        durations: list[int] = []
        for tval in transition_matches:
            # 提取所有 duration 模式：数字 + s/ms
            dur_matches = _re.findall(r"(\d+(?:\.\d+)?)(ms|s)\b", tval)
            for num_str, unit in dur_matches:
                durations.append(_parse_duration_to_ms(num_str, unit))
        if not durations:
            continue
        distinct = sorted(set(durations))
        non_standard = [d for d in distinct if d not in _STANDARD_TRANSITION_MS]
        if non_standard:
            violations.append({
                "rule": "transition_chaos",
                "severity": "warning",
                "file": fname,
                "message": f"非标准 transition duration：{non_standard}ms，应使用 0/150/200/300/500 系统化时长",
            })
            continue
        if len(distinct) > 4:
            violations.append({
                "rule": "transition_chaos",
                "severity": "warning",
                "file": fname,
                "message": f"transition 有 {len(distinct)} 个不同 duration：{distinct}ms，应精简到 ≤4 个系统化时长",
            })
    return violations


def auto_fix_transition(cwd: str) -> bool:
    """M72: 规范化 transition duration 到标准集合 {0,150,200,300,500}ms。

    非标准值映射到最近标准值（距离相等取较大值），保留原单位（s/ms）。
    幂等：标准值再次运行不修改。
    """
    import os as _os
    import re as _re

    def _nearest_duration(ms: int) -> int:
        best = _STANDARD_TRANSITION_MS[0]
        best_dist = abs(best - ms)
        for s in _STANDARD_TRANSITION_MS[1:]:
            d = abs(s - ms)
            if d < best_dist or (d == best_dist and s > best):
                best, best_dist = s, d
        return best

    changed = False
    if not _os.path.exists(cwd):
        return False

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

        # 先检查是否有违规
        violations = check_transition_chaos(_os.path.dirname(fpath))
        has_violation = any(
            v["file"] == fname and v["rule"] == "transition_chaos"
            for v in violations
        )
        if not has_violation:
            continue

        # 在每个 transition: <value>; 块内替换非标准 duration
        def _fix_transition_block(m):
            prefix = m.group(1)  # "transition:" 部分
            tval = m.group(2)    # transition 值

            def _replace_dur(dm):
                num_str = dm.group(1)
                unit = dm.group(2)
                ms = _parse_duration_to_ms(num_str, unit)
                if ms in _STANDARD_TRANSITION_MS:
                    return dm.group(0)  # 已标准
                std_ms = _nearest_duration(ms)
                return _ms_to_str(std_ms, unit)

            new_tval = _re.sub(
                r"(\d+(?:\.\d+)?)(ms|s)\b",
                _replace_dur,
                tval,
            )
            return prefix + new_tval

        new_content = _re.sub(
            r"(\btransition\s*:\s*)([^;]+)",
            _fix_transition_block,
            content,
            flags=_re.IGNORECASE,
        )

        if new_content != content:
            with open(fpath, "w", encoding="utf-8") as f:
                f.write(new_content)
            changed = True

    return changed


# ---------- M73: opacity 一致性检测 + auto-fix ----------

# 标准 opacity 集合：0/0.25/0.5/0.75/1（透明/微透/半透/强透/不透明）
_STANDARD_OPACITIES = (0.0, 0.25, 0.5, 0.75, 1.0)


def check_opacity_chaos(cwd: str) -> list[dict]:
    """M73: 检测 opacity 值一致性。

    AI 生成 CSS 常见破绽：随机 opacity 值（0.3/0.35/0.85/0.9）无系统性。
    标准集合：{0, 0.25, 0.5, 0.75, 1}。
    报 warning 当：
    - 任意 opacity 值不在标准集合中
    - 或超过 5 个不同 opacity 值
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
        # 匹配 opacity: <数字> （不含 fill-opacity 等子属性）
        opacity_matches = _re.findall(
            r"(?<![-\w])opacity\s*:\s*(\d+(?:\.\d+)?)", content, _re.IGNORECASE,
        )
        if not opacity_matches:
            continue
        values = [float(m) for m in opacity_matches]
        distinct = sorted(set(values))
        non_standard = [
            v for v in distinct
            if not any(abs(v - s) < 1e-6 for s in _STANDARD_OPACITIES)
        ]
        if non_standard:
            violations.append({
                "rule": "opacity_chaos",
                "severity": "warning",
                "file": fname,
                "message": f"非标准 opacity 值：{non_standard}，应使用 0/0.25/0.5/0.75/1 系统化透明度",
            })
            continue
        if len(distinct) > 5:
            violations.append({
                "rule": "opacity_chaos",
                "severity": "warning",
                "file": fname,
                "message": f"opacity 有 {len(distinct)} 个不同值：{distinct}，应精简到 ≤5 个系统化透明度",
            })
    return violations


def auto_fix_opacity(cwd: str) -> bool:
    """M73: 规范化 opacity 值到标准集合 {0, 0.25, 0.5, 0.75, 1}。

    非标准值映射到最近标准值（距离相等取较大值）。
    幂等：标准值再次运行不修改。
    """
    import os as _os
    import re as _re

    def _nearest_opacity(val: float) -> float:
        best = _STANDARD_OPACITIES[0]
        best_dist = abs(best - val)
        for s in _STANDARD_OPACITIES[1:]:
            d = abs(s - val)
            if d < best_dist or (d == best_dist and s > best):
                best, best_dist = s, d
        return best

    def _is_standard(val: float) -> bool:
        return any(abs(val - s) < 1e-6 for s in _STANDARD_OPACITIES)

    changed = False
    if not _os.path.exists(cwd):
        return False

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

        # 先检查是否有违规
        violations = check_opacity_chaos(_os.path.dirname(fpath))
        has_violation = any(
            v["file"] == fname and v["rule"] == "opacity_chaos"
            for v in violations
        )
        if not has_violation:
            continue

        # 替换非标准 opacity 值
        def _replace_opacity(m):
            val = float(m.group(1))
            if _is_standard(val):
                return m.group(0)  # 已标准
            std = _nearest_opacity(val)
            return f"opacity: {std:g}"

        new_content = _re.sub(
            r"(?<![-\w])opacity\s*:\s*(\d+(?:\.\d+)?)",
            _replace_opacity,
            content,
            flags=_re.IGNORECASE,
        )

        if new_content != content:
            with open(fpath, "w", encoding="utf-8") as f:
                f.write(new_content)
            changed = True

    return changed


# ---------- M74: font-size 一致性 ----------

_STANDARD_FONT_SIZES = (12, 14, 16, 18, 24, 30, 36, 48, 64, 96)


def check_font_size_chaos(cwd: str) -> list[dict]:
    """M74: 检测 font-size 一致性问题。

    AI 生成 CSS 常见破绽：随机字号（13px/17px/23px/37px）无系统性 type scale。
    标准集合（px）：{12, 14, 16, 18, 24, 30, 36, 48, 64, 96}（Major Third / Perfect Fourth）。

    规则1: 非标准值报 warning。
    规则2: 超过 8 个不同值报 warning（设计系统应有 ≤8 个字号层级）。
    """
    import os as _os
    import re as _re

    violations: list[dict] = []

    if not _os.path.exists(cwd):
        return violations

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

        # 提取所有 font-size: Npx 值（排除 line-height 等其他属性）
        size_matches = _re.findall(
            r"font-size\s*:\s*(\d+)px", content, _re.IGNORECASE,
        )
        if not size_matches:
            continue

        values = [int(m) for m in size_matches]
        distinct = sorted(set(values))

        # 规则1: 非标准值
        non_standard = [v for v in distinct if v not in _STANDARD_FONT_SIZES and v <= 200]
        if non_standard:
            violations.append({
                "rule": "font_size_chaos",
                "severity": "warning",
                "file": fname,
                "message": (
                    f"非标准 font-size 值：{non_standard}px，"
                    f"应使用 12/14/16/18/24/30/36/48/64/96 系统化 type scale"
                ),
            })

        # 规则2: 超过 8 个不同值
        if len(distinct) > 8:
            violations.append({
                "rule": "font_size_chaos",
                "severity": "warning",
                "file": fname,
                "message": (
                    f"font-size 有 {len(distinct)} 个不同值：{distinct}px，"
                    f"应精简到 ≤8 个系统化字号层级"
                ),
            })

    return violations


def auto_fix_font_size(cwd: str) -> bool:
    """M74: 规范化 font-size 值到标准 type scale {12,14,16,18,24,30,36,48,64,96}。"""
    import os as _os
    import re as _re

    def _nearest_font_size(val: int) -> int:
        """返回标准集合中最近的值（距离相等时取较大值）。"""
        best = _STANDARD_FONT_SIZES[0]
        best_dist = abs(best - val)
        for s in _STANDARD_FONT_SIZES[1:]:
            d = abs(s - val)
            if d < best_dist or (d == best_dist and s > best):
                best, best_dist = s, d
        return best

    def _is_standard(val: int) -> bool:
        return val in _STANDARD_FONT_SIZES

    if not _os.path.exists(cwd):
        return False

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

        # 先检查是否有违规
        violations = check_font_size_chaos(_os.path.dirname(fpath))
        has_violation = any(
            v["file"] == fname and v["rule"] == "font_size_chaos"
            for v in violations
        )
        if not has_violation:
            continue

        # 替换非标准 font-size px 值
        def _replace_font_size(m):
            val = int(m.group(1))
            if _is_standard(val):
                return m.group(0)  # 已标准
            std = _nearest_font_size(val)
            return f"font-size: {std}px"

        new_content = _re.sub(
            r"font-size\s*:\s*(\d+)px",
            _replace_font_size,
            content,
            flags=_re.IGNORECASE,
        )

        if new_content != content:
            with open(fpath, "w", encoding="utf-8") as f:
                f.write(new_content)
            changed = True

    return changed


# ---------- M75: line-height 一致性 ----------

_STANDARD_LINE_HEIGHTS = (1.0, 1.25, 1.5, 1.75, 2.0)


def check_line_height_chaos(cwd: str) -> list[dict]:
    """M75: 检测 line-height 一致性问题。

    AI 生成 CSS 常见破绽：随机行高（1.3/1.45/1.67/1.85）无系统性。
    标准集合（无单位）：{1, 1.25, 1.5, 1.75, 2}（WCAG 推荐正文 ≥1.5）。

    规则1: 非标准值报 warning。
    规则2: 超过 5 个不同值报 warning。
    """
    import os as _os
    import re as _re

    violations: list[dict] = []

    if not _os.path.exists(cwd):
        return violations

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

        # 提取无单位 line-height 值（排除 px 值和 normal 关键字）
        lh_matches = _re.findall(
            r"line-height\s*:\s*(\d+(?:\.\d+)?)(?!\s*px)",
            content, _re.IGNORECASE,
        )
        if not lh_matches:
            continue

        values = [float(m) for m in lh_matches]
        distinct = sorted(set(values))

        # 规则1: 非标准值
        non_standard = [
            v for v in distinct
            if not any(abs(v - s) < 1e-6 for s in _STANDARD_LINE_HEIGHTS)
        ]
        if non_standard:
            violations.append({
                "rule": "line_height_chaos",
                "severity": "warning",
                "file": fname,
                "message": (
                    f"非标准 line-height 值：{non_standard}，"
                    f"应使用 1/1.25/1.5/1.75/2 系统化行高"
                ),
            })

        # 规则2: 超过 5 个不同值
        if len(distinct) > 5:
            violations.append({
                "rule": "line_height_chaos",
                "severity": "warning",
                "file": fname,
                "message": (
                    f"line-height 有 {len(distinct)} 个不同值：{distinct}，"
                    f"应精简到 ≤5 个系统化行高"
                ),
            })

    return violations


def auto_fix_line_height(cwd: str) -> bool:
    """M75: 规范化 line-height 值到标准集合 {1, 1.25, 1.5, 1.75, 2}。"""
    import os as _os
    import re as _re

    def _nearest_line_height(val: float) -> float:
        """返回标准集合中最近的值（距离相等时取较大值）。"""
        best = _STANDARD_LINE_HEIGHTS[0]
        best_dist = abs(best - val)
        for s in _STANDARD_LINE_HEIGHTS[1:]:
            d = abs(s - val)
            if d < best_dist or (d == best_dist and s > best):
                best, best_dist = s, d
        return best

    def _is_standard(val: float) -> bool:
        return any(abs(val - s) < 1e-6 for s in _STANDARD_LINE_HEIGHTS)

    if not _os.path.exists(cwd):
        return False

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

        # 先检查是否有违规
        violations = check_line_height_chaos(_os.path.dirname(fpath))
        has_violation = any(
            v["file"] == fname and v["rule"] == "line_height_chaos"
            for v in violations
        )
        if not has_violation:
            continue

        # 替换非标准 line-height 值（无单位，排除 px 值）
        def _replace_line_height(m):
            val = float(m.group(1))
            if _is_standard(val):
                return m.group(0)  # 已标准
            std = _nearest_line_height(val)
            # 格式化：整数不带小数点，非整数保留2位去尾零
            if std == int(std):
                std_str = str(int(std))
            else:
                std_str = f"{std:g}"
            return f"line-height: {std_str}"

        new_content = _re.sub(
            r"line-height\s*:\s*(\d+(?:\.\d+)?)(?!\s*px)",
            _replace_line_height,
            content,
            flags=_re.IGNORECASE,
        )

        if new_content != content:
            with open(fpath, "w", encoding="utf-8") as f:
                f.write(new_content)
            changed = True

    return changed


# ---------- M76: font-weight 一致性 ----------

_STANDARD_FONT_WEIGHTS = (100, 200, 300, 400, 500, 600, 700, 800, 900)


def check_font_weight_chaos(cwd: str) -> list[dict]:
    """M76: 检测 font-weight 一致性问题。

    AI 生成 CSS 常见破绽：非标准字重（350/450/550/650）无系统性。
    标准集合：{100, 200, 300, 400, 500, 600, 700, 800, 900}（CSS 标准 100 倍数）。

    规则1: 非标准值报 warning。
    规则2: 超过 6 个不同值报 warning（设计系统应有 ≤6 个字重层级）。
    """
    import os as _os
    import re as _re

    violations: list[dict] = []

    if not _os.path.exists(cwd):
        return violations

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

        # 只提取数值 font-weight（排除 normal/bold 关键字）
        weight_matches = _re.findall(
            r"font-weight\s*:\s*(\d+)", content, _re.IGNORECASE,
        )
        if not weight_matches:
            continue

        values = [int(m) for m in weight_matches]
        distinct = sorted(set(values))

        # 规则1: 非标准值
        non_standard = [v for v in distinct if v not in _STANDARD_FONT_WEIGHTS]
        if non_standard:
            violations.append({
                "rule": "font_weight_chaos",
                "severity": "warning",
                "file": fname,
                "message": (
                    f"非标准 font-weight 值：{non_standard}，"
                    f"应使用 100/200/300/400/500/600/700/800/900 系统化字重"
                ),
            })

        # 规则2: 超过 6 个不同值
        if len(distinct) > 6:
            violations.append({
                "rule": "font_weight_chaos",
                "severity": "warning",
                "file": fname,
                "message": (
                    f"font-weight 有 {len(distinct)} 个不同值：{distinct}，"
                    f"应精简到 ≤6 个系统化字重层级"
                ),
            })

    return violations


def auto_fix_font_weight(cwd: str) -> bool:
    """M76: 规范化 font-weight 值到标准集合 {100,200,...,900}。"""
    import os as _os
    import re as _re

    def _nearest_font_weight(val: int) -> int:
        """返回标准集合中最近的值（距离相等时取较大值）。"""
        best = _STANDARD_FONT_WEIGHTS[0]
        best_dist = abs(best - val)
        for s in _STANDARD_FONT_WEIGHTS[1:]:
            d = abs(s - val)
            if d < best_dist or (d == best_dist and s > best):
                best, best_dist = s, d
        return best

    def _is_standard(val: int) -> bool:
        return val in _STANDARD_FONT_WEIGHTS

    if not _os.path.exists(cwd):
        return False

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

        # 先检查是否有违规
        violations = check_font_weight_chaos(_os.path.dirname(fpath))
        has_violation = any(
            v["file"] == fname and v["rule"] == "font_weight_chaos"
            for v in violations
        )
        if not has_violation:
            continue

        # 替换非标准 font-weight 值（仅数值）
        def _replace_font_weight(m):
            val = int(m.group(1))
            if _is_standard(val):
                return m.group(0)  # 已标准
            std = _nearest_font_weight(val)
            return f"font-weight: {std}"

        new_content = _re.sub(
            r"font-weight\s*:\s*(\d+)",
            _replace_font_weight,
            content,
            flags=_re.IGNORECASE,
        )

        if new_content != content:
            with open(fpath, "w", encoding="utf-8") as f:
                f.write(new_content)
            changed = True

    return changed


# ---------- M77: letter-spacing 一致性 ----------

_STANDARD_LETTER_SPACINGS = (-0.05, -0.02, 0.0, 0.025, 0.05, 0.1)


def check_letter_spacing_chaos(cwd: str) -> list[dict]:
    """M77: 检测 letter-spacing 一致性问题。

    AI 生成 CSS 常见破绽：随机字间距（0.03em/0.07em/-0.03em）无系统性。
    标准集合（em）：{-0.05, -0.02, 0, 0.025, 0.05, 0.1}。

    规则1: 非标准值报 warning。
    规则2: 超过 5 个不同值报 warning。
    """
    import os as _os
    import re as _re

    violations: list[dict] = []

    if not _os.path.exists(cwd):
        return violations

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

        # 只提取 em 单位的 letter-spacing（排除 normal 关键字）
        ls_matches = _re.findall(
            r"letter-spacing\s*:\s*(-?\d+(?:\.\d+)?)em",
            content, _re.IGNORECASE,
        )
        if not ls_matches:
            continue

        values = [float(m) for m in ls_matches]
        distinct = sorted(set(values))

        # 规则1: 非标准值
        non_standard = [
            v for v in distinct
            if not any(abs(v - s) < 1e-6 for s in _STANDARD_LETTER_SPACINGS)
        ]
        if non_standard:
            violations.append({
                "rule": "letter_spacing_chaos",
                "severity": "warning",
                "file": fname,
                "message": (
                    f"非标准 letter-spacing 值：{non_standard}em，"
                    f"应使用 -0.05/-0.02/0/0.025/0.05/0.1 系统化字间距"
                ),
            })

        # 规则2: 超过 6 个不同值
        if len(distinct) > 6:
            violations.append({
                "rule": "letter_spacing_chaos",
                "severity": "warning",
                "file": fname,
                "message": (
                    f"letter-spacing 有 {len(distinct)} 个不同值：{distinct}em，"
                    f"应精简到 ≤6 个系统化字间距"
                ),
            })

    return violations


def auto_fix_letter_spacing(cwd: str) -> bool:
    """M77: 规范化 letter-spacing 值到标准集合 {-0.05,-0.02,0,0.025,0.05,0.1}em。"""
    import os as _os
    import re as _re

    def _nearest_letter_spacing(val: float) -> float:
        """返回标准集合中最近的值（距离相等时取较大值）。"""
        best = _STANDARD_LETTER_SPACINGS[0]
        best_dist = abs(best - val)
        for s in _STANDARD_LETTER_SPACINGS[1:]:
            d = abs(s - val)
            if d < best_dist or (d == best_dist and s > best):
                best, best_dist = s, d
        return best

    def _is_standard(val: float) -> bool:
        return any(abs(val - s) < 1e-6 for s in _STANDARD_LETTER_SPACINGS)

    if not _os.path.exists(cwd):
        return False

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

        # 先检查是否有违规
        violations = check_letter_spacing_chaos(_os.path.dirname(fpath))
        has_violation = any(
            v["file"] == fname and v["rule"] == "letter_spacing_chaos"
            for v in violations
        )
        if not has_violation:
            continue

        # 替换非标准 letter-spacing 值（仅 em 单位）
        def _replace_letter_spacing(m):
            val = float(m.group(1))
            if _is_standard(val):
                return m.group(0)  # 已标准
            std = _nearest_letter_spacing(val)
            return f"letter-spacing: {std:g}em"

        new_content = _re.sub(
            r"letter-spacing\s*:\s*(-?\d+(?:\.\d+)?)em",
            _replace_letter_spacing,
            content,
            flags=_re.IGNORECASE,
        )

        if new_content != content:
            with open(fpath, "w", encoding="utf-8") as f:
                f.write(new_content)
            changed = True

    return changed


# ---------- M78: border-width 一致性 ----------

_STANDARD_BORDER_WIDTHS = (0, 1, 2, 4, 8)

_BORDER_WIDTH_RE = (
    r"border(?:-(?:top|right|bottom|left))?(?:-width)?\s*:\s*(\d+)px"
)


def check_border_width_chaos(cwd: str) -> list[dict]:
    """M78: 检测 border-width 一致性问题。

    AI 生成 CSS 常见破绽：随机边框宽度（3px/5px/7px）无系统性。
    标准集合（px）：{0, 1, 2, 4, 8}。

    规则1: 非标准值报 warning。
    规则2: 超过 5 个不同值报 warning。

    注意：border-radius / border-color / border-style / border-spacing 不会被误匹配，
    因为正则要求 border 后可选 -(top|right|bottom|left) 可选 -width 然后直接 :。
    """
    import os as _os
    import re as _re

    violations: list[dict] = []

    if not _os.path.exists(cwd):
        return violations

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

        bw_matches = _re.findall(_BORDER_WIDTH_RE, content, _re.IGNORECASE)
        if not bw_matches:
            continue

        values = [int(m) for m in bw_matches]
        distinct = sorted(set(values))

        # 规则1: 非标准值
        non_standard = [v for v in distinct if v not in _STANDARD_BORDER_WIDTHS]
        if non_standard:
            violations.append({
                "rule": "border_width_chaos",
                "severity": "warning",
                "file": fname,
                "message": (
                    f"非标准 border-width 值：{non_standard}px，"
                    f"应使用 0/1/2/4/8 系统化边框宽度"
                ),
            })

        # 规则2: 超过 5 个不同值
        if len(distinct) > 5:
            violations.append({
                "rule": "border_width_chaos",
                "severity": "warning",
                "file": fname,
                "message": (
                    f"border-width 有 {len(distinct)} 个不同值：{distinct}px，"
                    f"应精简到 ≤5 个系统化边框宽度"
                ),
            })

    return violations


def auto_fix_border_width(cwd: str) -> bool:
    """M78: 规范化 border-width 值到标准集合 {0,1,2,4,8}px。"""
    import os as _os
    import re as _re

    def _nearest_border_width(val: int) -> int:
        """返回标准集合中最近的值（距离相等时取较大值）。"""
        best = _STANDARD_BORDER_WIDTHS[0]
        best_dist = abs(best - val)
        for s in _STANDARD_BORDER_WIDTHS[1:]:
            d = abs(s - val)
            if d < best_dist or (d == best_dist and s > best):
                best, best_dist = s, d
        return best

    def _is_standard(val: int) -> bool:
        return val in _STANDARD_BORDER_WIDTHS

    if not _os.path.exists(cwd):
        return False

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

        # 先检查是否有违规
        violations = check_border_width_chaos(_os.path.dirname(fpath))
        has_violation = any(
            v["file"] == fname and v["rule"] == "border_width_chaos"
            for v in violations
        )
        if not has_violation:
            continue

        # 替换非标准 border-width 值
        # 用两步替换：先匹配完整属性声明，再替换其中的 px 值
        def _replace_border_width(m):
            val = int(m.group(2))
            if _is_standard(val):
                return m.group(0)  # 已标准
            std = _nearest_border_width(val)
            prop = m.group(1)  # 完整属性名（含 -top/-width 等）
            return f"{prop}: {std}px"

        new_content = _re.sub(
            r"(border(?:-(?:top|right|bottom|left))?(?:-width)?)\s*:\s*(\d+)px",
            _replace_border_width,
            content,
            flags=_re.IGNORECASE,
        )

        if new_content != content:
            with open(fpath, "w", encoding="utf-8") as f:
                f.write(new_content)
            changed = True

    return changed


# ---------- M79: animation-duration 一致性 ----------

_STANDARD_ANIMATION_MS = (0, 150, 200, 300, 500, 1000, 2000)


def check_animation_duration_chaos(cwd: str) -> list[dict]:
    """M79: 检测 animation-duration 一致性问题。

    AI 生成 CSS 常见破绽：随机动画时长（250ms/400ms/700ms）无系统性。
    标准时长集合（ms）：{0, 150, 200, 300, 500, 1000, 2000}。

    规则1: 非标准值报 warning。
    规则2: 超过 7 个不同值报 warning。
    """
    import os as _os
    import re as _re

    violations: list[dict] = []

    if not _os.path.exists(cwd):
        return violations

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

        # 匹配 animation: <value>; 和 animation-duration: <value>;
        anim_matches = _re.findall(
            r"\banimation(?:-duration)?\s*:\s*([^;]+)",
            content, _re.IGNORECASE,
        )
        if not anim_matches:
            continue

        durations: list[int] = []
        for aval in anim_matches:
            dur_matches = _re.findall(r"(\d+(?:\.\d+)?)(ms|s)\b", aval)
            for num_str, unit in dur_matches:
                durations.append(_parse_duration_to_ms(num_str, unit))

        if not durations:
            continue

        distinct = sorted(set(durations))

        # 规则1: 非标准值
        non_standard = [d for d in distinct if d not in _STANDARD_ANIMATION_MS]
        if non_standard:
            violations.append({
                "rule": "animation_duration_chaos",
                "severity": "warning",
                "file": fname,
                "message": (
                    f"非标准 animation-duration：{non_standard}ms，"
                    f"应使用 0/150/200/300/500/1000/2000 系统化时长"
                ),
            })

        # 规则2: 超过 7 个不同值
        if len(distinct) > 7:
            violations.append({
                "rule": "animation_duration_chaos",
                "severity": "warning",
                "file": fname,
                "message": (
                    f"animation-duration 有 {len(distinct)} 个不同值：{distinct}ms，"
                    f"应精简到 ≤7 个系统化时长"
                ),
            })

    return violations


def auto_fix_animation_duration(cwd: str) -> bool:
    """M79: 规范化 animation-duration 值到标准集合 {0,150,200,300,500,1000,2000}ms。

    非标准值映射到最近标准值（距离相等取较大值），保留原单位（s/ms）。
    幂等：标准值再次运行不修改。
    """
    import os as _os
    import re as _re

    def _nearest_animation_ms(ms: int) -> int:
        best = _STANDARD_ANIMATION_MS[0]
        best_dist = abs(best - ms)
        for s in _STANDARD_ANIMATION_MS[1:]:
            d = abs(s - ms)
            if d < best_dist or (d == best_dist and s > best):
                best, best_dist = s, d
        return best

    if not _os.path.exists(cwd):
        return False

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

        # 先检查是否有违规
        violations = check_animation_duration_chaos(_os.path.dirname(fpath))
        has_violation = any(
            v["file"] == fname and v["rule"] == "animation_duration_chaos"
            for v in violations
        )
        if not has_violation:
            continue

        # 在每个 animation/animation-duration: <value>; 块内替换非标准 duration
        def _fix_anim_block(m):
            prefix = m.group(1)
            aval = m.group(2)

            def _replace_dur(dm):
                num_str = dm.group(1)
                unit = dm.group(2)
                ms = _parse_duration_to_ms(num_str, unit)
                if ms in _STANDARD_ANIMATION_MS:
                    return dm.group(0)
                std_ms = _nearest_animation_ms(ms)
                return _ms_to_str(std_ms, unit)

            new_aval = _re.sub(
                r"(\d+(?:\.\d+)?)(ms|s)\b",
                _replace_dur,
                aval,
            )
            return prefix + new_aval

        new_content = _re.sub(
            r"(\banimation(?:-duration)?\s*:\s*)([^;]+)",
            _fix_anim_block,
            content,
            flags=_re.IGNORECASE,
        )

        if new_content != content:
            with open(fpath, "w", encoding="utf-8") as f:
                f.write(new_content)
            changed = True

    return changed


# ---------- M80: filter/backdrop-filter blur 一致性 ----------

_STANDARD_FILTER_BLUR = (0, 2, 4, 8, 12, 16, 24)

_FILTER_BLUR_RE = (
    r"\b(?:backdrop-)?filter\s*:\s*[^;]*blur\((\d+)px\)"
)


def check_filter_blur_chaos(cwd: str) -> list[dict]:
    """M80: 检测 filter/backdrop-filter blur 一致性问题。

    AI 生成 CSS 常见破绽：随机模糊半径（3px/5px/7px）无系统性。
    标准集合（px）：{0, 2, 4, 8, 12, 16, 24}。

    规则1: 非标准值报 warning。
    规则2: 超过 7 个不同值报 warning。
    """
    import os as _os
    import re as _re

    violations: list[dict] = []

    if not _os.path.exists(cwd):
        return violations

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

        blur_matches = _re.findall(_FILTER_BLUR_RE, content, _re.IGNORECASE)
        if not blur_matches:
            continue

        values = [int(m) for m in blur_matches]
        distinct = sorted(set(values))

        # 规则1: 非标准值
        non_standard = [v for v in distinct if v not in _STANDARD_FILTER_BLUR]
        if non_standard:
            violations.append({
                "rule": "filter_blur_chaos",
                "severity": "warning",
                "file": fname,
                "message": (
                    f"非标准 filter blur 值：{non_standard}px，"
                    f"应使用 0/2/4/8/12/16/24 系统化模糊半径"
                ),
            })

        # 规则2: 超过 7 个不同值
        if len(distinct) > 7:
            violations.append({
                "rule": "filter_blur_chaos",
                "severity": "warning",
                "file": fname,
                "message": (
                    f"filter blur 有 {len(distinct)} 个不同值：{distinct}px，"
                    f"应精简到 ≤7 个系统化模糊半径"
                ),
            })

    return violations


def auto_fix_filter_blur(cwd: str) -> bool:
    """M80: 规范化 filter/backdrop-filter blur 值到标准集合 {0,2,4,8,12,16,24}px。"""
    import os as _os
    import re as _re

    def _nearest_filter_blur(val: int) -> int:
        best = _STANDARD_FILTER_BLUR[0]
        best_dist = abs(best - val)
        for s in _STANDARD_FILTER_BLUR[1:]:
            d = abs(s - val)
            if d < best_dist or (d == best_dist and s > best):
                best, best_dist = s, d
        return best

    def _is_standard(val: int) -> bool:
        return val in _STANDARD_FILTER_BLUR

    if not _os.path.exists(cwd):
        return False

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

        # 先检查是否有违规
        violations = check_filter_blur_chaos(_os.path.dirname(fpath))
        has_violation = any(
            v["file"] == fname and v["rule"] == "filter_blur_chaos"
            for v in violations
        )
        if not has_violation:
            continue

        # 替换非标准 blur 值
        def _replace_blur(m):
            val = int(m.group(1))
            if _is_standard(val):
                return m.group(0)
            std = _nearest_filter_blur(val)
            return m.group(0).replace(f"{val}px", f"{std}px")

        new_content = _re.sub(
            _FILTER_BLUR_RE,
            _replace_blur,
            content,
            flags=_re.IGNORECASE,
        )

        if new_content != content:
            with open(fpath, "w", encoding="utf-8") as f:
                f.write(new_content)
            changed = True

    return changed


# ---------- M81: gap 一致性 ----------

_STANDARD_GAPS = (0, 4, 8, 12, 16, 24, 32, 48, 64)

_GAP_RE = r"\b(?:row-|column-)?gap\s*:\s*([^;]+)"


def check_gap_chaos(cwd: str) -> list[dict]:
    """M81: 检测 gap/row-gap/column-gap 一致性问题。

    AI 生成 CSS 常见破绽：随机间距（7px/13px/18px）无系统性。
    标准集合（px）：{0, 4, 8, 12, 16, 24, 32, 48, 64}（8px 网格系统）。

    规则1: 非标准值报 warning。
    规则2: 超过 9 个不同值报 warning。
    """
    import os as _os
    import re as _re

    violations: list[dict] = []

    if not _os.path.exists(cwd):
        return violations

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

        gap_matches = _re.findall(_GAP_RE, content, _re.IGNORECASE)
        if not gap_matches:
            continue

        # 从每个 gap 值中提取所有 Npx 数字
        values: list[int] = []
        for val_str in gap_matches:
            px_matches = _re.findall(r"(\d+)px", val_str)
            values.extend(int(m) for m in px_matches)

        if not values:
            continue

        distinct = sorted(set(values))

        # 规则1: 非标准值
        non_standard = [v for v in distinct if v not in _STANDARD_GAPS]
        if non_standard:
            violations.append({
                "rule": "gap_chaos",
                "severity": "warning",
                "file": fname,
                "message": (
                    f"非标准 gap 值：{non_standard}px，"
                    f"应使用 0/4/8/12/16/24/32/48/64 系统化间距（8px 网格）"
                ),
            })

        # 规则2: 超过 9 个不同值
        if len(distinct) > 9:
            violations.append({
                "rule": "gap_chaos",
                "severity": "warning",
                "file": fname,
                "message": (
                    f"gap 有 {len(distinct)} 个不同值：{distinct}px，"
                    f"应精简到 ≤9 个系统化间距"
                ),
            })

    return violations


def auto_fix_gap(cwd: str) -> bool:
    """M81: 规范化 gap/row-gap/column-gap 值到标准集合 {0,4,8,12,16,24,32,48,64}px。"""
    import os as _os
    import re as _re

    def _nearest_gap(val: int) -> int:
        best = _STANDARD_GAPS[0]
        best_dist = abs(best - val)
        for s in _STANDARD_GAPS[1:]:
            d = abs(s - val)
            if d < best_dist or (d == best_dist and s > best):
                best, best_dist = s, d
        return best

    def _is_standard(val: int) -> bool:
        return val in _STANDARD_GAPS

    if not _os.path.exists(cwd):
        return False

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

        # 先检查是否有违规
        violations = check_gap_chaos(_os.path.dirname(fpath))
        has_violation = any(
            v["file"] == fname and v["rule"] == "gap_chaos"
            for v in violations
        )
        if not has_violation:
            continue

        # 替换 gap 声明中的非标准 px 值
        def _replace_gap(m):
            val_str = m.group(1)
            def _replace_px(pm):
                val = int(pm.group(1))
                if _is_standard(val):
                    return pm.group(0)
                std = _nearest_gap(val)
                return f"{std}px"
            new_val = _re.sub(r"(\d+)px", _replace_px, val_str)
            return f"{m.group(0)[:m.start(1) - m.start(0)]}{new_val}"

        new_content = _re.sub(
            _GAP_RE,
            _replace_gap,
            content,
            flags=_re.IGNORECASE,
        )

        if new_content != content:
            with open(fpath, "w", encoding="utf-8") as f:
                f.write(new_content)
            changed = True

    return changed


# ---------- M82: padding 一致性 ----------

_STANDARD_PADDINGS = (0, 4, 8, 12, 16, 24, 32, 48, 64)

_PADDING_RE = r"\bpadding(?:-(?:top|right|bottom|left))?\s*:\s*([^;]+)"


def check_padding_chaos(cwd: str) -> list[dict]:
    """M82: 检测 padding/padding-top 等 一致性问题。

    AI 生成 CSS 常见破绽：随机内边距（7px/13px/18px）无系统性。
    标准集合（px）：{0, 4, 8, 12, 16, 24, 32, 48, 64}（8px 网格系统）。

    规则1: 非标准值报 warning。
    规则2: 超过 9 个不同值报 warning。
    """
    import os as _os
    import re as _re

    violations: list[dict] = []

    if not _os.path.exists(cwd):
        return violations

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

        pad_matches = _re.findall(_PADDING_RE, content, _re.IGNORECASE)
        if not pad_matches:
            continue

        values: list[int] = []
        for val_str in pad_matches:
            px_matches = _re.findall(r"(\d+)px", val_str)
            values.extend(int(m) for m in px_matches)

        if not values:
            continue

        distinct = sorted(set(values))

        non_standard = [v for v in distinct if v not in _STANDARD_PADDINGS]
        if non_standard:
            violations.append({
                "rule": "padding_chaos",
                "severity": "warning",
                "file": fname,
                "message": (
                    f"非标准 padding 值：{non_standard}px，"
                    f"应使用 0/4/8/12/16/24/32/48/64 系统化内边距（8px 网格）"
                ),
            })

        if len(distinct) > 9:
            violations.append({
                "rule": "padding_chaos",
                "severity": "warning",
                "file": fname,
                "message": (
                    f"padding 有 {len(distinct)} 个不同值：{distinct}px，"
                    f"应精简到 ≤9 个系统化内边距"
                ),
            })

    return violations


def auto_fix_padding(cwd: str) -> bool:
    """M82: 规范化 padding 值到标准集合 {0,4,8,12,16,24,32,48,64}px。"""
    import os as _os
    import re as _re

    def _nearest_padding(val: int) -> int:
        best = _STANDARD_PADDINGS[0]
        best_dist = abs(best - val)
        for s in _STANDARD_PADDINGS[1:]:
            d = abs(s - val)
            if d < best_dist or (d == best_dist and s > best):
                best, best_dist = s, d
        return best

    def _is_standard(val: int) -> bool:
        return val in _STANDARD_PADDINGS

    if not _os.path.exists(cwd):
        return False

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

        violations = check_padding_chaos(_os.path.dirname(fpath))
        has_violation = any(
            v["file"] == fname and v["rule"] == "padding_chaos"
            for v in violations
        )
        if not has_violation:
            continue

        def _replace_padding(m):
            val_str = m.group(1)
            def _replace_px(pm):
                val = int(pm.group(1))
                if _is_standard(val):
                    return pm.group(0)
                std = _nearest_padding(val)
                return f"{std}px"
            new_val = _re.sub(r"(\d+)px", _replace_px, val_str)
            return f"{m.group(0)[:m.start(1) - m.start(0)]}{new_val}"

        new_content = _re.sub(
            _PADDING_RE,
            _replace_padding,
            content,
            flags=_re.IGNORECASE,
        )

        if new_content != content:
            with open(fpath, "w", encoding="utf-8") as f:
                f.write(new_content)
            changed = True

    return changed


# ---------- M83: margin 一致性 ----------

_STANDARD_MARGINS = (0, 4, 8, 12, 16, 24, 32, 48, 64)

_MARGIN_RE = r"\bmargin(?:-(?:top|right|bottom|left))?\s*:\s*([^;]+)"


def check_margin_chaos(cwd: str) -> list[dict]:
    """M83: 检测 margin/margin-top 等 一致性问题。

    AI 生成 CSS 常见破绽：随机外边距（7px/13px/18px）无系统性。
    标准集合（px）：{0, 4, 8, 12, 16, 24, 32, 48, 64}（8px 网格系统）。
    注意：margin: auto / margin: 0 auto 中的 auto 不检测（非 px 值）。

    规则1: 非标准值报 warning。
    规则2: 超过 9 个不同值报 warning。
    """
    import os as _os
    import re as _re

    violations: list[dict] = []

    if not _os.path.exists(cwd):
        return violations

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

        mar_matches = _re.findall(_MARGIN_RE, content, _re.IGNORECASE)
        if not mar_matches:
            continue

        values: list[int] = []
        for val_str in mar_matches:
            px_matches = _re.findall(r"(\d+)px", val_str)
            values.extend(int(m) for m in px_matches)

        if not values:
            continue

        distinct = sorted(set(values))

        non_standard = [v for v in distinct if v not in _STANDARD_MARGINS]
        if non_standard:
            violations.append({
                "rule": "margin_chaos",
                "severity": "warning",
                "file": fname,
                "message": (
                    f"非标准 margin 值：{non_standard}px，"
                    f"应使用 0/4/8/12/16/24/32/48/64 系统化外边距（8px 网格）"
                ),
            })

        if len(distinct) > 9:
            violations.append({
                "rule": "margin_chaos",
                "severity": "warning",
                "file": fname,
                "message": (
                    f"margin 有 {len(distinct)} 个不同值：{distinct}px，"
                    f"应精简到 ≤9 个系统化外边距"
                ),
            })

    return violations


def auto_fix_margin(cwd: str) -> bool:
    """M83: 规范化 margin 值到标准集合 {0,4,8,12,16,24,32,48,64}px。"""
    import os as _os
    import re as _re

    def _nearest_margin(val: int) -> int:
        best = _STANDARD_MARGINS[0]
        best_dist = abs(best - val)
        for s in _STANDARD_MARGINS[1:]:
            d = abs(s - val)
            if d < best_dist or (d == best_dist and s > best):
                best, best_dist = s, d
        return best

    def _is_standard(val: int) -> bool:
        return val in _STANDARD_MARGINS

    if not _os.path.exists(cwd):
        return False

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

        violations = check_margin_chaos(_os.path.dirname(fpath))
        has_violation = any(
            v["file"] == fname and v["rule"] == "margin_chaos"
            for v in violations
        )
        if not has_violation:
            continue

        def _replace_margin(m):
            val_str = m.group(1)
            def _replace_px(pm):
                val = int(pm.group(1))
                if _is_standard(val):
                    return pm.group(0)
                std = _nearest_margin(val)
                return f"{std}px"
            new_val = _re.sub(r"(\d+)px", _replace_px, val_str)
            return f"{m.group(0)[:m.start(1) - m.start(0)]}{new_val}"

        new_content = _re.sub(
            _MARGIN_RE,
            _replace_margin,
            content,
            flags=_re.IGNORECASE,
        )

        if new_content != content:
            with open(fpath, "w", encoding="utf-8") as f:
                f.write(new_content)
            changed = True

    return changed


# ---------- M84: text-shadow blur 一致性 ----------

_STANDARD_TEXT_SHADOW_BLURS = (0, 1, 2, 4, 8)

_TEXT_SHADOW_RE = r"\btext-shadow\s*:\s*([^;]+)"


def check_text_shadow_chaos(cwd: str) -> list[dict]:
    """M84: 检测 text-shadow blur 一致性问题。

    AI 生成 CSS 常见破绽：随机文字阴影模糊（3px/5px/7px）无系统性。
    标准集合（px）：{0, 1, 2, 4, 8}（文字阴影通常较小）。
    复用 _extract_shadow_blur 提取第3个 token 的 blur 值。

    规则1: 非标准值报 warning。
    规则2: 超过 5 个不同值报 warning。
    """
    import os as _os
    import re as _re

    violations: list[dict] = []

    if not _os.path.exists(cwd):
        return violations

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

        shadow_matches = _re.findall(_TEXT_SHADOW_RE, content, _re.IGNORECASE)
        if not shadow_matches:
            continue

        blurs: list[int] = []
        for shadow_val in shadow_matches:
            # text-shadow 可能有多个阴影（逗号分隔），逐个提取
            for part in shadow_val.split(","):
                blur = _extract_shadow_blur(part.strip())
                if blur is not None:
                    blurs.append(blur)

        if not blurs:
            continue

        distinct = sorted(set(blurs))

        non_standard = [b for b in distinct if b not in _STANDARD_TEXT_SHADOW_BLURS]
        if non_standard:
            violations.append({
                "rule": "text_shadow_chaos",
                "severity": "warning",
                "file": fname,
                "message": (
                    f"非标准 text-shadow blur 值：{non_standard}px，"
                    f"应使用 0/1/2/4/8 系统化文字阴影模糊"
                ),
            })

        if len(distinct) > 5:
            violations.append({
                "rule": "text_shadow_chaos",
                "severity": "warning",
                "file": fname,
                "message": (
                    f"text-shadow blur 有 {len(distinct)} 个不同值：{distinct}px，"
                    f"应精简到 ≤5 个系统化模糊"
                ),
            })

    return violations


def auto_fix_text_shadow(cwd: str) -> bool:
    """M84: 规范化 text-shadow blur 值到标准集合 {0,1,2,4,8}px。"""
    import os as _os
    import re as _re

    def _nearest_text_shadow_blur(val: int) -> int:
        best = _STANDARD_TEXT_SHADOW_BLURS[0]
        best_dist = abs(best - val)
        for s in _STANDARD_TEXT_SHADOW_BLURS[1:]:
            d = abs(s - val)
            if d < best_dist or (d == best_dist and s > best):
                best, best_dist = s, d
        return best

    def _is_standard(val: int) -> bool:
        return val in _STANDARD_TEXT_SHADOW_BLURS

    if not _os.path.exists(cwd):
        return False

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

        violations = check_text_shadow_chaos(_os.path.dirname(fpath))
        has_violation = any(
            v["file"] == fname and v["rule"] == "text_shadow_chaos"
            for v in violations
        )
        if not has_violation:
            continue

        def _replace_text_shadow(m):
            shadow_val = m.group(1)
            # 逐个处理逗号分隔的多个阴影
            parts = shadow_val.split(",")
            new_parts = []
            for part in parts:
                tokens = part.strip().split()
                # 跳过 none 关键词
                if len(tokens) < 3:
                    new_parts.append(part)
                    continue
                # 第3个 token 是 blur
                blur_token = tokens[2]
                px_m = _re.match(r"-?(\d+)px", blur_token)
                if px_m:
                    val = int(px_m.group(1))
                    if not _is_standard(val):
                        std = _nearest_text_shadow_blur(val)
                        # 保留负号
                        prefix = "-" if blur_token.startswith("-") else ""
                        tokens[2] = f"{prefix}{std}px"
                        new_parts.append(" ".join(tokens))
                        continue
                new_parts.append(part)
            new_val = ",".join(new_parts)
            return f"{m.group(0)[:m.start(1) - m.start(0)]}{new_val}"

        new_content = _re.sub(
            _TEXT_SHADOW_RE,
            _replace_text_shadow,
            content,
            flags=_re.IGNORECASE,
        )

        if new_content != content:
            with open(fpath, "w", encoding="utf-8") as f:
                f.write(new_content)
            changed = True

    return changed


# ---------- M85: transform scale 一致性 ----------

_STANDARD_SCALES = (0.8, 0.9, 0.95, 1.0, 1.05, 1.1, 1.2)

_SCALE_RE = r"scale[XY]?\((\d+(?:\.\d+)?)"


def check_transform_scale_chaos(cwd: str) -> list[dict]:
    """M85: 检测 transform scale 一致性问题。

    AI 生成 CSS 常见破绽：随机缩放值（0.97/1.07/0.85）无系统性。
    标准集合：{0.8, 0.9, 0.95, 1, 1.05, 1.1, 1.2}。
    匹配 scale()/scaleX()/scaleY() 的第一个数值参数。

    规则1: 非标准值报 warning。
    规则2: 超过 7 个不同值报 warning。
    """
    import os as _os
    import re as _re

    violations: list[dict] = []

    if not _os.path.exists(cwd):
        return violations

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

        scale_matches = _re.findall(_SCALE_RE, content, _re.IGNORECASE)
        if not scale_matches:
            continue

        values = [float(m) for m in scale_matches]
        distinct = sorted(set(values))

        non_standard = [v for v in distinct if v not in _STANDARD_SCALES]
        if non_standard:
            violations.append({
                "rule": "transform_scale_chaos",
                "severity": "warning",
                "file": fname,
                "message": (
                    f"非标准 transform scale 值：{non_standard}，"
                    f"应使用 0.8/0.9/0.95/1/1.05/1.1/1.2 系统化缩放"
                ),
            })

        if len(distinct) > 7:
            violations.append({
                "rule": "transform_scale_chaos",
                "severity": "warning",
                "file": fname,
                "message": (
                    f"transform scale 有 {len(distinct)} 个不同值：{distinct}，"
                    f"应精简到 ≤7 个系统化缩放"
                ),
            })

    return violations


def auto_fix_transform_scale(cwd: str) -> bool:
    """M85: 规范化 transform scale 值到标准集合 {0.8,0.9,0.95,1,1.05,1.1,1.2}。"""
    import os as _os
    import re as _re

    def _nearest_scale(val: float) -> float:
        best = _STANDARD_SCALES[0]
        best_dist = abs(best - val)
        for s in _STANDARD_SCALES[1:]:
            d = abs(s - val)
            if d < best_dist or (d == best_dist and s > best):
                best, best_dist = s, d
        return best

    def _is_standard(val: float) -> bool:
        return val in _STANDARD_SCALES

    if not _os.path.exists(cwd):
        return False

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

        violations = check_transform_scale_chaos(_os.path.dirname(fpath))
        has_violation = any(
            v["file"] == fname and v["rule"] == "transform_scale_chaos"
            for v in violations
        )
        if not has_violation:
            continue

        def _replace_scale(m):
            val = float(m.group(1))
            if _is_standard(val):
                return m.group(0)
            std = _nearest_scale(val)
            # 格式化：去掉多余的 .0
            if std == int(std):
                std_str = str(int(std))
            else:
                std_str = str(std)
            return m.group(0).replace(m.group(1), std_str)

        new_content = _re.sub(
            _SCALE_RE,
            _replace_scale,
            content,
            flags=_re.IGNORECASE,
        )

        if new_content != content:
            with open(fpath, "w", encoding="utf-8") as f:
                f.write(new_content)
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
    changed14 = auto_fix_placeholder_text(cwd)
    changed15 = auto_fix_console_log(cwd)
    changed16 = auto_fix_empty_links(cwd)
    changed17 = auto_fix_inline_styles(cwd)
    changed18 = auto_fix_color_contrast(cwd)
    changed19 = auto_fix_zindex(cwd)
    changed20 = auto_fix_border_radius(cwd)
    changed21 = auto_fix_box_shadow(cwd)
    changed22 = auto_fix_transition(cwd)
    changed23 = auto_fix_opacity(cwd)
    changed24 = auto_fix_font_size(cwd)
    changed25 = auto_fix_line_height(cwd)
    changed26 = auto_fix_font_weight(cwd)
    changed27 = auto_fix_letter_spacing(cwd)
    changed28 = auto_fix_border_width(cwd)
    changed29 = auto_fix_animation_duration(cwd)
    changed30 = auto_fix_filter_blur(cwd)
    changed31 = auto_fix_gap(cwd)
    changed32 = auto_fix_padding(cwd)
    changed33 = auto_fix_margin(cwd)
    changed34 = auto_fix_text_shadow(cwd)
    changed35 = auto_fix_transform_scale(cwd)
    return (
        changed1 or changed2 or changed3 or changed4 or changed5
        or changed6 or changed7 or changed8 or changed9 or changed10 or changed11
        or changed12 or changed13 or changed14 or changed15 or changed16 or changed17
        or changed18 or changed19 or changed20 or changed21 or changed22 or changed23
        or changed24 or changed25 or changed26 or changed27 or changed28 or changed29
        or changed30 or changed31 or changed32 or changed33 or changed34 or changed35
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

    # 10. M54: 占位文本检测
    try:
        violations.extend(check_placeholder_text(cwd))
    except Exception:
        pass

    # 11. M56: 空链接/无效 href 检测
    try:
        violations.extend(check_empty_links(cwd))
    except Exception:
        pass

    # 12. M57: 内联样式检测
    try:
        violations.extend(check_inline_styles(cwd))
    except Exception:
        pass

    # 13. M58: console.log 调试残留检测
    try:
        violations.extend(check_console_log(cwd))
    except Exception:
        pass

    # 14. M69: z-index 堆叠混乱检测
    try:
        violations.extend(check_zindex_chaos(cwd))
    except Exception:
        pass

    # 15. M70: border-radius 一致性检测
    try:
        violations.extend(check_border_radius_chaos(cwd))
    except Exception:
        pass

    # 16. M71: box-shadow elevation 混乱检测
    try:
        violations.extend(check_box_shadow_chaos(cwd))
    except Exception:
        pass

    # 17. M72: transition duration 一致性检测
    try:
        violations.extend(check_transition_chaos(cwd))
    except Exception:
        pass

    # 18. M73: opacity 一致性检测
    try:
        violations.extend(check_opacity_chaos(cwd))
    except Exception:
        pass

    # 19. M74: font-size 一致性检测
    try:
        violations.extend(check_font_size_chaos(cwd))
    except Exception:
        pass

    # 20. M75: line-height 一致性检测
    try:
        violations.extend(check_line_height_chaos(cwd))
    except Exception:
        pass

    # 21. M76: font-weight 一致性检测
    try:
        violations.extend(check_font_weight_chaos(cwd))
    except Exception:
        pass

    # 22. M77: letter-spacing 一致性检测
    try:
        violations.extend(check_letter_spacing_chaos(cwd))
    except Exception:
        pass

    # 23. M78: border-width 一致性检测
    try:
        violations.extend(check_border_width_chaos(cwd))
    except Exception:
        pass

    # 24. M79: animation-duration 一致性检测
    try:
        violations.extend(check_animation_duration_chaos(cwd))
    except Exception:
        pass

    # 25. M80: filter/backdrop-filter blur 一致性检测
    try:
        violations.extend(check_filter_blur_chaos(cwd))
    except Exception:
        pass

    # 26. M81: gap/row-gap/column-gap 一致性检测
    try:
        violations.extend(check_gap_chaos(cwd))
    except Exception:
        pass

    # 27. M82: padding 一致性检测
    try:
        violations.extend(check_padding_chaos(cwd))
    except Exception:
        pass

    # 28. M83: margin 一致性检测
    try:
        violations.extend(check_margin_chaos(cwd))
    except Exception:
        pass

    # 29. M84: text-shadow blur 一致性检测
    try:
        violations.extend(check_text_shadow_chaos(cwd))
    except Exception:
        pass

    # 30. M85: transform scale 一致性检测
    try:
        violations.extend(check_transform_scale_chaos(cwd))
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

    # 10. M54: 占位文本扣分（内容质量，error 级别）
    if "placeholder_text" in error_rules:
        score -= 10
        notes.append("检测到占位文本(-10)")

    # 11. M56: 空链接扣分（warning 级别，-5）
    if "empty_link" in warning_rules:
        score -= 5
        notes.append("检测到空链接/无效href(-5)")

    # 12. M57: 内联样式扣分（warning 级别，-5）
    if "inline_style" in warning_rules:
        score -= 5
        notes.append("检测到内联样式style(-5)")

    # 13. M58: console.log 调试残留扣分（warning 级别，-5）
    if "console_log" in warning_rules:
        score -= 5
        notes.append("检测到console.log调试残留(-5)")

    # 14. M69: z-index 堆叠混乱扣分（warning 级别，-5）
    if "zindex_chaos" in warning_rules:
        score -= 5
        notes.append("检测到z-index堆叠混乱(-5)")

    # 15. M70: border-radius 一致性扣分（warning 级别，-5）
    if "border_radius_chaos" in warning_rules:
        score -= 5
        notes.append("检测到border-radius不一致(-5)")

    # 16. M71: box-shadow elevation 混乱扣分（warning 级别，-5）
    if "box_shadow_chaos" in warning_rules:
        score -= 5
        notes.append("检测到box-shadow elevation混乱(-5)")

    # 17. M72: transition duration 一致性扣分（warning 级别，-5）
    if "transition_chaos" in warning_rules:
        score -= 5
        notes.append("检测到transition duration不一致(-5)")

    # 18. M73: opacity 一致性扣分（warning 级别，-5）
    if "opacity_chaos" in warning_rules:
        score -= 5
        notes.append("检测到opacity不一致(-5)")

    # 19. M74: font-size 一致性扣分（warning 级别，-5）
    if "font_size_chaos" in warning_rules:
        score -= 5
        notes.append("检测到font-size不一致(-5)")

    # 20. M75: line-height 一致性扣分（warning 级别，-5）
    if "line_height_chaos" in warning_rules:
        score -= 5
        notes.append("检测到line-height不一致(-5)")

    # 21. M76: font-weight 一致性扣分（warning 级别，-5）
    if "font_weight_chaos" in warning_rules:
        score -= 5
        notes.append("检测到font-weight不一致(-5)")

    # 22. M77: letter-spacing 一致性扣分（warning 级别，-5）
    if "letter_spacing_chaos" in warning_rules:
        score -= 5
        notes.append("检测到letter-spacing不一致(-5)")

    # 23. M78: border-width 一致性扣分（warning 级别，-5）
    if "border_width_chaos" in warning_rules:
        score -= 5
        notes.append("检测到border-width不一致(-5)")

    # 24. M79: animation-duration 一致性扣分（warning 级别，-5）
    if "animation_duration_chaos" in warning_rules:
        score -= 5
        notes.append("检测到animation-duration不一致(-5)")

    # 25. M80: filter/backdrop-filter blur 一致性扣分（warning 级别，-5）
    if "filter_blur_chaos" in warning_rules:
        score -= 5
        notes.append("检测到filter-blur不一致(-5)")

    # 26. M81: gap/row-gap/column-gap 一致性扣分（warning 级别，-5）
    if "gap_chaos" in warning_rules:
        score -= 5
        notes.append("检测到gap不一致(-5)")

    # 27. M82: padding 一致性扣分（warning 级别，-5）
    if "padding_chaos" in warning_rules:
        score -= 5
        notes.append("检测到padding不一致(-5)")

    # 28. M83: margin 一致性扣分（warning 级别，-5）
    if "margin_chaos" in warning_rules:
        score -= 5
        notes.append("检测到margin不一致(-5)")

    # 29. M84: text-shadow blur 一致性扣分（warning 级别，-5）
    if "text_shadow_chaos" in warning_rules:
        score -= 5
        notes.append("检测到text-shadow不一致(-5)")

    # 30. M85: transform scale 一致性扣分（warning 级别，-5）
    if "transform_scale_chaos" in warning_rules:
        score -= 5
        notes.append("检测到transform-scale不一致(-5)")

    score = max(0, score)
    if not notes:
        notes.append("设计质量良好")
    return score, notes
