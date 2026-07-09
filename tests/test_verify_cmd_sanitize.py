"""测试 verify_cmd 单行约束与 planner 兜底（M9 稳定性修复）。

T3 熔断的根因是 GLM 生成多行 Python 用 && 连接，python -c 无法执行。
这里验证两道防线：prompt 约束 + _sanitize_verify_cmd 后处理。
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))


def test_sanitize_empty_returns_true():
    from driving.factory_loop import _sanitize_verify_cmd
    assert _sanitize_verify_cmd([]) == ["true"]
    assert _sanitize_verify_cmd([""]) == ["true"]
    assert _sanitize_verify_cmd(["", "  "]) == ["true"]


def test_sanitize_single_passthrough():
    from driving.factory_loop import _sanitize_verify_cmd
    cmd = ["python -m pytest tests/test_calc.py -q"]
    assert _sanitize_verify_cmd(cmd) == ["python -m pytest tests/test_calc.py -q"]


def test_sanitize_bare_pytest_replaced():
    """裸 pytest（沙箱 PATH 里没有 pytest 可执行文件）→ python -m pytest。

    T3 熔断根因：OpenHands 沙箱 `pytest: command not found`。
    """
    from driving.factory_loop import _sanitize_verify_cmd
    assert _sanitize_verify_cmd(["pytest tests/test_calc.py -q"]) == [
        "python -m pytest tests/test_calc.py -q"
    ]
    # 已正确的不重复替换
    assert _sanitize_verify_cmd(["python -m pytest tests/"]) == [
        "python -m pytest tests/"
    ]
    # 多命令里的裸 pytest 也替换
    result = _sanitize_verify_cmd(["echo hi", "pytest tests/"])
    assert "python -m pytest tests/" in result[0]


def test_sanitize_multi_element_joined_with_semicolon():
    from driving.factory_loop import _sanitize_verify_cmd
    cmd = ["python -c \"import calc\"", "pytest tests/test_calc.py"]
    result = _sanitize_verify_cmd(cmd)
    assert len(result) == 1
    assert ";" in result[0]
    # 不用 && 连接（避免短路）
    assert "&&" not in result[0]


def test_sanitize_newlines_collapsed():
    from driving.factory_loop import _sanitize_verify_cmd
    cmd = ["python -c \"def f():\n  return 1\n\nf()\""]
    result = _sanitize_verify_cmd(cmd)
    assert len(result) == 1
    assert "\n" not in result[0]


def test_sanitize_multiline_python_compactified():
    """T3 的真实故障场景：多行 python -c 代码"""
    from driving.factory_loop import _sanitize_verify_cmd
    cmd = ["python -c \"\nimport calc\nassert calc.add(1,2)==3\nassert calc.mul(2,3)==6\n\""]
    result = _sanitize_verify_cmd(cmd)
    assert len(result) == 1
    assert "\n" not in result[0]
    # 所有断言还在
    assert "add" in result[0] and "mul" in result[0]


def test_planner_prompt_contains_verify_cmd_rules():
    """验证 planner prompt 里有硬性约束文本"""
    from driving.factory_loop import default_planner, FactoryState
    # 用一个会抛异常的 mock 拿到 prompt 不容易，直接检查源码
    import inspect
    src = inspect.getsource(default_planner)
    assert "verify_cmd" in src
    assert "单行" in src or "单元素" in src
    assert "禁止" in src
