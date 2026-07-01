"""Tests for context / KV cache management helpers."""
import os
import sqlite3
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from driving.context_manager import (  # noqa: E402
    CheckpointRetention,
    compress_history,
    estimate_tokens,
    simple_estimator,
    tiktoken_estimator,
)


def test_simple_estimator_counts():
    assert simple_estimator("a" * 10) == 4  # 10 / 2.5 = 4
    assert simple_estimator("") == 1        # max(1, 0) = 1
    assert simple_estimator(None) == 0


def test_estimate_tokens_sums_items():
    history = [{"step": "a"}, {"step": "b"}]
    total = estimate_tokens(history, simple_estimator)
    assert total == sum(simple_estimator(item) for item in history)


def test_compress_history_no_compression_when_under_limit():
    history = [{"step": i} for i in range(3)]
    result = compress_history(history, max_tokens=1000, keep_recent=2)
    assert result["compressed"] is False
    assert result["history"] is history
    assert result["summary"] is None
    assert result["tokens_before"] == result["tokens_after"]


def test_compress_history_triggers_above_limit():
    long_data = "x" * 200
    history = [{"step": i, "data": long_data} for i in range(5)]
    result = compress_history(history, max_tokens=100, keep_recent=2)
    assert result["compressed"] is True
    assert len(result["history"]) == 3  # summary + 2 recent
    assert result["history"][0]["step"] == "summary"
    assert result["history"][-2:] == history[-2:]
    assert result["tokens_before"] > result["tokens_after"]


def test_compress_history_custom_summarizer():
    def custom(old, tokens_before, retained):
        return {"custom": True, "old_count": len(old), "retained": retained}

    long_data = "x" * 200
    history = [{"step": i, "data": long_data} for i in range(5)]
    result = compress_history(history, max_tokens=100, keep_recent=2, summarizer=custom)
    assert result["summary"] == {"custom": True, "old_count": 3, "retained": 2}


def test_compress_history_preserves_short_history():
    # Even if tokens exceed max, do not compress when there are not enough
    # items to keep_recent+1 so we don't lose all context.
    long_data = "x" * 500
    history = [{"data": long_data}, {"data": long_data}]
    result = compress_history(history, max_tokens=10, keep_recent=2)
    assert result["compressed"] is False


def test_checkpoint_retention_keeps_latest_n():
    class FakeSaver:
        def __init__(self, conn):
            self.conn = conn

        def cursor(self):
            class CM:
                def __init__(self, conn):
                    self.conn = conn

                def __enter__(self):
                    return self.conn.cursor()

                def __exit__(self, *args):
                    self.conn.commit()

            return CM(self.conn)

    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE checkpoints (thread_id TEXT, checkpoint_ns TEXT, checkpoint_id TEXT)"
    )
    conn.execute(
        "CREATE TABLE writes (thread_id TEXT, checkpoint_ns TEXT, checkpoint_id TEXT)"
    )
    for i in range(5):
        conn.execute(
            "INSERT INTO checkpoints VALUES (?, ?, ?)", ("t1", "", f"c{i}")
        )
        conn.execute("INSERT INTO writes VALUES (?, ?, ?)", ("t1", "", f"c{i}"))
    for i in range(3):
        conn.execute(
            "INSERT INTO checkpoints VALUES (?, ?, ?)", ("t2", "", f"d{i}")
        )
        conn.execute("INSERT INTO writes VALUES (?, ?, ?)", ("t2", "", f"d{i}"))

    saver = FakeSaver(conn)
    CheckpointRetention(saver, max_checkpoints=2).trim("t1")

    cur = conn.cursor()
    t1_check = cur.execute(
        "SELECT checkpoint_id FROM checkpoints WHERE thread_id = 't1'"
    ).fetchall()
    t2_check = cur.execute(
        "SELECT checkpoint_id FROM checkpoints WHERE thread_id = 't2'"
    ).fetchall()
    t1_writes = cur.execute(
        "SELECT checkpoint_id FROM writes WHERE thread_id = 't1'"
    ).fetchall()

    assert len(t1_check) == 2
    assert {row[0] for row in t1_check} == {"c3", "c4"}
    assert len(t2_check) == 3  # untouched
    assert len(t1_writes) == 2


def test_tiktoken_estimator_requires_installed():
    try:
        tiktoken_estimator("hello")
    except RuntimeError as exc:
        assert "tiktoken is not installed" in str(exc)
    else:
        # tiktoken is available; just verify it returns a non-negative int
        assert tiktoken_estimator("hello") >= 0
