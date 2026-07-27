#!/usr/bin/env python3
"""
E2E 测试报告生成器 — 把 Playwright JSON 结果转成结构化 Markdown 报告。

用法：
    python3 scripts/gen_e2e_report.py <results.json> <output.md>

报告内容（满足"完整测试报告"要求）：
  1. 概览：通过/失败/flaky/skipped 总数 + 通过率
  2. 5 维度分类统计：功能/边界/异常/性能/兼容性
  3. 浏览器维度统计：chromium/firefox/webkit
  4. 失败用例详情：用例标题 + 浏览器 + 错误摘要 + 文件路径
  5. 性能基线：从 console.log 中提取 Core Web Vitals 数值
  6. 测试覆盖率：用例数 / 文件数 / 维度覆盖
  7. 问题分析与改进建议
"""
from __future__ import annotations

import json
import os
import re
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path


# ---------- 维度分类规则 ----------
# 按测试文件名/路径归类到 5 个维度。
# Playwright JSON 的 file 字段是相对 testDir 的路径（如 "a11y.spec.ts" 或 "boundary/input.spec.ts"），
# 故匹配规则用文件名关键词而非完整路径前缀。
DIMENSION_RULES = {
    "功能验证": [
        "console-smoke.spec", "console.spec", "console-errors.spec",
        "factory.spec", "factory-api.spec", "panels.spec",
        "layout.spec", "mobile.spec", "a11y.spec",
        "compatibility/interaction", "compatibility/routing", "compatibility/layout",
    ],
    "边界条件": ["boundary/"],
    "异常处理": ["error-handling/"],
    "性能测试": ["performance/"],
    "兼容性测试": ["compatibility/responsive", "accessibility/"],
}


def classify_dimension(file_path: str) -> str:
    """根据测试文件路径归类到 5 维度之一。

    file_path 可能是 "a11y.spec.ts" / "boundary/input.spec.ts" / "compatibility/routing.spec.ts" 等格式。
    匹配规则用子串匹配（兼顾相对路径与完整路径）。
    """
    # 规范化：统一用正斜杠
    norm = file_path.replace("\\", "/")
    for dim, prefixes in DIMENSION_RULES.items():
        for prefix in prefixes:
            # 既要匹配 "boundary/input.spec.ts" 也要匹配 "input.spec.ts"（裸文件名场景）
            if prefix in norm or norm.startswith(prefix) or norm.endswith(prefix):
                return dim
    return "其他"


def extract_browser(project_name: str) -> str:
    """从 Playwright project name 提取浏览器名。"""
    if not project_name:
        return "unknown"
    name = project_name.lower()
    if "firefox" in name:
        return "firefox"
    if "webkit" in name:
        return "webkit"
    if "chromium" in name or "chrome" in name:
        return "chromium"
    return project_name


def parse_stats(data: dict) -> dict:
    """解析 stats 数组为 {passed, failed, flaky, skipped}。"""
    stats = {"passed": 0, "failed": 0, "flaky": 0, "skipped": 0}
    # Playwright JSON: stats 是对象，含 counts 字段；老版本是数组
    raw = data.get("stats", {})
    if isinstance(raw, list):
        for s in raw:
            k = s.get("status")
            if k in stats:
                stats[k] = s.get("count", 0)
    elif isinstance(raw, dict):
        # 新版 Playwright：stats = {expected: 0, unexpected: 0, flaky: 0, skipped: 0}
        stats["passed"] = raw.get("expected", 0)
        stats["failed"] = raw.get("unexpected", 0)
        stats["flaky"] = raw.get("flaky", 0)
        stats["skipped"] = raw.get("skipped", 0)
    return stats


def collect_suites(data: dict) -> list:
    """Playwright JSON 嵌套结构：root.suites[]，每个 suite 又有 suites[] 与 spec[]。
    递归收集所有 spec，返回扁平化列表。"""
    results = []

    def walk(suite: dict, parent_path: str = ""):
        title = suite.get("title", "")
        cur_path = f"{parent_path} > {title}" if parent_path else title
        file = suite.get("file", "")
        for spec in suite.get("specs", []):
            results.append({"spec": spec, "suite_path": cur_path, "file": file})
        for child in suite.get("suites", []):
            walk(child, cur_path)

    for top in data.get("suites", []):
        walk(top)
    return results


def collect_test_cases(suites_flat: list) -> list:
    """把 spec 展开为 test case 列表（每个 spec 多个 browser project = 多条 case）。

    每个 test 可能有多个 results（retry 产生），只取最终结果（最后一个），
    避免重复计数。Playwright stats 也是按 test 计数，不按 result。
    """
    cases = []
    for item in suites_flat:
        spec = item["spec"]
        file = item["file"]
        dimension = classify_dimension(file)
        for test in spec.get("tests", []):
            browser = extract_browser(test.get("projectName", ""))
            results = test.get("results", [])
            if not results:
                # 无 result 的 test（理论不会出现，防御性处理）
                cases.append({
                    "title": spec.get("title", ""),
                    "file": file,
                    "dimension": dimension,
                    "browser": browser,
                    "status": "skipped",
                    "duration_ms": 0,
                    "error": "",
                    "stdout": "",
                    "line": spec.get("line", 0),
                })
                continue
            # 只取最终结果（最后一个 result = retry 后的最终态）
            r = results[-1]
            # Playwright result.status: "passed" / "failed" / "flaky" / "skipped" / "interrupted"
            # 但 test 级别的状态需要看所有 results：若任一失败但最终通过 = flaky
            statuses = [x.get("status") for x in results]
            if len(results) > 1 and "failed" in statuses and statuses[-1] == "passed":
                final_status = "flaky"
            else:
                final_status = r.get("status", "unknown")
            cases.append({
                "title": spec.get("title", ""),
                "file": file,
                "dimension": dimension,
                "browser": browser,
                "status": final_status,
                "duration_ms": r.get("duration", 0),
                "error": _extract_error(r) if final_status == "failed" else "",
                "stdout": _extract_stdout(r),
                "line": spec.get("line", 0),
            })
    return cases


def _extract_error(result: dict) -> str:
    """从 result 中提取错误信息摘要。"""
    errors = result.get("errors", [])
    if not errors:
        return ""
    parts = []
    for e in errors[:2]:  # 最多 2 条
        msg = e.get("message", "") if isinstance(e, dict) else str(e)
        if msg:
            # 截断长错误
            parts.append(msg[:500] + ("..." if len(msg) > 500 else ""))
    return "\n".join(parts)


def _extract_stdout(result: dict) -> str:
    """从 result.stdout 提取 console.log 输出（性能基线用）。"""
    stdout = result.get("stdout", [])
    if not stdout:
        return ""
    parts = []
    for s in stdout:
        if isinstance(s, dict):
            text = s.get("text", "")
        else:
            text = str(s)
        if text:
            parts.append(text)
    return "\n".join(parts)


def extract_perf_baseline(cases: list) -> dict:
    """从性能测试 case 的 stdout 中提取 Core Web Vitals 数值。"""
    baseline = {"lcp_ms": [], "fcp_ms": [], "ttfb_ms": [], "cls": [], "interaction": []}
    for c in cases:
        if c["dimension"] != "性能测试":
            continue
        out = c["stdout"]
        # 匹配 "📊 Core Web Vitals 基线: {...}"
        m = re.search(r"Core Web Vitals 基线:\s*(\{[^}]+\})", out)
        if m:
            try:
                obj = json.loads(m.group(1).replace("'", '"'))
                if obj.get("ttfb_ms") is not None and obj["ttfb_ms"] >= 0:
                    baseline["ttfb_ms"].append(obj["ttfb_ms"])
                if obj.get("fcp_ms") is not None:
                    baseline["fcp_ms"].append(obj["fcp_ms"])
                if obj.get("lcp_ms") is not None:
                    baseline["lcp_ms"].append(obj["lcp_ms"])
                if obj.get("cls") is not None:
                    baseline["cls"].append(obj["cls"])
            except Exception:
                pass
        # 交互延迟
        m2 = re.search(r"第1轮\s*(\d+)ms.*第20轮\s*(\d+)ms", out)
        if m2:
            baseline["interaction"].append({
                "first_ms": int(m2.group(1)),
                "last_ms": int(m2.group(2)),
            })
    return baseline


def render_markdown(data: dict, cases: list, stats: dict, output_path: str) -> None:
    """渲染 Markdown 报告。"""
    total = sum(stats.values())
    passed_rate = (stats["passed"] + stats["flaky"]) / total * 100 if total > 0 else 0
    overall_status = "✅ 通过" if stats["failed"] == 0 else "❌ 有失败"

    # 维度统计
    dim_stats = defaultdict(lambda: {"passed": 0, "failed": 0, "flaky": 0, "skipped": 0, "total": 0})
    for c in cases:
        d = c["dimension"]
        dim_stats[d]["total"] += 1
        # Playwright: status="passed"/"failed"/"flaky"/"skipped"
        s = c["status"]
        if s in dim_stats[d]:
            dim_stats[d][s] += 1
        elif s == "passed":
            dim_stats[d]["passed"] += 1

    # 浏览器统计
    browser_stats = defaultdict(lambda: {"passed": 0, "failed": 0, "flaky": 0, "skipped": 0, "total": 0})
    for c in cases:
        b = c["browser"]
        browser_stats[b]["total"] += 1
        s = c["status"]
        if s in browser_stats[b]:
            browser_stats[b][s] += 1

    # 失败用例
    failed_cases = [c for c in cases if c["status"] == "failed"]

    # 性能基线
    perf = extract_perf_baseline(cases)

    # 文件覆盖
    files = sorted(set(c["file"] for c in cases))

    # 渲染
    lines = []
    lines.append("# E2E 自动化测试报告")
    lines.append("")
    lines.append(f"> 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  ")
    lines.append(f"> 测试框架: Playwright  ")
    lines.append(f"> 整体状态: **{overall_status}**  ")
    lines.append(f"> 通过率: **{passed_rate:.1f}%**")
    lines.append("")

    # 概览
    lines.append("## 1. 概览")
    lines.append("")
    lines.append("| 指标 | 数量 |")
    lines.append("|------|------|")
    lines.append(f"| 总用例数 | {total} |")
    lines.append(f"| ✅ 通过 | {stats['passed']} |")
    lines.append(f"| ⚠️ Flaky | {stats['flaky']} |")
    lines.append(f"| ❌ 失败 | {stats['failed']} |")
    lines.append(f"| ⏭ 跳过 | {stats['skipped']} |")
    lines.append(f"| 测试文件数 | {len(files)} |")
    lines.append("")

    # 5 维度统计
    lines.append("## 2. 五维度覆盖统计")
    lines.append("")
    lines.append("| 维度 | 总数 | 通过 | Flaky | 失败 | 跳过 | 通过率 |")
    lines.append("|------|------|------|-------|------|------|--------|")
    for dim in ["功能验证", "边界条件", "异常处理", "性能测试", "兼容性测试", "其他"]:
        if dim not in dim_stats:
            continue
        s = dim_stats[dim]
        rate = (s["passed"] + s["flaky"]) / s["total"] * 100 if s["total"] > 0 else 0
        lines.append(
            f"| {dim} | {s['total']} | {s['passed']} | {s['flaky']} | {s['failed']} | {s['skipped']} | {rate:.1f}% |"
        )
    lines.append("")

    # 浏览器维度
    lines.append("## 3. 浏览器维度统计")
    lines.append("")
    lines.append("| 浏览器 | 总数 | 通过 | Flaky | 失败 | 跳过 | 通过率 |")
    lines.append("|--------|------|------|-------|------|------|--------|")
    for b in ["chromium", "firefox", "webkit", "unknown"]:
        if b not in browser_stats:
            continue
        s = browser_stats[b]
        if s["total"] == 0:
            continue
        rate = (s["passed"] + s["flaky"]) / s["total"] * 100 if s["total"] > 0 else 0
        lines.append(
            f"| {b} | {s['total']} | {s['passed']} | {s['flaky']} | {s['failed']} | {s['skipped']} | {rate:.1f}% |"
        )
    lines.append("")

    # 失败用例详情
    lines.append("## 4. 失败用例详情")
    lines.append("")
    if not failed_cases:
        lines.append("✅ 无失败用例。")
    else:
        lines.append(f"共 **{len(failed_cases)}** 条失败用例：")
        lines.append("")
        for i, c in enumerate(failed_cases, 1):
            lines.append(f"### 失败 #{i}: {c['title']}")
            lines.append("")
            lines.append(f"- **文件**: `{c['file']}:{c['line']}`")
            lines.append(f"- **维度**: {c['dimension']}")
            lines.append(f"- **浏览器**: {c['browser']}")
            lines.append(f"- **耗时**: {c['duration_ms']}ms")
            if c["error"]:
                lines.append("- **错误**:")
                lines.append("  ```")
                err_lines = c["error"].split("\n")
                for el in err_lines[:10]:
                    lines.append(f"  {el}")
                lines.append("  ```")
            lines.append("")
    lines.append("")

    # 性能基线
    lines.append("## 5. 性能基线")
    lines.append("")
    if perf["lcp_ms"] or perf["fcp_ms"] or perf["ttfb_ms"]:
        lines.append("### Core Web Vitals")
        lines.append("")
        lines.append("| 指标 | 采集样本数 | 最小值 | 最大值 | 平均值 | 阈值 |")
        lines.append("|------|-----------|--------|--------|--------|------|")

        def _stats_row(name: str, samples: list, threshold: str) -> str:
            if not samples:
                return f"| {name} | 0 | - | - | - | {threshold} |"
            return (
                f"| {name} | {len(samples)} | {min(samples):.1f} | "
                f"{max(samples):.1f} | {sum(samples)/len(samples):.1f} | {threshold} |"
            )

        lines.append(_stats_row("TTFB (ms)", perf["ttfb_ms"], "< 1800 (dev 1.5x)"))
        lines.append(_stats_row("FCP (ms)", perf["fcp_ms"], "< 3000 (dev 1.5x)"))
        lines.append(_stats_row("LCP (ms)", perf["lcp_ms"], "< 4000 (dev 1.5x)"))
        lines.append(_stats_row("CLS", perf["cls"], "< 0.25"))
        lines.append("")
    else:
        lines.append("_本次运行未采集到 Core Web Vitals 数据（性能测试可能未跑或被 grep 过滤）。_")
        lines.append("")

    if perf["interaction"]:
        lines.append("### 交互延迟稳定性")
        lines.append("")
        lines.append("| 第 1 轮 (ms) | 第 20 轮 (ms) | 退化倍数 |")
        lines.append("|-------------|--------------|---------|")
        for it in perf["interaction"]:
            ratio = it["last_ms"] / it["first_ms"] if it["first_ms"] > 0 else 0
            lines.append(f"| {it['first_ms']} | {it['last_ms']} | {ratio:.2f}x |")
        lines.append("")

    # 测试覆盖
    lines.append("## 6. 测试覆盖率")
    lines.append("")
    lines.append("### 6.1 维度覆盖")
    lines.append("")
    covered_dims = [d for d in DIMENSION_RULES if any(c["dimension"] == d for c in cases)]
    lines.append(f"- 5 维度已覆盖: **{len(covered_dims)}/5** ({', '.join(covered_dims)})")
    lines.append(f"- 测试文件总数: **{len(files)}**")
    lines.append(f"- 测试用例总数: **{total}**")
    lines.append("")

    lines.append("### 6.2 测试文件清单")
    lines.append("")
    for f in files:
        dim = classify_dimension(f)
        case_count = sum(1 for c in cases if c["file"] == f)
        lines.append(f"- `{f}` ({dim}, {case_count} cases)")
    lines.append("")

    # 问题分析与建议
    lines.append("## 7. 问题分析与改进建议")
    lines.append("")
    if not failed_cases:
        lines.append("✅ 本次测试全部通过，无已知问题。")
    else:
        lines.append(f"共发现 **{len(failed_cases)}** 个失败用例，按维度分布：")
        lines.append("")
        fail_by_dim = defaultdict(int)
        for c in failed_cases:
            fail_by_dim[c["dimension"]] += 1
        for d, n in sorted(fail_by_dim.items(), key=lambda x: -x[1]):
            lines.append(f"- **{d}**: {n} 个失败")
        lines.append("")
        lines.append("### 改进建议")
        lines.append("")
        lines.append("1. **优先修复高失败率维度**：按上表分布，优先处理失败最多的维度。")
        lines.append("2. **查看 HTML 报告获取详情**：`open console/reports/e2e-html/index.html`")
        lines.append("3. **查看失败 trace**：`console/reports/e2e-artifacts/` 下有截图与 trace 文件。")
        lines.append("4. **针对 flaky 用例**：增加 retries 或定位时序依赖。")
    lines.append("")

    # 报告元信息
    lines.append("---")
    lines.append("")
    lines.append(f"- 报告生成器: `scripts/gen_e2e_report.py`")
    lines.append(f"- JSON 结果: `console/reports/e2e-results.json`")
    lines.append(f"- HTML 报告: `console/reports/e2e-html/index.html`")
    lines.append(f"- 失败 artifacts: `console/reports/e2e-artifacts/`")
    lines.append("")

    Path(output_path).write_text("\n".join(lines), encoding="utf-8")
    print(f"✓ 报告已生成: {output_path}")


def main():
    if len(sys.argv) != 3:
        print("用法: python3 gen_e2e_report.py <results.json> <output.md>", file=sys.stderr)
        sys.exit(1)

    results_json = sys.argv[1]
    output_md = sys.argv[2]

    if not os.path.exists(results_json):
        print(f"✗ 找不到输入文件: {results_json}", file=sys.stderr)
        sys.exit(1)

    with open(results_json, encoding="utf-8") as f:
        data = json.load(f)

    stats = parse_stats(data)
    suites_flat = collect_suites(data)
    cases = collect_test_cases(suites_flat)
    render_markdown(data, cases, stats, output_md)


if __name__ == "__main__":
    main()
