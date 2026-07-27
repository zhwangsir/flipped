"""M157.10 · 结构化失败信号 JSON 测试。

验证 scripts/quality_gate.sh 失败时往 reports/findings.jsonl 追加的结构化 finding：
  - 每行合法 JSON
  - 含全部 6 字段：ts / rule / location / expected / actual / suggested_fix / retryable
    （ts + 6 业务字段 = 7 个 key，与 REFERENCE_CLAUDE_CODE_TRAE_AGENT.md §1.2 schema 对齐）
  - rule 值在预定义常量集合内
  - append 模式（多次调用不覆盖）

被测对象：
  - scripts/_emit_finding.py（核心 Python 模块 + CLI，单一可信源）
  - scripts/quality_gate.sh（通过 FLIPPED_QG_INJECT_FAILURE 钩子注入失败，
    跑 --quick --no-cov 验证端到端 shell→python 调用链；标记 slow 默认跳过，
    避免拖慢 1758 全量回归）

设计要点：
  - 用 tmp_path fixture 隔离 reports/findings.jsonl，不污染仓库
  - 通过 FLIPPED_FINDINGS_PATH 环境变量重定向输出路径（_emit_finding.py 读取）
  - 不破坏真实代码（不修改 src/ console/src/），只调 emit_finding 或注入失败钩子
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

# ---- 常量集合（与 scripts/_emit_finding.py / quality_gate.sh 保持一致）----
EXPECTED_RULES = {
    "QG_SHELL_LINT_FAILED",
    "QG_PYTEST_FAILED",
    "QG_PY_COVERAGE_BELOW_FLOOR",
    "QG_VITEST_FAILED",
    "QG_FE_COVERAGE_BELOW_FLOOR",
    "QG_TSC_ERRORS",
    "QG_BUILD_FAILED",
}

REQUIRED_FIELDS = {
    "ts",
    "rule",
    "location",
    "expected",
    "actual",
    "suggested_fix",
    "retryable",
}

# scripts/_emit_finding.py 的绝对路径（项目根 / scripts / _emit_finding.py）
ROOT = Path(__file__).resolve().parent.parent
EMIT_SCRIPT = ROOT / "scripts" / "_emit_finding.py"
QUALITY_GATE = ROOT / "scripts" / "quality_gate.sh"


def _import_emit_module():
    """以模块方式导入 scripts/_emit_finding.py（不依赖 sys.path[0] 注入）。"""
    import importlib.util

    spec = importlib.util.spec_from_file_location("_emit_finding", EMIT_SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# =====================================================================
# Test A · 单元测试 emit_finding Python 函数
# =====================================================================


class TestEmitFindingUnit:
    """直接 import _emit_finding 模块，测试 emit_finding 函数。"""

    def test_writes_valid_json_line(self, tmp_path, monkeypatch):
        findings = tmp_path / "findings.jsonl"
        monkeypatch.setenv("FLIPPED_FINDINGS_PATH", str(findings))
        mod = _import_emit_module()

        mod.emit_finding(
            rule="QG_TSC_ERRORS",
            location="console/src/foo.ts:42",
            expected="0 tsc errors",
            actual="5 errors (TS2322 etc.)",
            suggested_fix="fix the type annotations on bar()",
            retryable=True,
        )

        assert findings.exists()
        lines = findings.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 1
        obj = json.loads(lines[0])  # 合法 JSON
        assert REQUIRED_FIELDS.issubset(obj.keys())
        assert obj["rule"] == "QG_TSC_ERRORS"
        assert obj["retryable"] is True
        assert obj["location"] == "console/src/foo.ts:42"
        # ts 必须是 ISO8601 字符串（含 'T' 分隔日期时间，或带时区）
        assert isinstance(obj["ts"], str)
        assert "T" in obj["ts"] or ":" in obj["ts"]

    def test_append_mode_does_not_overwrite(self, tmp_path, monkeypatch):
        findings = tmp_path / "findings.jsonl"
        monkeypatch.setenv("FLIPPED_FINDINGS_PATH", str(findings))
        mod = _import_emit_module()

        for i in range(3):
            mod.emit_finding(
                rule="QG_BUILD_FAILED",
                location=f"console/src/m{i}.ts",
                expected="build ok",
                actual=f"error {i}",
                suggested_fix="rebuild",
                retryable=False,
            )

        lines = findings.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 3
        for ln in lines:
            obj = json.loads(ln)
            assert obj["rule"] == "QG_BUILD_FAILED"

    @pytest.mark.parametrize("rule", sorted(EXPECTED_RULES))
    def test_all_expected_rules_accepted(self, tmp_path, monkeypatch, rule):
        findings = tmp_path / "findings.jsonl"
        monkeypatch.setenv("FLIPPED_FINDINGS_PATH", str(findings))
        mod = _import_emit_module()

        mod.emit_finding(
            rule=rule,
            location="loc",
            expected="exp",
            actual="act",
            suggested_fix="fix",
            retryable=True,
        )
        obj = json.loads(findings.read_text(encoding="utf-8").strip())
        assert obj["rule"] == rule

    def test_unknown_rule_raises(self, tmp_path, monkeypatch):
        findings = tmp_path / "findings.jsonl"
        monkeypatch.setenv("FLIPPED_FINDINGS_PATH", str(findings))
        mod = _import_emit_module()

        # 未知 rule 必须拒绝（防止拼写错误悄悄溜进 findings.jsonl）
        with pytest.raises(ValueError):
            mod.emit_finding(
                rule="QG_TYPO_RULE",
                location="x",
                expected="x",
                actual="x",
                suggested_fix="x",
                retryable=True,
            )

    def test_default_findings_path_when_env_unset(self, tmp_path, monkeypatch):
        # 未设 FLIPPED_FINDINGS_PATH 时，写到默认 reports/findings.jsonl
        # 测试里切到 tmp_path 模拟项目根，避免污染真实 reports/
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("FLIPPED_FINDINGS_PATH", raising=False)
        mod = _import_emit_module()

        mod.emit_finding(
            rule="QG_TSC_ERRORS",
            location="x",
            expected="x",
            actual="x",
            suggested_fix="x",
            retryable=True,
        )
        default_path = tmp_path / "reports" / "findings.jsonl"
        assert default_path.exists(), "默认应写到 reports/findings.jsonl"


# =====================================================================
# Test B · CLI 入口（subprocess 调 python3 scripts/_emit_finding.py）
# =====================================================================


class TestEmitFindingCLI:
    """验证 quality_gate.sh 调用 emit_finding 的命令行模式工作。"""

    def test_cli_writes_finding(self, tmp_path):
        findings = tmp_path / "findings.jsonl"
        env = os.environ.copy()
        env["FLIPPED_FINDINGS_PATH"] = str(findings)

        result = subprocess.run(
            [
                sys.executable,
                str(EMIT_SCRIPT),
                "--rule",
                "QG_PY_COVERAGE_BELOW_FLOOR",
                "--location",
                "src/orchestrator.py",
                "--expected",
                ">=80%",
                "--actual",
                "78.5%",
                "--suggested-fix",
                "add tests for src/orchestrator.py uncovered branches",
                "--retryable",
                "true",
            ],
            capture_output=True,
            text=True,
            env=env,
            cwd=str(ROOT),
        )
        assert result.returncode == 0, f"CLI failed: {result.stderr}"
        assert findings.exists()
        obj = json.loads(findings.read_text(encoding="utf-8").strip())
        assert obj["rule"] == "QG_PY_COVERAGE_BELOW_FLOOR"
        assert obj["expected"] == ">=80%"
        assert obj["actual"] == "78.5%"
        assert obj["retryable"] is True

    def test_cli_unknown_rule_exits_nonzero(self, tmp_path):
        findings = tmp_path / "findings.jsonl"
        env = os.environ.copy()
        env["FLIPPED_FINDINGS_PATH"] = str(findings)

        result = subprocess.run(
            [
                sys.executable,
                str(EMIT_SCRIPT),
                "--rule",
                "QG_BOGUS",
                "--location",
                "x",
                "--expected",
                "x",
                "--actual",
                "x",
                "--suggested-fix",
                "x",
                "--retryable",
                "false",
            ],
            capture_output=True,
            text=True,
            env=env,
            cwd=str(ROOT),
        )
        assert result.returncode != 0
        assert not findings.exists() or findings.read_text(encoding="utf-8").strip() == ""


# =====================================================================
# Test C · shell→python 调用链（模拟 quality_gate.sh 调 emit_finding 的方式）
# =====================================================================


class TestShellCallChain:
    """模拟 quality_gate.sh 里 `python3 scripts/_emit_finding.py ...` 的调用链。"""

    def test_shell_invokes_python_helper(self, tmp_path):
        findings = tmp_path / "findings.jsonl"
        # 用 bash 调 python，复现 quality_gate.sh 的调用模式
        # 用单引号包裹含 $VAR 的值，避免 bash 把 $VAR 当变量展开成空串
        shell_cmd = (
            f'FLIPPED_FINDINGS_PATH="{findings}" '
            f'python3 "{EMIT_SCRIPT}" '
            f'--rule QG_SHELL_LINT_FAILED '
            f'--location scripts/quality_gate.sh '
            f"--expected 'no $VAR<non-ascii> traps' "
            f"--actual '1 trap found' "
            f'--suggested-fix "quote variables" '
            f'--retryable true'
        )
        result = subprocess.run(
            ["bash", "-c", shell_cmd],
            capture_output=True,
            text=True,
            cwd=str(ROOT),
        )
        assert result.returncode == 0, f"shell call failed: {result.stderr}"
        obj = json.loads(findings.read_text(encoding="utf-8").strip())
        assert obj["rule"] == "QG_SHELL_LINT_FAILED"
        # 含特殊字符的 expected/actual 也要正确序列化
        assert "$VAR" in obj["expected"]


# =====================================================================
# Test D · 端到端 quality_gate.sh 集成（slow，默认跳过）
# =====================================================================


@pytest.mark.skipif(
    not os.environ.get("FLIPPED_RUN_SLOW_QG_TESTS"),
    reason="跑全量 quality_gate.sh 慢（含 vitest+tsc+build）；设 FLIPPED_RUN_SLOW_QG_TESTS=1 启用",
)
class TestQualityGateEndToEnd:
    """端到端：跑真实 quality_gate.sh，验证 findings.jsonl 写入。

    通过 FLIPPED_QG_INJECT_FAILURE 钩子注入失败，不破坏真实代码。
    """

    @pytest.mark.parametrize(
        "inject_rule",
        [
            "QG_SHELL_LINT_FAILED",
            "QG_PYTEST_FAILED",
            "QG_PY_COVERAGE_BELOW_FLOOR",
            "QG_VITEST_FAILED",
            "QG_FE_COVERAGE_BELOW_FLOOR",
            "QG_TSC_ERRORS",
            "QG_BUILD_FAILED",
        ],
    )
    def test_quality_gate_emits_finding_on_injected_failure(
        self, tmp_path, inject_rule
    ):
        findings = tmp_path / "findings.jsonl"
        env = os.environ.copy()
        env["FLIPPED_FINDINGS_PATH"] = str(findings)
        env["FLIPPED_QG_INJECT_FAILURE"] = inject_rule

        result = subprocess.run(
            ["bash", str(QUALITY_GATE), "--quick", "--no-cov"],
            capture_output=True,
            text=True,
            env=env,
            cwd=str(ROOT),
            timeout=300,
        )
        # 注入失败后 quality_gate 必须退出码非 0
        assert result.returncode != 0, (
            f"quality_gate.sh 应在注入 {inject_rule} 后失败，但退出码 0\n"
            f"stdout: {result.stdout[-2000:]}\nstderr: {result.stderr[-2000:]}"
        )
        assert findings.exists(), "findings.jsonl 未生成"
        lines = [
            ln for ln in findings.read_text(encoding="utf-8").splitlines() if ln.strip()
        ]
        assert len(lines) >= 1, "findings.jsonl 为空"
        # 至少有一行 rule == inject_rule
        rules = {json.loads(ln)["rule"] for ln in lines}
        assert inject_rule in rules, (
            f"findings.jsonl 未含注入的 rule={inject_rule}；实际 rules={rules}"
        )
        # 校验每行字段完整
        for ln in lines:
            obj = json.loads(ln)
            assert REQUIRED_FIELDS.issubset(obj.keys()), (
                f"finding 缺字段：{set(REQUIRED_FIELDS) - set(obj.keys())}"
            )
            assert obj["rule"] in EXPECTED_RULES, f"未知 rule: {obj['rule']}"
            assert isinstance(obj["retryable"], bool)

    def test_quality_gate_pass_no_findings_when_clean(self, tmp_path):
        """无注入 + 干净环境 → quality_gate.sh exit 0 + findings.jsonl 为空。

        覆盖 M157.10 修的 bug：`grep -c . file || echo "0"` 在空文件时双输出
        "0\n0" 导致 `[: integer expression expected`。修后应静默通过。
        """
        findings = tmp_path / "findings.jsonl"
        env = os.environ.copy()
        env["FLIPPED_FINDINGS_PATH"] = str(findings)
        # 显式 unset 注入钩子，防止外部环境变量污染
        env.pop("FLIPPED_QG_INJECT_FAILURE", None)

        result = subprocess.run(
            ["bash", str(QUALITY_GATE), "--quick", "--no-cov"],
            capture_output=True,
            text=True,
            env=env,
            cwd=str(ROOT),
            timeout=300,
        )
        assert result.returncode == 0, (
            f"quality_gate.sh 应在干净环境 exit 0\n"
            f"stdout: {result.stdout[-2000:]}\nstderr: {result.stderr[-2000:]}"
        )
        # findings.jsonl 存在但为空（quality_gate.sh 开头 truncate）
        assert findings.exists(), "findings.jsonl 应被创建（即使为空）"
        content = findings.read_text(encoding="utf-8").strip()
        assert content == "", f"findings.jsonl 应为空，实际：{content!r}"
        # stderr 不应含 integer expression 报错
        assert "integer expression expected" not in result.stderr, (
            f"grep -c 双输出 bug 复发：{result.stderr[-500:]}"
        )
