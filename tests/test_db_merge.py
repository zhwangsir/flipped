"""M137 · 八库合一迁移脚本测试（scripts/migrate_db_merge.py）。

全部用 tmp_path 造临时旧库，不碰真实 data/。
旧库表结构直接复用各业务模块的真实建表函数（failure_kb / skill_registry /
factory_loop / event_log），checkpoints/writes 用 LangGraph SqliteSaver 的真实 schema。
"""
from __future__ import annotations

import importlib.util
import shutil
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))  # 双保险（跑测时 PYTHONPATH=src 已配）

_spec = importlib.util.spec_from_file_location(
    "migrate_db_merge", ROOT / "scripts" / "migrate_db_merge.py"
)
mdb = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = mdb  # @dataclass 解析注解时需从 sys.modules 找回本模块
_spec.loader.exec_module(mdb)

from driving import event_log, factory_loop, failure_kb, skill_registry  # noqa: E402

_TS = "2026-07-18T00:00:00+00:00"


# ---------- 临时旧库构造（用各模块真实建表函数） ----------

def _mk_failures_db(path: Path) -> None:
    conn = sqlite3.connect(str(path))
    failure_kb._ensure_table(conn)
    for i in range(2):
        conn.execute(
            """
            INSERT INTO failures
                (failure_id, task_description, cause, error_detail,
                 stop_reason, iterations, resolved, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (f"fail-{i}", f"task {i}", "syntax_error", f"boom {i}",
             "verify_failed", i + 1, 0, _TS),
        )
    conn.commit()
    conn.close()


def _mk_skills_db(path: Path) -> None:
    conn = sqlite3.connect(str(path))
    skill_registry._ensure_table(conn)
    for i in range(2):
        conn.execute(
            "INSERT INTO skills (skill_id, description, created_at) VALUES (?, ?, ?)",
            (f"sk-{i}", f"skill desc {i}", _TS),
        )
    conn.commit()
    conn.close()


def _mk_factory_db(path: Path) -> None:
    conn = sqlite3.connect(str(path))
    factory_loop._ensure_table(conn)  # factory_states + factory_events（真实建表函数）
    conn.execute(
        """
        INSERT INTO factory_states
            (factory_id, product_goal, cwd, status, roadmap_json, completed_json,
             failed_json, context_summary, iteration_count, max_tasks,
             created_at, updated_at)
        VALUES ('fac-1', 'build app', '/tmp/proj', 'running', '[]', '[]',
                '[]', '', 0, 10, ?, ?)
        """,
        (_TS, _TS),
    )
    assert event_log.append_event(
        conn, "fac-1", "task_done", {"task_id": "t1"}, idempotency_key="idem-1"
    ) is not None
    assert event_log.append_event(
        conn, "fac-1", "task_done", {"task_id": "t2"}, idempotency_key="idem-2"
    ) is not None
    conn.commit()
    conn.close()


def _mk_saver_db(path: Path, thread_id: str) -> None:
    """用 LangGraph SqliteSaver 建真实 checkpoints/writes schema 并写数据。"""
    from langgraph.checkpoint.sqlite import SqliteSaver

    with SqliteSaver.from_conn_string(str(path)) as saver:
        saver.setup()
        for i in range(2):
            saver.conn.execute(
                """
                INSERT INTO checkpoints
                    (thread_id, checkpoint_ns, checkpoint_id,
                     parent_checkpoint_id, type, checkpoint, metadata)
                VALUES (?, '', ?, NULL, 'msgpack', ?, ?)
                """,
                (thread_id, f"ckpt-{i}", b"blob-data", b"{}"),
            )
        saver.conn.execute(
            """
            INSERT INTO writes
                (thread_id, checkpoint_ns, checkpoint_id,
                 task_id, idx, channel, type, value)
            VALUES (?, '', 'ckpt-0', 'task-0', 0, 'ch', 'msgpack', ?)
            """,
            (thread_id, b"v"),
        )
        saver.conn.commit()


# ---------- 工具 ----------

def _count(db: Path, table: str) -> int:
    conn = sqlite3.connect(str(db))
    try:
        return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    finally:
        conn.close()


def _column_values(db: Path, table: str, column: str) -> set:
    conn = sqlite3.connect(str(db))
    try:
        return {r[0] for r in conn.execute(f"SELECT {column} FROM {table}")}
    finally:
        conn.close()


def _bak_files(data_dir: Path, name: str) -> list[Path]:
    return sorted(data_dir.glob(f"{name}.bak-*"))


def _run(data_dir: Path, target: Path, dry_run: bool = False) -> tuple[int, list[str]]:
    logs: list[str] = []
    rc = mdb.migrate(data_dir=data_dir, target=str(target), dry_run=dry_run, log=logs.append)
    return rc, logs


# ---------- 1. roundtrip ----------

def test_roundtrip(tmp_path: Path) -> None:
    _mk_factory_db(tmp_path / "factory.db")
    _mk_failures_db(tmp_path / "failures.db")
    _mk_skills_db(tmp_path / "skills.db")
    target = tmp_path / "flipped.db"

    rc, logs = _run(tmp_path, target)

    assert rc == 0, "\n".join(logs)
    # 行数
    assert _count(target, "failures") == 2
    assert _count(target, "skills") == 2
    assert _count(target, "factory_states") == 1
    assert _count(target, "factory_events") == 2
    # 关键字段内容
    assert _column_values(target, "failures", "failure_id") == {"fail-0", "fail-1"}
    assert _column_values(target, "failures", "cause") == {"syntax_error"}
    assert _column_values(target, "skills", "skill_id") == {"sk-0", "sk-1"}
    assert _column_values(target, "factory_states", "factory_id") == {"fac-1"}
    assert _column_values(target, "factory_states", "product_goal") == {"build app"}
    assert _column_values(target, "factory_events", "idempotency_key") == {"idem-1", "idem-2"}
    assert _column_values(target, "factory_events", "factory_id") == {"fac-1"}


# ---------- 2. 幂等：重复跑两次行数不翻倍 ----------

def test_idempotent_rerun(tmp_path: Path) -> None:
    _mk_factory_db(tmp_path / "factory.db")
    _mk_failures_db(tmp_path / "failures.db")
    target = tmp_path / "flipped.db"

    rc, _ = _run(tmp_path, target)
    assert rc == 0
    # 把 .bak 拷回原文件名，再跑一次（验证 INSERT OR IGNORE 真去重）
    for name in ("factory.db", "failures.db"):
        bak = _bak_files(tmp_path, name)
        assert len(bak) == 1
        shutil.copy(bak[0], tmp_path / name)
    rc, logs = _run(tmp_path, target)
    assert rc == 0, "\n".join(logs)

    assert _count(target, "failures") == 2
    assert _count(target, "factory_states") == 1
    assert _count(target, "factory_events") == 2


# ---------- 3. 三 saver 共库隔离：checkpoints/writes 合并互不覆盖 ----------

def test_saver_dbs_merge_isolated(tmp_path: Path) -> None:
    _mk_saver_db(tmp_path / "factory_checkpoints.db", thread_id="thread-a")
    _mk_saver_db(tmp_path / "delegate_checkpoints.db", thread_id="thread-b")
    target = tmp_path / "flipped.db"

    rc, logs = _run(tmp_path, target)

    assert rc == 0, "\n".join(logs)
    # 两库 checkpoint_id 相同（ckpt-0/1），靠 (thread_id, checkpoint_ns, checkpoint_id) 主键共存
    assert _count(target, "checkpoints") == 4
    assert _count(target, "writes") == 2
    assert _column_values(target, "checkpoints", "thread_id") == {"thread-a", "thread-b"}
    assert _column_values(target, "writes", "thread_id") == {"thread-a", "thread-b"}
    conn = sqlite3.connect(str(target))
    try:
        for tid in ("thread-a", "thread-b"):
            n = conn.execute(
                "SELECT COUNT(*) FROM checkpoints WHERE thread_id=?", (tid,)
            ).fetchone()[0]
            assert n == 2, f"{tid} 的 checkpoints 被覆盖或丢失: {n}"
    finally:
        conn.close()


# ---------- 4. dry-run：不产生目标库、不改名旧库 ----------

def test_dry_run_no_side_effects(tmp_path: Path) -> None:
    _mk_failures_db(tmp_path / "failures.db")
    target = tmp_path / "flipped.db"

    rc, logs = _run(tmp_path, target, dry_run=True)

    assert rc == 0
    assert not target.exists(), "dry-run 不应创建目标库"
    assert (tmp_path / "failures.db").exists(), "dry-run 不应改名旧库"
    assert _bak_files(tmp_path, "failures.db") == []
    assert any("failures" in line and "2" in line for line in logs), logs


# ---------- 5. 旧库改名：实跑后旧文件（含 -wal/-shm 边车）变 .bak-* ----------

def test_old_dbs_renamed_with_sidecars(tmp_path: Path) -> None:
    _mk_failures_db(tmp_path / "failures.db")
    # 模拟 WAL 边车文件
    (tmp_path / "failures.db-wal").write_bytes(b"")
    (tmp_path / "failures.db-shm").write_bytes(b"")
    target = tmp_path / "flipped.db"

    rc, logs = _run(tmp_path, target)

    assert rc == 0, "\n".join(logs)
    assert not (tmp_path / "failures.db").exists()
    assert not (tmp_path / "failures.db-wal").exists()
    assert not (tmp_path / "failures.db-shm").exists()
    assert len(_bak_files(tmp_path, "failures.db")) == 1
    assert len(_bak_files(tmp_path, "failures.db-wal")) == 1
    assert len(_bak_files(tmp_path, "failures.db-shm")) == 1
