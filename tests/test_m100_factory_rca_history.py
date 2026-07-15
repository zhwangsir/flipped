"""M100 — Factory RCA 历史聚合视图测试。

测试覆盖:
1. factory 无 RCA → 端点返回空列表
2. factory 有 RCA(预置 rca_history) → 端点返回历史
3. cause_stats 聚合正确(按 cause 计数)
4. factory 不存在 → 404
5. factory_loop 触发 verify 失败 → rca_history 自动追加

测试方法:TDD — 端点+state 字段已实现,这里验证契约。
"""
from __future__ import annotations

import importlib
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("FLIPPED_MOCK_WORKER", "1")
os.environ.setdefault("FLIPPED_MOCK_APPROVAL", "1")

import src.api.main as _main  # noqa: E402
from driving.factory_loop import (  # noqa: E402
    FactoryRcaEntry,
    FactoryState,
    FactoryStatus,
    FactoryTask,
    TaskResult,
    TaskStatus,
    load_factory_state,
    save_factory_state,
    run_factory_loop,
)


@pytest.fixture
def tmp_factory_db(monkeypatch, tmp_path):
    db = str(tmp_path / "m100_factory_test.db")
    monkeypatch.setenv("FLIPPED_FACTORY_DB", db)
    import src.api.factory as factory_mod
    monkeypatch.setattr(factory_mod, "FACTORY_DB", db)
    return db


@pytest.fixture
def client(monkeypatch, tmp_factory_db):
    monkeypatch.setenv("FLIPPED_MOCK_WORKER", "1")
    importlib.reload(_main)
    with TestClient(_main.app) as tc:
        yield tc


@pytest.fixture
def tmp_db():
    """临时 factory SQLite db 路径(独立于 API 端点测试用的 tmp_factory_db)。"""
    with tempfile.TemporaryDirectory() as td:
        yield Path(td) / "factory.db"


@pytest.fixture
def tmp_cwd():
    """临时工作目录,模拟沙盒 cwd。"""
    with tempfile.TemporaryDirectory() as td:
        yield td


def _make_factory_with_rca(db_path: str, factory_id: str = "m100-factory-rca",
                           rca_entries: list[FactoryRcaEntry] | None = None) -> FactoryState:
    """预置一个工厂状态(含 RCA 历史),持久化到 db_path。"""
    state = FactoryState(
        factory_id=factory_id,
        product_goal="M100 测试工厂",
        cwd="/tmp",
        status=FactoryStatus.paused,
        roadmap=[FactoryTask(id="t-1", description="任务一", verify_cmd=["true"])],
        max_tasks=5,
        rca_history=rca_entries or [],
    )
    save_factory_state(state, db_path)
    return state


# ---------- 1. 无 RCA → 空列表 ----------


def test_endpoint_returns_empty_list_when_no_rca(client, tmp_factory_db):
    """工厂无 RCA 历史 → 端点返回空 rca_history 列表 + 空 cause_stats。"""
    _make_factory_with_rca(tmp_factory_db, rca_entries=[])

    r = client.get("/api/v1/factories/m100-factory-rca/rca_history")
    assert r.status_code == 200
    body = r.json()
    assert body["factory_id"] == "m100-factory-rca"
    assert body["rca_history"] == []
    assert body["cause_stats"] == {}


# ---------- 2. 有 RCA → 返回历史 ----------


def test_endpoint_returns_rca_history_when_present(client, tmp_factory_db):
    """工厂有 RCA 历史 → 端点返回完整历史条目,字段齐全。"""
    entries = [
        FactoryRcaEntry(
            cause="syntax_error",
            confidence=0.85,
            fix_suggestion="检查缩进",
            history_hint="历史提示",
            related_rules=["verify_mismatch"],
            task_index=2,
            timestamp="2026-07-13T10:00:00+00:00",
        ),
        FactoryRcaEntry(
            cause="timeout",
            confidence=0.7,
            fix_suggestion="拆小任务",
            history_hint="",
            related_rules=[],
            task_index=3,
            timestamp="2026-07-13T11:00:00+00:00",
        ),
    ]
    _make_factory_with_rca(tmp_factory_db, rca_entries=entries)

    r = client.get("/api/v1/factories/m100-factory-rca/rca_history")
    assert r.status_code == 200
    body = r.json()
    history = body["rca_history"]
    assert len(history) == 2

    # 第一条字段齐全
    first = history[0]
    assert first["cause"] == "syntax_error"
    assert first["confidence"] == pytest.approx(0.85)
    assert first["fix_suggestion"] == "检查缩进"
    assert first["history_hint"] == "历史提示"
    assert first["related_rules"] == ["verify_mismatch"]
    assert first["task_index"] == 2
    assert first["timestamp"] == "2026-07-13T10:00:00+00:00"


# ---------- 3. cause_stats 聚合 ----------


def test_endpoint_cause_stats_aggregation(client, tmp_factory_db):
    """cause_stats 按 cause 计数,多次同类失败累加。"""
    entries = [
        FactoryRcaEntry(cause="syntax_error", confidence=0.9, task_index=0),
        FactoryRcaEntry(cause="syntax_error", confidence=0.8, task_index=1),
        FactoryRcaEntry(cause="timeout", confidence=0.7, task_index=2),
    ]
    _make_factory_with_rca(tmp_factory_db, rca_entries=entries)

    r = client.get("/api/v1/factories/m100-factory-rca/rca_history")
    assert r.status_code == 200
    body = r.json()
    stats = body["cause_stats"]
    assert stats == {"syntax_error": 2, "timeout": 1}


# ---------- 4. factory 不存在 → 404 ----------


def test_endpoint_returns_404_when_factory_not_found(client):
    """查询不存在的 factory_id → 404。"""
    r = client.get("/api/v1/factories/nonexistent-factory/rca_history")
    assert r.status_code == 404


# ---------- 5. factory_loop 触发 verify 失败 → rca_history 追加 ----------


def test_factory_loop_appends_rca_history_on_verify_failure(tmp_db, tmp_cwd):
    """factory_loop 触发 verify 失败 → rca_history 自动追加 RCA 条目。

    使用 stub orchestrator 让任务连续失败 3 次(max_attempts=3),
    验证 state.rca_history 含 RCA 结果(每次失败追加一条)。
    """
    from driving.rca import reset_failure_counter

    reset_failure_counter()

    def stub_planner(state: FactoryState) -> list[FactoryTask]:
        return [FactoryTask(
            id="m100-fail-task",
            description="实现登录页面",
            verify_cmd=["false"],
            max_attempts=3,
        )]

    def stub_orchestrator(task: FactoryTask, state: FactoryState) -> TaskResult:
        return TaskResult(
            task=task,
            verified=False,
            stop_reason="verify_failed",
            iteration=1,
            summary="SyntaxError: invalid syntax",
        )

    result = run_factory_loop(
        product_goal="build login",
        cwd=tmp_cwd,
        db_path=str(tmp_db),
        planner=stub_planner,
        orchestrator_fn=stub_orchestrator,
        max_tasks=10,
    )

    # 3 次重试都失败 → 暂停
    assert result.status == FactoryStatus.paused
    # rca_history 应有 2 条(第 1/2 次失败会走 RCA 给下次重试建议;
    # 第 3 次 attempts>=max_attempts 时直接 break,不走 RCA)
    assert len(result.rca_history) == 2, \
        f"应有 2 条 RCA 历史,实际 {len(result.rca_history)}"

    # 第一条字段验证
    first = result.rca_history[0]
    assert isinstance(first, FactoryRcaEntry)
    assert first.cause == "syntax_error"
    assert 0.0 <= first.confidence <= 1.0
    assert first.fix_suggestion  # 应非空
    assert first.task_index == 0  # roadmap 中第 0 个任务

    # 持久化验证(同样 2 条)
    loaded = load_factory_state(result.factory_id, str(tmp_db))
    assert loaded is not None
    assert len(loaded.rca_history) == 2
    assert loaded.rca_history[0].cause == "syntax_error"


# ---------- 6. 持久化往返:rca_history 不丢失 ----------


def test_rca_history_persisted_across_save_load(tmp_db):
    """rca_history 写入 SQLite 后能完整读回。"""
    entries = [
        FactoryRcaEntry(cause="timeout", confidence=0.6, task_index=1),
        FactoryRcaEntry(cause="verify_mismatch", confidence=0.7, task_index=2),
    ]
    state = FactoryState(
        factory_id="m100-persist",
        product_goal="持久化测试",
        cwd="/tmp",
        status=FactoryStatus.paused,
        roadmap=[],
        rca_history=entries,
    )
    save_factory_state(state, str(tmp_db))

    loaded = load_factory_state("m100-persist", str(tmp_db))
    assert loaded is not None
    assert len(loaded.rca_history) == 2
    assert loaded.rca_history[0].cause == "timeout"
    assert loaded.rca_history[1].cause == "verify_mismatch"


# ---------- 7. 旧表(无 rca_history_json 列)向后兼容 ----------


def test_legacy_table_without_rca_history_column_returns_empty(tmp_db):
    """旧 SQLite 表(无 rca_history_json 列)读回时应返回空 rca_history。"""
    import sqlite3
    # 手动建一个旧 schema 的表(无 rca_history_json 列)
    with sqlite3.connect(str(tmp_db)) as conn:
        conn.execute("""
            CREATE TABLE factory_states (
                factory_id TEXT PRIMARY KEY,
                product_goal TEXT NOT NULL,
                cwd TEXT NOT NULL,
                status TEXT NOT NULL,
                roadmap_json TEXT NOT NULL,
                completed_json TEXT NOT NULL,
                failed_json TEXT NOT NULL,
                current_task_id TEXT,
                context_summary TEXT NOT NULL,
                iteration_count INTEGER NOT NULL,
                max_tasks INTEGER NOT NULL,
                design_style TEXT NOT NULL DEFAULT 'auto',
                design_context TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        conn.execute("""
            INSERT INTO factory_states VALUES (
                'legacy-factory', 'goal', '/tmp', 'paused',
                '[]', '[]', '[]', NULL, '', 0, 5,
                'auto', '', '2026-07-13', '2026-07-13'
            )
        """)

    # _ensure_table 应自动 ALTER 加列,读回时 rca_history 为空
    loaded = load_factory_state("legacy-factory", str(tmp_db))
    assert loaded is not None
    assert loaded.rca_history == []


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
