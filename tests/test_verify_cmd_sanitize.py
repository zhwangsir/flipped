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


def test_sanitize_bare_assert_wrapped_in_python_c():
    """M156.12：裸 assert → python -c "assert ..."（assert 是 Python 关键字非 shell 命令）。

    GLM planner 偶发生成裸 `assert "x" == "$(python hello.py)"` 作为 verify_cmd，
    被 safety.is_safe_command 白名单拦截 → circuit_breaker → task failed。
    包裹成 python -c 让 assert 语句合法执行（含 shell $() 替换的会失败但给出真实错误）。
    """
    from driving.factory_loop import _sanitize_verify_cmd

    # 纯 Python 表达式的裸 assert → 包裹后能执行
    result = _sanitize_verify_cmd(["assert os.path.isfile('hello.py')"])
    assert result == ['python -c "assert os.path.isfile(\'hello.py\')"']

    # 含 shell 替换的裸 assert → 包裹后执行会失败，但 safety 不拦截（可诊断）
    result = _sanitize_verify_cmd(['assert "hello" == "$(python hello.py)"'])
    assert result[0].startswith('python -c "assert ')
    assert "safety" not in result[0]  # 不再被 safety 拦截


def test_sanitize_python_c_with_assert_not_affected():
    """M156.12：python -c 里已有的 assert 不受裸 assert 改写影响。"""
    from driving.factory_loop import _sanitize_verify_cmd

    # 已经是 python -c "...assert..." 的不改写
    original = ['python -c "import calc; assert calc.add(1,2)==3"']
    result = _sanitize_verify_cmd(original)
    assert result == original

    # python -m pytest ... 不受影响
    original = ["python -m pytest tests/test_calc.py -q"]
    result = _sanitize_verify_cmd(original)
    assert result == original


def test_planner_prompt_forbids_bare_assert():
    """M156.12：planner prompt 必须含禁止裸 assert 的规则。
    M156.15c：python → python3（macOS 无 python 命令）。"""
    import inspect
    from driving.factory_loop import default_planner

    src = inspect.getsource(default_planner)
    assert "裸 assert" in src
    assert "python3 -c / python3 -m pytest / bash / test" in src
