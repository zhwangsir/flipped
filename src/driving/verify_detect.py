"""验收命令探测(F1a · 自主开发工厂地基)。

自主循环的心脏是**自我验证**:写完码要能自己跑测/构建判定成败。orchestrator 之前
`verify_cmd` 默认 `["true"]`(永远通过)= 循环空转、自主是假的。本模块读项目文件
推断该项目**如何验证自己**(pytest / npm test / cargo test / go test / make test …),
纯函数、无副作用、完全可测。

WHERE 命令在哪儿跑(host bind-mount 目录 vs 沙盒)是接线层(F1c/F1d)的事,这里只管
WHAT 命令是什么。

优先级(首个命中即返回,polyglot 仓库由 confidence 让调用方决断):
  1. Makefile 有 `test:` 目标          → make test        (high)
  2. Python pytest 信号                 → pytest -q        (high)
  3. Node package.json 真实 test 脚本   → <pm> test        (high)
  4. Rust Cargo.toml                    → cargo test       (high)
  5. Go go.mod                          → go test ./...    (high)
  6. Node package.json 有 build 无 test → <pm> run build   (medium, 退而求编译通过)
  7. 都没有                             → true             (none, detected=False)
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class VerifyPlan:
    """一次验收探测的结果(不可变 DTO)。"""

    command: list[str]   # 传给 orchestrator 的 argv,如 ["pytest", "-q"]
    label: str           # 人读:"pytest -q"
    source: str          # pytest|npm|pnpm|yarn|bun|cargo|go|make|none
    confidence: str      # high|medium|none
    detected: bool       # 仅 "none" 兜底为 False


_NPM_NO_TEST = "no test specified"  # npm 默认占位 test 脚本的标志串
_MAKE_TEST_TARGET = re.compile(r"^test\s*:", re.MULTILINE)


def _read_text(path: Path, limit: int = 200_000) -> str:
    try:
        return path.read_text(encoding="utf-8")[:limit]
    except (OSError, UnicodeDecodeError):
        return ""


def _detect_package_manager(root: Path) -> str:
    """按 lockfile 推断 Node 包管理器,默认 npm。"""
    if (root / "pnpm-lock.yaml").is_file():
        return "pnpm"
    if (root / "yarn.lock").is_file():
        return "yarn"
    if (root / "bun.lockb").is_file() or (root / "bun.lock").is_file():
        return "bun"
    return "npm"


def _has_pytest_signal(root: Path) -> bool:
    """项目是否用 pytest(配置文件 / 约定目录 / 测试文件)。"""
    if (root / "pytest.ini").is_file() or (root / "conftest.py").is_file():
        return True
    if (root / "tests").is_dir() or (root / "test").is_dir():
        return True
    pyproject = _read_text(root / "pyproject.toml")
    if "[tool.pytest" in pyproject:
        return True
    if "[tool:pytest]" in _read_text(root / "setup.cfg"):
        return True
    # 根目录直接摆着的测试文件
    for pattern in ("test_*.py", "*_test.py"):
        if next(root.glob(pattern), None) is not None:
            return True
    return False


def _node_plan(root: Path) -> VerifyPlan | None:
    """解析 package.json 的 scripts,优先 test,退而 build。"""
    raw = _read_text(root / "package.json")
    if not raw:
        return None
    try:
        pkg = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return None
    scripts = pkg.get("scripts") or {}
    if not isinstance(scripts, dict):
        return None
    pm = _detect_package_manager(root)
    test_script = str(scripts.get("test") or "")
    if test_script and _NPM_NO_TEST not in test_script.lower():
        cmd = [pm, "test"]
        return VerifyPlan(command=cmd, label=" ".join(cmd), source=pm,
                          confidence="high", detected=True)
    if scripts.get("build"):
        cmd = [pm, "run", "build"]
        return VerifyPlan(command=cmd, label=" ".join(cmd), source=pm,
                          confidence="medium", detected=True)
    return None


def detect_verify_command(root: Path) -> VerifyPlan:
    """探测该项目根的验收命令。root 不存在或无信号 → detected=False 的 `true` 兜底。"""
    if not root.is_dir():
        return VerifyPlan(command=["true"], label="(无验证)", source="none",
                          confidence="none", detected=False)

    # 1) Makefile 的 test 目标 = 项目钦定入口,最高优先
    for makefile in ("Makefile", "makefile", "GNUmakefile"):
        text = _read_text(root / makefile)
        if text and _MAKE_TEST_TARGET.search(text):
            return VerifyPlan(command=["make", "test"], label="make test",
                              source="make", confidence="high", detected=True)

    # 2) Python pytest — 用 `python3 -m pytest`:F8 真机实测发现沙盒 sh 的 PATH 里
    #    没有裸 `pytest` 入口脚本(pip 装了包但 /bin/sh 找不到命令),-m 形式跨环境稳。
    if _has_pytest_signal(root):
        return VerifyPlan(command=["python3", "-m", "pytest", "-q"], label="python3 -m pytest -q",
                          source="pytest", confidence="high", detected=True)

    # 3) Node(真实 test 脚本,退而 build)
    node = _node_plan(root)
    if node is not None:
        return node

    # 4) Rust
    if (root / "Cargo.toml").is_file():
        return VerifyPlan(command=["cargo", "test"], label="cargo test",
                          source="cargo", confidence="high", detected=True)

    # 5) Go
    if (root / "go.mod").is_file():
        return VerifyPlan(command=["go", "test", "./..."], label="go test ./...",
                          source="go", confidence="high", detected=True)

    # 6) 兜底:没有可信验证命令
    return VerifyPlan(command=["true"], label="(未检测到验证命令)", source="none",
                      confidence="none", detected=False)
