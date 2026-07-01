"""M5.1 性能指标收集测试。"""
from __future__ import annotations

import time

from fastapi.testclient import TestClient
from langchain_core.outputs import LLMResult

from api.main import app
from metrics import COLLECTOR, MetricsCallbackHandler, MetricsCollector


class FakeMessage:
    def __init__(self, content: str):
        self.content = content


def test_collector_records_token_usage_and_latency():
    collector = MetricsCollector()
    start = time.time()
    result = LLMResult(
        generations=[],
        llm_output={"token_usage": {"total_tokens": 100, "prompt_tokens": 70, "completion_tokens": 30}},
    )
    collector.record_llm_end(result, start, start + 0.1)
    snap = collector.snapshot()
    assert snap["llm"]["total_calls"] == 1
    assert snap["llm"]["total_tokens"] == 100
    assert snap["llm"]["prompt_tokens"] == 70
    assert snap["llm"]["completion_tokens"] == 30
    assert snap["llm"]["avg_latency_ms"] > 0
    assert snap["llm"]["avg_ttft_ms"] > 0


def test_collector_handles_list_token_usage():
    collector = MetricsCollector()
    result = LLMResult(
        generations=[],
        llm_output={"token_usage": [
            {"total_tokens": 50, "prompt_tokens": 30, "completion_tokens": 20},
            {"total_tokens": 30, "prompt_tokens": 20, "completion_tokens": 10},
        ]},
    )
    collector.record_llm_end(result, time.time(), None)
    snap = collector.snapshot()
    assert snap["llm"]["total_tokens"] == 80
    assert snap["llm"]["prompt_tokens"] == 50
    assert snap["llm"]["completion_tokens"] == 30


def test_collector_records_context():
    collector = MetricsCollector()
    collector.record_context(chars=100, messages=5)
    collector.record_context(chars=200, messages=3)
    snap = collector.snapshot()
    assert snap["context"]["total_chars"] == 300
    assert snap["context"]["total_messages"] == 8
    assert snap["context"]["avg_chars"] == 150.0
    assert snap["context"]["avg_messages"] == 4.0


def test_callback_handler_records_context_and_tokens():
    collector = MetricsCollector()
    handler = MetricsCallbackHandler(collector=collector)
    handler.on_chat_model_start({}, [[FakeMessage("hello"), FakeMessage("world")]])
    result = LLMResult(
        generations=[],
        llm_output={"token_usage": {"total_tokens": 10, "prompt_tokens": 7, "completion_tokens": 3}},
    )
    handler.on_llm_end(result)
    snap = collector.snapshot()
    assert snap["llm"]["total_calls"] == 1
    assert snap["llm"]["total_tokens"] == 10
    assert snap["context"]["total_chars"] == 10
    assert snap["context"]["total_messages"] == 2


def test_callback_handler_records_error():
    collector = MetricsCollector()
    handler = MetricsCallbackHandler(collector=collector)
    handler.on_llm_error(RuntimeError("boom"))
    snap = collector.snapshot()
    assert snap["llm"]["errors"] == 1


def test_collector_reset():
    collector = MetricsCollector()
    collector.record_context(chars=100, messages=5)
    result = LLMResult(generations=[], llm_output={"token_usage": {"total_tokens": 10}})
    collector.record_llm_end(result, time.time(), None)
    collector.reset()
    snap = collector.snapshot()
    assert snap["llm"]["total_calls"] == 0
    assert snap["context"]["total_chars"] == 0


def test_metrics_endpoint():
    COLLECTOR.reset()
    result = LLMResult(generations=[], llm_output={"token_usage": {"total_tokens": 42}})
    handler = MetricsCallbackHandler(collector=COLLECTOR)
    handler.on_chat_model_start({}, [[FakeMessage("hi")]])
    handler.on_llm_end(result)
    with TestClient(app) as client:
        r = client.get("/api/v1/metrics")
        assert r.status_code == 200
        data = r.json()
        assert data["llm"]["total_tokens"] == 42
        assert data["context"]["total_messages"] == 1
