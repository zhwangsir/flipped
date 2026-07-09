"""设计系统程序化校验（M10.4-A）。

把 AI-Design-System-Prompt.md 的设计准则从"prompt 提示"升级到"程序强制校验"：
扫描生成的 UI 代码（HTML/CSS/JSX/TSX/Vue），检查是否遵循设计系统。

校验维度：
1. 必含颜色：设计系统要求的 hex 值至少出现一个（accent 必须）
2. 禁止英文颜色名：blue/red/green 等命名色不允许
3. 响应式断点：必须出现 @media 或 Tailwind 断点（md:/lg:）
4. 组件状态：交互组件必须含 hover/focus
5. 入口文件存在：UI 项目必须有 index.html 或 App.tsx 等

集成方式：
- lint_dir(cwd, style) -> DesignLintResult：核心校验函数
- make_design_verifier(style)：适配 orchestrator 的 verifier 接口
- planner 可在 verify_cmd 里调用 `python -m driving.design_lint <cwd> --style <style>`
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from driving.design_context import STYLE_BRIEFS, infer_style

# UI 代码文件扩展名
_UI_EXTS = {".html", ".htm", ".css", ".scss", ".jsx", ".tsx", ".vue", ".svelte"}

# 入口文件名
_ENTRY_FILES = (
    "index.html", "index.htm",
    "App.tsx", "App.jsx", "App.vue",
    "main.tsx", "main.jsx",
    "_app.tsx", "_app.jsx",  # Next.js
    "pages/index.tsx", "pages/index.jsx",
    "src/App.tsx", "src/App.jsx",
)

# Tailwind 断点类名（响应式检测用）
_TAILWIND_BP = re.compile(r"\b(sm:|md:|lg:|xl:|2xl:)")

# @media 断点
_MEDIA_QUERY = re.compile(r"@media[^{]*\{", re.MULTILINE)

# 英文颜色名（CSS 命名色，禁止使用）
_NAMED_COLORS = re.compile(
    r"\b(color|background(-color)?|border|fill|stroke)\s*:\s*"
    r"(aliceblue|antiquewhite|aqua|aquamarine|azure|beige|bisque|black|blanchedalmond|"
    r"blue|blueviolet|brown|burlywood|cadetblue|chartreuse|chocolate|coral|"
    r"cornflowerblue|cornsilk|crimson|cyan|darkblue|darkcyan|darkgoldenrod|darkgray|"
    r"darkgreen|darkgrey|darkkhaki|darkmagenta|darkolivegreen|darkorange|darkorchid|"
    r"darkred|darksalmon|darkseagreen|darkslateblue|darkslategray|darkslategrey|"
    r"darkturquoise|darkviolet|deeppink|deepskyblue|dimgray|dimgrey|dodgerblue|"
    r"firebrick|floralwhite|forestgreen|fuchsia|gainsboro|ghostwhite|gold|goldenrod|"
    r"gray|green|greenyellow|grey|honeydew|hotpink|indianred|indigo|ivory|khaki|"
    r"lavender|lavenderblush|lawngreen|lemonchiffon|lightblue|lightcoral|lightcyan|"
    r"lightgoldenrodyellow|lightgray|lightgreen|lightgrey|lightpink|lightsalmon|"
    r"lightseagreen|lightskyblue|lightslategray|lightslategrey|lightsteelblue|"
    r"lightyellow|lime|limegreen|linen|magenta|maroon|mediumaquamarine|mediumblue|"
    r"mediumorchid|mediumpurple|mediumseagreen|mediumslateblue|mediumspringgreen|"
    r"mediumturquoise|mediumvioletred|midnightblue|mintcream|mistyrose|moccasin|"
    r"navajowhite|navy|oldlace|olive|olivedrab|orange|orangered|orchid|palegoldenrod|"
    r"palegreen|paleturquoise|palevioletred|papayawhip|peachpuff|peru|pink|plum|"
    r"powderblue|purple|rebeccapurple|red|rosybrown|royalblue|saddlebrown|salmon|"
    r"sandybrown|seagreen|seashell|sienna|silver|skyblue|slateblue|slategray|"
    r"slategrey|snow|springgreen|steelblue|tan|teal|thistle|tomato|turquoise|violet|"
    r"wheat|white|whitesmoke|yellow|yellowgreen)\b",
    re.IGNORECASE,
)

# hover/focus 状态检测
_INTERACT_STATES = re.compile(
    r":\s*(hover|focus|active|focus-visible)\s*[\{,]", re.MULTILINE
)
_TAILWIND_STATES = re.compile(
    r"\b(hover:|focus:|active:|focus-visible:|group-hover:)"
)

# hex 值匹配
_HEX_COLOR = re.compile(r"#[0-9a-fA-F]{3,8}\b")


@dataclass
class Violation:
    rule: str
    severity: str  # error / warning
    detail: str
    file: str = ""


@dataclass
class DesignLintResult:
    passed: bool
    style: str
    cwd: str
    checked_files: int = 0
    violations: list[Violation] = field(default_factory=list)

    def summary(self) -> str:
        errors = sum(1 for v in self.violations if v.severity == "error")
        warnings = sum(1 for v in self.violations if v.severity == "warning")
        if self.passed:
            return f"✅ design-lint 通过 (style={self.style}, files={self.checked_files}, warnings={warnings})"
        return f"❌ design-lint 未通过 (style={self.style}, files={self.checked_files}, errors={errors}, warnings={warnings})"


def _collect_ui_files(cwd: Path) -> list[Path]:
    """收集所有 UI 代码文件（限制深度，跳过 node_modules/.git/dist/build）。"""
    skip_dirs = {"node_modules", ".git", ".next", "dist", "build", "out", ".cache", ".venv", "__pycache__"}
    out: list[Path] = []
    for p in cwd.rglob("*"):
        if not p.is_file():
            continue
        if any(part in skip_dirs for part in p.parts):
            continue
        if p.suffix.lower() in _UI_EXTS:
            out.append(p)
    return out


def _has_entry_file(cwd: Path) -> str | None:
    """检查是否有 UI 入口文件；返回找到的文件名或 None。"""
    for name in _ENTRY_FILES:
        if (cwd / name).exists():
            return name
    # 兜底：任何 .html 都算入口
    for p in cwd.glob("*.html"):
        return p.name
    return None


def _normalize_hex(val: str) -> str:
    """把 hex 规整为小写 6 位（#abc → #aabbcc）。

    方便比对设计系统要求值。
    """
    v = val.lower().lstrip("#")
    if len(v) == 3:
        v = "".join(c * 2 for c in v)
    return f"#{v[:6]}"


def _design_hexes(style: str) -> set[str]:
    """取该风格设计系统要求的所有 hex 值（规整后）。"""
    brief = STYLE_BRIEFS.get(style) or STYLE_BRIEFS["dark"]
    out: set[str] = set()
    for v in brief["colors"].values():
        # colors 里可能是 "gradient" / "rgba(...)"，提取所有 hex
        for m in _HEX_COLOR.finditer(v):
            out.add(_normalize_hex(m.group()))
    return out


def lint_dir(cwd: str | Path, style: str = "auto", product_type: str = "") -> DesignLintResult:
    """校验目录里的 UI 代码是否遵循设计系统。

    Args:
        cwd: 工作目录
        style: 设计风格（auto 时根据 product_type 推断）
        product_type: 产品类型（用于自动推断风格）

    Returns:
        DesignLintResult，passed=True 表示通过
    """
    cwd = Path(cwd)
    if style == "auto":
        style = infer_style(product_type or str(cwd.name))
    if style not in STYLE_BRIEFS:
        style = "dark"

    result = DesignLintResult(passed=True, style=style, cwd=str(cwd))
    files = _collect_ui_files(cwd)
    result.checked_files = len(files)

    # 规则 1：UI 项目必须有入口文件
    if files:
        entry = _has_entry_file(cwd)
        if not entry:
            result.violations.append(Violation(
                rule="entry_file",
                severity="error",
                detail=f"未找到 UI 入口文件（期望 {', '.join(_ENTRY_FILES[:5])} 等之一）",
            ))

    # 规则 2-5：扫描每个文件
    required_hexes = _design_hexes(style)
    found_hexes: set[str] = set()
    found_media = False
    found_states = False
    has_named_colors = False

    for f in files:
        try:
            text = f.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        # 收集 hex 值
        for m in _HEX_COLOR.finditer(text):
            found_hexes.add(_normalize_hex(m.group()))
        # 检查命名色
        if _NAMED_COLORS.search(text):
            has_named_colors = True
            result.violations.append(Violation(
                rule="no_named_colors",
                severity="warning",
                detail="使用了 CSS 命名色（如 blue/red/green），违反设计系统要求用 hex 值",
                file=str(f.relative_to(cwd)) if f.is_relative_to(cwd) else str(f),
            ))
        # 响应式断点
        if _MEDIA_QUERY.search(text) or _TAILWIND_BP.search(text):
            found_media = True
        # 组件状态
        if _INTERACT_STATES.search(text) or _TAILWIND_STATES.search(text):
            found_states = True

    # 规则 2：必含设计系统 hex 值
    if files and required_hexes:
        # 至少要有一个设计系统要求的 hex 出现（宽松：accent 或 bg 任一即可）
        matched = found_hexes & required_hexes
        if not matched:
            # 警告：生成的代码未使用任何设计系统颜色
            result.violations.append(Violation(
                rule="design_colors",
                severity="warning",
                detail=(
                    f"未在生成的 UI 代码中检测到设计系统要求的任何颜色值。"
                    f"风格={style} 期望含 {'/'.join(sorted(required_hexes)[:3])} 等，"
                    f"实际找到 {len(found_hexes)} 个 hex：{'/'.join(sorted(found_hexes)[:5])}"
                ),
            ))

    # 规则 3：响应式断点（UI 有交互才需要，单页静态 HTML 也建议有）
    if files and not found_media:
        result.violations.append(Violation(
            rule="responsive_breakpoints",
            severity="warning",
            detail="未检测到响应式断点（@media 或 Tailwind md:/lg:），UI 在移动端可能不可用",
        ))

    # 规则 4：组件状态
    if files and not found_states:
        result.violations.append(Violation(
            rule="component_states",
            severity="warning",
            detail="未检测到组件交互状态（hover/focus/active），违反设计系统的状态要求",
        ))

    # 判定：有 error 级违规即不通过
    has_errors = any(v.severity == "error" for v in result.violations)
    result.passed = not has_errors
    return result


def make_design_verifier(style: str = "auto"):
    """构造适配 orchestrator verifier 接口的设计校验器。

    orchestrator 的 verifier 签名是 (cmd_list, cwd) -> tuple[bool, str]。
    我们把 design-lint 作为补充校验：在用户 verify_cmd 之外，
    自动追加一次设计系统校验。
    """
    def _verify(cmd_list: list[str], cwd: str) -> tuple[bool, str]:
        lint = lint_dir(cwd, style)
        if lint.passed:
            return True, lint.summary()
        return False, lint.summary()

    return _verify


def combined_verifier(base_verifier, style: str = "auto"):
    """组合校验：先跑用户 verify_cmd，再跑 design-lint。

    用法（在 default_orchestrator_fn 里）：
        verifier = combined_verifier(sandbox_verifier, state.design_style)
    """
    design_verifier = make_design_verifier(style)

    def _verify(cmd_list: list[str], cwd: str) -> tuple[bool, str]:
        ok1, msg1 = base_verifier(cmd_list, cwd)
        ok2, msg2 = design_verifier(cmd_list, cwd)
        # 任一失败即失败；设计-lint 用 warning 也算通过，所以 ok2 通常 True
        if not ok1:
            return False, f"verify: {msg1}"
        if not ok2:
            return False, f"design-lint: {msg2}"
        return True, f"{msg1}; {msg2}"

    return _verify


# ---------- CLI 入口（供 verify_cmd 调用） ----------

def _cli() -> int:
    import argparse
    import sys

    p = argparse.ArgumentParser(description="设计系统程序化校验")
    p.add_argument("cwd", help="要校验的目录")
    p.add_argument("--style", default="auto", help="设计风格（auto 时自动推断）")
    p.add_argument("--product-type", default="", help="产品类型（auto 推断风格时参考）")
    args = p.parse_args()

    result = lint_dir(args.cwd, args.style, args.product_type)
    print(result.summary())
    if result.violations:
        print("\n违规详情:")
        for v in result.violations:
            print(f"  [{v.severity}] {v.rule}: {v.detail}" + (f" ({v.file})" if v.file else ""))
    return 0 if result.passed else 1


if __name__ == "__main__":
    import sys
    sys.exit(_cli())
