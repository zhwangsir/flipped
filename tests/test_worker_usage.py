"""F10 补全 — Worker(Kimi)沙盒会话 token 用量汇入全局统计。"""
from types import SimpleNamespace

from executor.openhands_worker import _sum_conversation_usage
from metrics.collector import MetricsCollector


def _state(metrics_map):
    return SimpleNamespace(stats=SimpleNamespace(usage_to_metrics=metrics_map))


def _metrics(prompt, completion, n_usages):
    return SimpleNamespace(
        accumulated_token_usage=SimpleNamespace(prompt_tokens=prompt, completion_tokens=completion),
        token_usages=[SimpleNamespace()] * n_usages,
    )


def test_sum_usage_across_llms():
    st = _state({"kimi": _metrics(1000, 400, 7), "aux": _metrics(50, 20, 1)})
    assert _sum_conversation_usage(st) == (1050, 420, 8)


def test_sum_usage_defensive_on_missing_fields():
    # 无 stats / 空 mapping / 缺 accumulated 都不崩,返回 0
    assert _sum_conversation_usage(SimpleNamespace()) == (0, 0, 0)
    assert _sum_conversation_usage(_state({})) == (0, 0, 0)
    st = _state({"x": SimpleNamespace(accumulated_token_usage=None, token_usages=None)})
    assert _sum_conversation_usage(st) == (0, 0, 0)


def test_collector_record_usage():
    c = MetricsCollector()
    c.record_usage(prompt_tokens=100, completion_tokens=40, calls=3)
    c.record_usage(prompt_tokens=10, completion_tokens=5)  # 默认 calls=1
    snap = c.snapshot()["llm"]
    assert snap["total_calls"] == 4
    assert snap["prompt_tokens"] == 110
    assert snap["completion_tokens"] == 45
    assert snap["total_tokens"] == 155


def test_collector_record_usage_clamps_negative():
    c = MetricsCollector()
    c.record_usage(prompt_tokens=-5, completion_tokens=10, calls=-1)
    snap = c.snapshot()["llm"]
    assert snap["prompt_tokens"] == 0 and snap["completion_tokens"] == 10
    assert snap["total_calls"] == 0
