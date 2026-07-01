"""Context / KV cache management (M5.2).

Provides pluggable token estimation, history compaction, and a checkpoint
retention policy for the LangGraph SqliteSaver.
"""

from __future__ import annotations

import json
from typing import Any, Callable

try:
    from tiktoken import get_encoding
    _TIKTOKEN = get_encoding("cl100k_base")
except Exception:
    _TIKTOKEN = None

Estimator = Callable[[Any], int]


def simple_estimator(obj: Any) -> int:
    """Approximate token count using a mixed-character heuristic (chars / 2.5)."""
    if obj is None:
        return 0
    text = json.dumps(obj, ensure_ascii=False) if not isinstance(obj, str) else obj
    return max(1, int(len(text) / 2.5 + 0.5))


def tiktoken_estimator(obj: Any) -> int:
    """Exact token count using tiktoken, if available."""
    if _TIKTOKEN is None:
        raise RuntimeError("tiktoken is not installed")
    text = json.dumps(obj, ensure_ascii=False) if not isinstance(obj, str) else obj
    return len(_TIKTOKEN.encode(text))


def estimate_tokens(history: list[Any], estimator: Estimator = simple_estimator) -> int:
    """Sum token estimates across a sequence of items."""
    return sum(estimator(item) for item in history)


def _default_summarizer(old_items: list[dict], tokens_before: int, retained: int) -> dict:
    """Non-LLM summarizer: keeps step types and a short digest of old items."""
    digest_parts: list[str] = []
    total = 0
    for item in old_items:
        short = json.dumps(item, ensure_ascii=False)
        if total + len(short) > 400:
            digest_parts.append(f"... +{len(old_items) - len(digest_parts)} more")
            break
        digest_parts.append(short)
        total += len(short)
    return {
        "step": "summary",
        "tokens_before": tokens_before,
        "items": len(old_items),
        "retained": retained,
        "digest": "\n".join(digest_parts),
    }


def compress_history(
    history: list[dict],
    max_tokens: int,
    keep_recent: int = 4,
    estimator: Estimator = simple_estimator,
    summarizer: Callable[[list[dict], int, int], dict] | None = None,
) -> dict:
    """Compress history when it exceeds max_tokens by summarizing old items.

    Returns a dict with keys:
      - history: the new history (original if no compression needed)
      - compressed: bool
      - summary: the summary dict or None
      - tokens_before, tokens_after: estimated token counts
    """
    tokens_before = estimate_tokens(history, estimator)
    if tokens_before <= max_tokens or len(history) <= keep_recent:
        return {
            "history": history,
            "compressed": False,
            "summary": None,
            "tokens_before": tokens_before,
            "tokens_after": tokens_before,
        }
    old = history[:-keep_recent]
    recent = history[-keep_recent:]
    if summarizer is None:
        summary = _default_summarizer(old, tokens_before, len(recent))
    else:
        summary = summarizer(old, tokens_before, len(recent))
    new_history = [summary] + recent
    tokens_after = estimate_tokens(new_history, estimator)
    return {
        "history": new_history,
        "compressed": True,
        "summary": summary,
        "tokens_before": tokens_before,
        "tokens_after": tokens_after,
    }


class CheckpointRetention:
    """Trim old checkpoints from a LangGraph SqliteSaver, keeping the latest N."""

    def __init__(self, saver: Any, max_checkpoints: int = 100):
        self.saver = saver
        self.max_checkpoints = max(max_checkpoints, 1)

    def trim(self, thread_id: str, checkpoint_ns: str = "") -> None:
        """Delete all but the latest max_checkpoints for a thread."""
        with self.saver.cursor() as cur:
            cur.execute(
                "SELECT checkpoint_id FROM checkpoints "
                "WHERE thread_id = ? AND checkpoint_ns = ? "
                "ORDER BY rowid DESC LIMIT ?",
                (str(thread_id), str(checkpoint_ns), self.max_checkpoints),
            )
            kept = {row[0] for row in cur.fetchall()}
            if not kept:
                return
            placeholders = ",".join("?" * len(kept))
            params = (str(thread_id), str(checkpoint_ns), *kept)
            cur.execute(
                f"DELETE FROM writes WHERE thread_id = ? AND checkpoint_ns = ? "
                f"AND checkpoint_id NOT IN ({placeholders})",
                params,
            )
            cur.execute(
                f"DELETE FROM checkpoints WHERE thread_id = ? AND checkpoint_ns = ? "
                f"AND checkpoint_id NOT IN ({placeholders})",
                params,
            )
