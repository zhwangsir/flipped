"""性能基准测试（TEST_STRATEGY_OPTIMIZATION.md §2）。

用 pytest-benchmark 测量后端核心函数的执行延迟，建立性能基线。
每次代码变更后重跑，对比基线检测回归。

跑法:
  PYTHONPATH=src .venv/bin/python -m pytest tests/benchmarks/test_perf_benchmark.py \
    --benchmark-only --benchmark-json=reports/benchmark.json -q
"""
from __future__ import annotations

import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

import pytest  # noqa: E402

from driving.safety import is_safe_command  # noqa: E402
from driving.approval import classify_risk  # noqa: E402
from driving.factory_loop import _deterministic_roadmap, _next_task  # noqa: E402
from driving.factory_loop import FactoryState, FactoryStatus, FactoryTask, TaskStatus  # noqa: E402


# ---------- 安全护栏性能 ----------


def test_benchmark_is_safe_command_safe(benchmark):
    """is_safe_command 对安全命令的判定延迟基线。

    目标: P95 < 1ms（纯正则匹配，无 IO）。
    """
    result = benchmark(is_safe_command, "python3 -c 'print(1)'")
    assert result[0] is True


def test_benchmark_is_safe_command_complex(benchmark):
    """is_safe_command 对复杂管道命令的判定延迟基线。"""
    result = benchmark(is_safe_command, "cat file.py | grep import | head -10")
    assert result[0] is True


def test_benchmark_classify_risk(benchmark):
    """classify_risk 风险分级延迟基线。"""
    result = benchmark(classify_risk, "python3 -c 'print(1)'")
    assert result in ("low", "medium", "high")


# ---------- Factory Loop 调度性能 ----------


def test_benchmark_deterministic_roadmap(benchmark):
    """_deterministic_roadmap 生成确定性 roadmap 的延迟基线。

    目标: P95 < 50ms（纯字符串构造，无 LLM 调用）。
    """
    tasks = benchmark(_deterministic_roadmap, "做一个落地页", "/tmp")
    assert len(tasks) >= 2


def test_benchmark_next_task(benchmark):
    """_next_task 任务选择延迟基线。

    目标: P95 < 0.1ms（列表遍历，无 IO）。
    """
    state = FactoryState(
        factory_id="bench",
        product_goal="test",
        cwd="/tmp",
        status=FactoryStatus.running,
        roadmap=[FactoryTask(description=f"task-{i}") for i in range(10)],
    )
    task = benchmark(_next_task, state)
    assert task is not None


# ---------- 模型路由性能 ----------


def test_benchmark_model_config_resolution(benchmark):
    """resolve_worker_model_config 路由决策延迟基线。

    目标: P95 < 5ms（env 读取 + dict lookup）。
    """
    from driving.model_router import resolve_worker_model_config

    with patch.dict(os.environ, {"FLIPPED_MODEL_MODE": "single"}, clear=False):
        result = benchmark(resolve_worker_model_config, "supervisor")
        # 返回 (base_url, model_id) 元组
        assert isinstance(result, tuple) and len(result) == 2


# ---------- JSON 解析性能 ----------


def test_benchmark_json_repair_trailing_commas(benchmark):
    """_repair_json_trailing_commas JSON 修复延迟基线（M156.15）。"""
    from driving.orchestrator import _repair_json_trailing_commas

    text = '{"tasks": [{"id": "task1", "desc": "test",}, {"id": "task2", "desc": "test2",}],}'
    result = benchmark(_repair_json_trailing_commas, text)
    assert "tasks" in result


# ---------- 路径翻译性能（M156.17） ----------


def test_benchmark_to_container_path(benchmark):
    """_to_container_path 路径翻译延迟基线（M156.17）。

    目标: P95 < 0.01ms（纯字符串操作）。
    """
    from executor.sandbox_verify import _to_container_path

    # 用实际 home 目录构造路径，确保 _to_container_path 能翻译
    home = os.path.expanduser("~")
    host_path = os.path.join(home, "projects", "flipped_demo")
    result = benchmark(_to_container_path, host_path)
    assert result == "/projects/flipped_demo"
