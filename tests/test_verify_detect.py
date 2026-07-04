"""F1a — 验收命令探测器单测(纯函数,tmp_path 造假项目,确定性无 LLM)。"""
from pathlib import Path

from driving.verify_detect import VerifyPlan, detect_verify_command


def _touch(root: Path, rel: str, content: str = "") -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


def test_pytest_ini(tmp_path: Path):
    _touch(tmp_path, "pytest.ini", "[pytest]\n")
    plan = detect_verify_command(tmp_path)
    assert plan.command == ["pytest", "-q"]
    assert plan.source == "pytest"
    assert plan.detected is True
    assert plan.confidence == "high"


def test_pytest_tests_dir(tmp_path: Path):
    _touch(tmp_path, "tests/test_x.py", "def test_x():\n    assert True\n")
    assert detect_verify_command(tmp_path).source == "pytest"


def test_pytest_pyproject_tool_section(tmp_path: Path):
    _touch(tmp_path, "pyproject.toml", "[tool.pytest.ini_options]\naddopts = '-q'\n")
    assert detect_verify_command(tmp_path).source == "pytest"


def test_pytest_root_test_file(tmp_path: Path):
    _touch(tmp_path, "test_thing.py", "def test_thing():\n    pass\n")
    assert detect_verify_command(tmp_path).source == "pytest"


def test_npm_real_test_script(tmp_path: Path):
    _touch(tmp_path, "package.json", '{"scripts": {"test": "vitest run"}}')
    plan = detect_verify_command(tmp_path)
    assert plan.command == ["npm", "test"]
    assert plan.source == "npm"


def test_npm_default_placeholder_test_ignored(tmp_path: Path):
    # npm init 的占位 test 脚本不算真实验证
    _touch(tmp_path, "package.json",
           '{"scripts": {"test": "echo \\"Error: no test specified\\" && exit 1"}}')
    plan = detect_verify_command(tmp_path)
    assert plan.source == "none"
    assert plan.detected is False


def test_npm_build_fallback_when_no_test(tmp_path: Path):
    _touch(tmp_path, "package.json", '{"scripts": {"build": "tsc"}}')
    plan = detect_verify_command(tmp_path)
    assert plan.command == ["npm", "run", "build"]
    assert plan.confidence == "medium"


def test_pnpm_from_lockfile(tmp_path: Path):
    _touch(tmp_path, "package.json", '{"scripts": {"test": "jest"}}')
    _touch(tmp_path, "pnpm-lock.yaml", "lockfileVersion: 9\n")
    plan = detect_verify_command(tmp_path)
    assert plan.command == ["pnpm", "test"]
    assert plan.source == "pnpm"


def test_yarn_from_lockfile(tmp_path: Path):
    _touch(tmp_path, "package.json", '{"scripts": {"test": "jest"}}')
    _touch(tmp_path, "yarn.lock", "# yarn lockfile v1\n")
    assert detect_verify_command(tmp_path).source == "yarn"


def test_cargo(tmp_path: Path):
    _touch(tmp_path, "Cargo.toml", "[package]\nname = 'x'\n")
    plan = detect_verify_command(tmp_path)
    assert plan.command == ["cargo", "test"]
    assert plan.source == "cargo"


def test_go(tmp_path: Path):
    _touch(tmp_path, "go.mod", "module example.com/x\n\ngo 1.22\n")
    plan = detect_verify_command(tmp_path)
    assert plan.command == ["go", "test", "./..."]
    assert plan.source == "go"


def test_makefile_test_target_wins(tmp_path: Path):
    # Makefile 有 test 目标 → 优先于语言默认(即便同时有 pytest 信号)
    _touch(tmp_path, "Makefile", "build:\n\tgcc x.c\n\ntest:\n\t./run_tests.sh\n")
    _touch(tmp_path, "pytest.ini", "[pytest]\n")
    plan = detect_verify_command(tmp_path)
    assert plan.command == ["make", "test"]
    assert plan.source == "make"


def test_makefile_without_test_target_falls_through(tmp_path: Path):
    _touch(tmp_path, "Makefile", "build:\n\tgcc x.c\n")
    _touch(tmp_path, "Cargo.toml", "[package]\nname='x'\n")
    assert detect_verify_command(tmp_path).source == "cargo"


def test_no_signal_fallback(tmp_path: Path):
    _touch(tmp_path, "README.md", "# just docs\n")
    plan = detect_verify_command(tmp_path)
    assert plan.command == ["true"]
    assert plan.detected is False
    assert plan.confidence == "none"


def test_missing_dir():
    plan = detect_verify_command(Path("/nonexistent/xyz/123"))
    assert plan.detected is False
    assert plan.source == "none"


def test_malformed_package_json_falls_through(tmp_path: Path):
    _touch(tmp_path, "package.json", "{ this is not json ")
    _touch(tmp_path, "go.mod", "module x\n")
    # package.json 解析失败不该崩,继续往下探测到 go
    assert detect_verify_command(tmp_path).source == "go"


def test_priority_pytest_over_node(tmp_path: Path):
    # 同时有 pytest 和 node test:按文档优先级 pytest 先(Makefile 未命中时)
    _touch(tmp_path, "pytest.ini", "[pytest]\n")
    _touch(tmp_path, "package.json", '{"scripts": {"test": "jest"}}')
    assert detect_verify_command(tmp_path).source == "pytest"


def test_result_is_frozen(tmp_path: Path):
    _touch(tmp_path, "go.mod", "module x\n")
    plan = detect_verify_command(tmp_path)
    assert isinstance(plan, VerifyPlan)
    try:
        plan.source = "mutated"  # type: ignore[misc]
        raise AssertionError("VerifyPlan 应为 frozen 不可变")
    except AttributeError:
        pass
