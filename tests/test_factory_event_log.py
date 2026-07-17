"""M136-A · factory_events append-only 日志 + 幂等键崩溃恢复单测（确定性，无需真 LLM）。"""
from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest  # noqa: E402

from driving.event_log import (  # noqa: E402
    append_event,
    ensure_event_table,
    list_events,
    seen_idempotency_key,
)
from driving.factory_loop import (  # noqa: E402
    FactoryState,
    FactoryStatus,
    FactoryTask,
    TaskResult,
    TaskStatus,
    load_factory_state,
    run_factory_loop,
    save_factory_state,
)


@pytest.fixture
def tmp_db():
    with tempfile.TemporaryDirectory() as td:
        yield Path(td) / "factory.db"


@pytest.fixture
def tmp_cwd():
    with tempfile.TemporaryDirectory() as td:
        yield td


@pytest.fixture
def mem_conn():
    conn = sqlite3.connect(":memory:")
    yield conn
    conn.close()


# ---------- 事件表迁移 ----------


def test_ensure_event_table_creates_table_and_is_idempotent(mem_conn):
    ensure_event_table(mem_conn)
    ensure_event_table(mem_conn)  # 第二次调用不报错（幂等迁移）

    tables = {r[0] for r in mem_conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert "factory_events" in tables

    cols = {row[1] for row in mem_conn.execute("PRAGMA table_info(factory_events)")}
    assert {"seq", "factory_id", "ts", "kind", "payload_json", "idempotency_key"} <= cols

    indexes = {r[0] for r in mem_conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='factory_events'")}
    assert "idx_factory_events_fid_seq" in indexes
    assert "idx_factory_events_idempotency" in indexes


# ---------- append / list ----------


def test_append_event_returns_increasing_seq_and_list_filters_after_seq(mem_conn):
    ensure_event_table(mem_conn)
    seqs = [
        append_event(mem_conn, "f1", "factory_start", {"goal": "g"}),
        append_event(mem_conn, "f1", "task_start", {"task_id": "t1"}),
        append_event(mem_conn, "f1", "verify_result", {"task_id": "t1", "verified": True}),
        append_event(mem_conn, "f2", "factory_start", {"goal": "other"}),
    ]
    assert all(s is not None for s in seqs)
    assert seqs == sorted(seqs)  # seq 递增

    events = list_events(mem_conn, "f1")
    assert len(events) == 3  # f2 的事件被隔离
    assert [e["kind"] for e in events] == ["factory_start", "task_start", "verify_result"]
    assert events[0]["payload"] == {"goal": "g"}
    assert events[2]["payload"]["verified"] is True
    assert all(e["factory_id"] == "f1" for e in events)

    # after_seq 增量过滤：只返回 seq > 指定值的事件
    incremental = list_events(mem_conn, "f1", after_seq=events[0]["seq"])
    assert [e["kind"] for e in incremental] == ["task_start", "verify_result"]

    assert list_events(mem_conn, "nonexistent") == []


# ---------- 幂等键 ----------


def test_idempotency_key_uniqueness_and_seen_roundtrip(mem_conn):
    ensure_event_table(mem_conn)

    key = "f1:task-1:done"
    assert seen_idempotency_key(mem_conn, key) is False

    first = append_event(mem_conn, "f1", "task_done", {"task_id": "task-1"},
                         idempotency_key=key)
    assert first is not None
    assert seen_idempotency_key(mem_conn, key) is True

    # 设计决策：重复幂等键 → 返回 None（不抛异常、不插重复行）。
    # 调用方用 seen_idempotency_key 判断是否跳过副作用。
    dup = append_event(mem_conn, "f1", "task_done", {"task_id": "task-1"},
                       idempotency_key=key)
    assert dup is None
    events = list_events(mem_conn, "f1")
    assert len([e for e in events if e["kind"] == "task_done"]) == 1

    # 不同 key 不受影响
    other = append_event(mem_conn, "f1", "task_done", {"task_id": "task-2"},
                         idempotency_key="f1:task-2:done")
    assert other is not None

    # 无幂等键（NULL）的事件可重复插入（SQLite 唯一索引允许多个 NULL）
    n1 = append_event(mem_conn, "f1", "verify_result", {"v": 1})
    n2 = append_event(mem_conn, "f1", "verify_result", {"v": 2})
    assert n1 is not None and n2 is not None and n1 != n2


# ---------- fail-open ----------


def test_event_log_fail_open_on_closed_connection():
    conn = sqlite3.connect(":memory:")
    conn.close()
    # 所有操作 fail-open，绝不抛进主流程
    assert append_event(conn, "f", "k", {}) is None
    assert seen_idempotency_key(conn, "x") is False
    assert list_events(conn, "f") == []


def test_run_factory_loop_survives_broken_event_log(tmp_db, tmp_cwd, monkeypatch):
    """事件写入全面抛异常时，主循环不受影响（fail-open 退化为旧路径）。"""
    import driving.factory_loop as fl

    monkeypatch.setattr(fl, "append_event",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("db on fire")))
    monkeypatch.setattr(fl, "seen_idempotency_key",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("db on fire")))

    def stub_planner(state):
        return [FactoryTask(description="t", verify_cmd=["true"])]

    def stub_orchestrator(task, state):
        return TaskResult(task=task, verified=True, stop_reason="verified",
                          iteration=1, summary="ok")

    result = run_factory_loop(
        product_goal="g", cwd=tmp_cwd, db_path=str(tmp_db),
        planner=stub_planner, orchestrator_fn=stub_orchestrator, max_tasks=5,
    )
    assert result.status == FactoryStatus.done
    assert len(result.completed) == 1


# ---------- 崩溃恢复 drill：完成副作用幂等 ----------


def test_crash_recovery_completion_side_effects_not_duplicated(tmp_db, tmp_cwd):
    """崩溃恢复重放同一 task 时，context_summary/quality_history/completed 不重复追加。

    场景：task 完成 → 副作用已应用并保存 → 崩溃 → 调度层把任务重置为 pending 重跑
    （工具副作用重执行不可避免），再次 verified → 幂等键守卫跳过重复的完成副作用。
    """
    holder: dict = {}

    def stub_planner(state: FactoryState) -> list[FactoryTask]:
        t = FactoryTask(description="crash drill task", verify_cmd=["true"])
        holder["task_id"] = t.id
        return [t]

    call_count = [0]

    def stub_orchestrator(task: FactoryTask, state: FactoryState) -> TaskResult:
        call_count[0] += 1
        return TaskResult(task=task, verified=True, stop_reason="verified",
                          iteration=1, summary="ok")

    result = run_factory_loop(
        product_goal="crash drill", cwd=tmp_cwd, db_path=str(tmp_db),
        planner=stub_planner, orchestrator_fn=stub_orchestrator, max_tasks=10,
    )
    assert result.status == FactoryStatus.done
    fid, tid = result.factory_id, holder["task_id"]
    ctx_entries_first = result.context_summary.count(f"[{tid}]")
    qhist_first = len(result.quality_history)
    completed_first = len(result.completed)
    assert ctx_entries_first == 1

    # --- 模拟崩溃：任务完成副作用已落库，但调度层认为任务还没跑完 ---
    crashed = load_factory_state(fid, str(tmp_db))
    for t in crashed.roadmap:
        if t.id == tid:
            t.status = TaskStatus.pending  # resume 路径会把 running 重置为 pending
    crashed.status = FactoryStatus.running
    crashed.current_task_id = None
    save_factory_state(crashed, str(tmp_db))

    # --- 新连接 resume（模拟进程重启）---
    result2 = run_factory_loop(
        product_goal="crash drill", cwd=tmp_cwd, db_path=str(tmp_db),
        factory_id=fid, planner=stub_planner, orchestrator_fn=stub_orchestrator,
        max_tasks=10,
    )
    assert call_count[0] == 2, "任务确实被重跑（重执行不可避，但副作用须幂等）"
    assert result2.context_summary.count(f"[{tid}]") == 1, "context_summary 不得重复追加"
    assert len(result2.quality_history) == qhist_first, "quality_history 不得重复追加"
    assert len(result2.completed) == completed_first, "completed 不得重复追加"

    # --- 事件连续性 + 去重断言 ---
    with sqlite3.connect(str(tmp_db)) as conn:
        events = list_events(conn, fid)
    seqs = [e["seq"] for e in events]
    assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs), "seq 严格递增无空洞重复"
    kinds = [e["kind"] for e in events]
    assert kinds.count("factory_start") == 1
    assert kinds.count("task_start") == 1, "task_start 幂等键去重（重跑不重复记录）"
    assert kinds.count("verify_result") == 2, "两次运行各记一次 verify_result"
    assert kinds.count("task_done") == 1, "task_done 幂等键去重（重跑不重复记录）"
    # 事件负载可用
    done_evt = next(e for e in events if e["kind"] == "task_done")
    assert done_evt["payload"]["task_id"] == tid
    assert done_evt["idempotency_key"] == f"{fid}:{tid}:done"


if __name__ == "__main__":
    test_idempotency_key_uniqueness_and_seen_roundtrip(sqlite3.connect(":memory:"))
    print("factory_event_log 单测: 通过 ✅")
