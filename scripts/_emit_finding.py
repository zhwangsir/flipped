#!/usr/bin/env python3
"""M157.10 · 结构化失败信号发射器（单一可信源）。

被 scripts/quality_gate.sh 在每个门禁失败时调用，往 reports/findings.jsonl
追加一行合法 JSON。schema 对齐 REFERENCE_CLAUDE_CODE_TRAE_AGENT.md §1.2：

    {
      "ts":             "2026-07-27T03:04:11+00:00",   # ISO8601
      "rule":           "QG_PY_COVERAGE_BELOW_FLOOR",   # 大写蛇形，白名单
      "location":       "src/orchestrator.py",          # 文件/模块/命令
      "expected":       ">=80%",                        # 阈值或期望
      "actual":         "78.5%",                        # 实测值
      "suggested_fix":  "add tests for uncovered branches",
      "retryable":      true                            # Agent 重试可能修复吗
    }

设计要点：
  - 单一可信源：quality_gate.sh 只调本脚本，不内联 python3 -c，避免 JSON 拼接陷阱
  - append 模式：多次调用累积，不覆盖（findings.jsonl 是 jsonl，每行一个 finding）
  - rule 白名单：拒绝未知 rule，防止拼写错误悄悄溜进 findings.jsonl
  - 父目录自动创建：reports/ 不存在时不报错
  - FLIPPED_FINDINGS_PATH 环境变量：测试/调试可重定向输出路径，默认 reports/findings.jsonl
  - 既可 import 又可 CLI：方便单元测试 + shell 调用

用法（CLI）:
    python3 scripts/_emit_finding.py \\
        --rule QG_PY_COVERAGE_BELOW_FLOOR \\
        --location src/orchestrator.py \\
        --expected ">=80%" \\
        --actual "78.5%" \\
        --suggested-fix "add tests for uncovered branches" \\
        --retryable true

用法（import）:
    from _emit_finding import emit_finding
    emit_finding(rule="QG_TSC_ERRORS", location="x", expected="0",
                 actual="5", suggested_fix="fix types", retryable=True)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ---- rule 白名单（与 quality_gate.sh 的 G0-G5 门禁一一对应）----
# 顺序与 quality_gate.sh 检查顺序一致，方便排查。
EXPECTED_RULES: frozenset[str] = frozenset({
    "QG_SHELL_LINT_FAILED",        # G0
    "QG_PYTEST_FAILED",            # G1
    "QG_PY_COVERAGE_BELOW_FLOOR",  # G2
    "QG_VITEST_FAILED",            # G3
    "QG_FE_COVERAGE_BELOW_FLOOR",  # G3
    "QG_TSC_ERRORS",               # G4
    "QG_BUILD_FAILED",             # G5
})


def _default_findings_path() -> Path:
    """默认 reports/findings.jsonl（相对 cwd）；FLIPPED_FINDINGS_PATH 可重定向。"""
    override = os.environ.get("FLIPPED_FINDINGS_PATH")
    if override:
        return Path(override)
    return Path("reports") / "findings.jsonl"


def emit_finding(
    *,
    rule: str,
    location: str,
    expected: str,
    actual: str,
    suggested_fix: str,
    retryable: bool,
    findings_path: Path | None = None,
) -> dict[str, Any]:
    """追加一行结构化 finding 到 findings.jsonl。

    返回写入的 dict（方便测试断言）。rule 不在白名单内时 raise ValueError。
    """
    if rule not in EXPECTED_RULES:
        raise ValueError(
            f"unknown rule {rule!r}; expected one of {sorted(EXPECTED_RULES)}"
        )

    finding: dict[str, Any] = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "rule": rule,
        "location": location,
        "expected": expected,
        "actual": actual,
        "suggested_fix": suggested_fix,
        "retryable": bool(retryable),
    }

    path = findings_path if findings_path is not None else _default_findings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    # json.dumps 默认 ascii=True 会转义非 ASCII；显式 ensure_ascii=False 保留中文可读
    line = json.dumps(finding, ensure_ascii=False)
    with path.open("a", encoding="utf-8") as f:
        f.write(line + "\n")
    return finding


def _parse_bool(s: str) -> bool:
    s2 = s.strip().lower()
    if s2 in ("true", "1", "yes", "y"):
        return True
    if s2 in ("false", "0", "no", "n"):
        return False
    raise argparse.ArgumentTypeError(f"invalid bool: {s!r} (expected true/false)")


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Emit a structured finding to reports/findings.jsonl",
    )
    p.add_argument("--rule", required=True, help=f"rule name (one of {sorted(EXPECTED_RULES)})")
    p.add_argument("--location", required=True, help="file path / module / command")
    p.add_argument("--expected", required=True, help="threshold or expectation")
    p.add_argument("--actual", required=True, help="measured value")
    p.add_argument("--suggested-fix", required=True, help="actionable fix hint")
    p.add_argument(
        "--retryable",
        required=True,
        type=_parse_bool,
        help="true if Agent retry might fix it; false otherwise",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        emit_finding(
            rule=args.rule,
            location=args.location,
            expected=args.expected,
            actual=args.actual,
            suggested_fix=args.suggested_fix,
            retryable=args.retryable,
        )
    except ValueError as e:
        print(f"_emit_finding: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
