"""性能指标收集（M5.1）：LLM token 使用、延迟、TTFT、上下文长度、错误。

设计为线程安全，可被 LangChain callback 与 orchestration-api /metrics 端点共享。
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.outputs import LLMResult


@dataclass
class LLMMetrics:
    total_calls: int = 0
    total_tokens: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_latency: float = 0.0
    ttft_total: float = 0.0
    errors: int = 0


@dataclass
class ContextMetrics:
    total_chars: int = 0
    total_messages: int = 0
    calls: int = 0


class MetricsCollector:
    """聚合 LLM 与上下文指标。线程安全。"""

    def __init__(self) -> None:
        self._llm = LLMMetrics()
        self._context = ContextMetrics()
        self._lock = threading.Lock()

    def record_llm_end(self, result: LLMResult, start_time: float, first_token_time: float | None) -> None:
        """在 LLM 调用结束时记录 token、延迟、TTFT。"""
        now = time.time()
        latency = now - start_time
        ttft = (first_token_time - start_time) if first_token_time else 0.0

        token_usage = (result.llm_output or {}).get("token_usage", {}) or {}
        # LangChain 在不同版本/模型下可能是 dict 或 list[dict]
        usages = token_usage if isinstance(token_usage, list) else [token_usage]
        total_tokens = sum(int(u.get("total_tokens", 0)) for u in usages)
        prompt_tokens = sum(int(u.get("prompt_tokens", 0)) for u in usages)
        completion_tokens = sum(int(u.get("completion_tokens", 0)) for u in usages)

        with self._lock:
            self._llm.total_calls += 1
            self._llm.total_latency += latency
            self._llm.ttft_total += ttft
            self._llm.total_tokens += total_tokens
            self._llm.prompt_tokens += prompt_tokens
            self._llm.completion_tokens += completion_tokens

    def record_llm_error(self) -> None:
        with self._lock:
            self._llm.errors += 1

    def record_context(self, *, chars: int, messages: int) -> None:
        """记录每次 LLM 请求的上下文规模（字符数、消息数）。"""
        with self._lock:
            self._context.total_chars += chars
            self._context.total_messages += messages
            self._context.calls += 1

    def snapshot(self) -> dict[str, Any]:
        """返回当前指标快照，供 /metrics 端点使用。"""
        with self._lock:
            llm = self._llm
            ctx = self._context
            calls = llm.total_calls
            ctx_calls = ctx.calls or 0
            return {
                "llm": {
                    "total_calls": calls,
                    "total_tokens": llm.total_tokens,
                    "prompt_tokens": llm.prompt_tokens,
                    "completion_tokens": llm.completion_tokens,
                    "total_latency_ms": round(llm.total_latency * 1000, 2),
                    "avg_latency_ms": round((llm.total_latency / calls) * 1000, 2) if calls else 0.0,
                    "avg_ttft_ms": round((llm.ttft_total / calls) * 1000, 2) if calls else 0.0,
                    "errors": llm.errors,
                },
                "context": {
                    "total_chars": ctx.total_chars,
                    "total_messages": ctx.total_messages,
                    "avg_chars": round(ctx.total_chars / ctx_calls, 2) if ctx_calls else 0.0,
                    "avg_messages": round(ctx.total_messages / ctx_calls, 2) if ctx_calls else 0.0,
                },
            }

    def reset(self) -> None:
        """重置所有指标（仅用于测试）。"""
        with self._lock:
            self._llm = LLMMetrics()
            self._context = ContextMetrics()


# 全局单例：API / orchestrator 共享
COLLECTOR = MetricsCollector()


class MetricsCallbackHandler(BaseCallbackHandler):
    """LangChain callback：在 LLM 调用过程中自动记录指标。"""

    def __init__(self, collector: MetricsCollector | None = None) -> None:
        super().__init__()
        self.collector = collector or COLLECTOR
        self._start_time: float | None = None
        self._first_token_time: float | None = None

    def on_llm_start(self, *args: Any, **kwargs: Any) -> Any:
        self._start_time = time.time()
        self._first_token_time = None

    def on_chat_model_start(self, serialized: dict[str, Any], messages: list[list[Any]], **kwargs: Any) -> Any:
        self._start_time = time.time()
        self._first_token_time = None
        # messages: list[generations] of list[BaseMessage]
        total_chars = 0
        total_messages = 0
        for batch in messages:
            total_messages += len(batch)
            for m in batch:
                content = getattr(m, "content", None) or ""
                total_chars += len(content)
        self.collector.record_context(chars=total_chars, messages=total_messages)

    def on_llm_new_token(self, *args: Any, **kwargs: Any) -> Any:
        if self._first_token_time is None:
            self._first_token_time = time.time()

    def on_llm_end(self, response: LLMResult, **kwargs: Any) -> Any:
        if self._start_time is not None:
            self.collector.record_llm_end(response, self._start_time, self._first_token_time)
        self._start_time = None
        self._first_token_time = None

    def on_llm_error(self, error: BaseException, **kwargs: Any) -> Any:
        self.collector.record_llm_error()
        self._start_time = None
        self._first_token_time = None
