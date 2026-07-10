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
        f"字体 {font}; 用 CSS variables; 含 hover/focus 状态; "
        f"响应式 768px; focus-visible; WCAG AA 对比度(文字≥4.5:1); "
        f"按钮文字色须与背景对比度≥4.5:1。"
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

    return violations


def design_score(cwd: str) -> "tuple[int, list[str]]":
    """计算 HTML 文件的设计质量评分（0-100），返回 (分数, 评语列表)。

    评分维度（每项权重不同）：
    - 语义化HTML结构 (20分)：header/main/section/footer 齐全
    - meta 标签 (15分)：viewport + charset + description
    - CSS 变量系统 (15分)：:root 定义 --color-* 变量
    - 响应式 (15分)：@media 查询或 viewport meta
    - 无障碍基础 (15分)：img alt + html lang
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

    # 1. 语义化HTML (20分)
    if "semantic_html" not in warning_rules:
        score += 20
    else:
        score += 10
        notes.append("语义化HTML不完整(-10)")

    # 2. meta 标签 (15分)
    if "meta_viewport" not in error_rules:
        score += 15
    else:
        notes.append("缺少viewport meta(-15)")

    # 3. CSS 变量 (15分)
    if "css_variables" not in warning_rules:
        score += 15
    else:
        score += 8
        notes.append("CSS变量使用不充分(-7)")

    # 4. 响应式 (15分) — viewport meta 存在即视为有响应式意识
    if "meta_viewport" not in error_rules:
        score += 15
    else:
        notes.append("无响应式(-15)")

    # 5. 无障碍 (15分)
    if "img_alt_missing" not in error_rules and "html_lang" not in warning_rules:
        score += 15
    elif "img_alt_missing" not in error_rules:
        score += 8
        notes.append("缺少html lang(-7)")
    else:
        notes.append("img缺少alt(-15)")

    # 6. 动画性能 (10分)
    if "animation_performance" not in warning_rules:
        score += 10
    else:
        notes.append("动画性能待优化(-10)")

    # 7. 设计一致性 (10分) — 检查 hex 颜色数量
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
        # 统计非黑非白的颜色（排除 #000000/#FFFFFF 等基础色）
        design_colors = {
            c for c in hex_colors
            if c.upper() not in ("#000000", "#FFFFFF", "#FFF", "#000")
        }
        if len(design_colors) <= 5:
            score += 10
        else:
            score += 5
            notes.append(f"配色过多({len(design_colors)}种，建议≤5)(-5)")
        break  # 只检查第一个 HTML 文件

    if not notes:
        notes.append("设计质量良好")
    return score, notes
