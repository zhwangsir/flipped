#!/usr/bin/env python3
"""M137 · 八库合一数据迁移：把 8 个历史 SQLite 默认库的表合并进单一 flipped.db。

背景：M137 把 factory / factory_checkpoints / checkpoints / delegate_checkpoints /
failures / gold_memory / skills / infinite_loop 八个默认库收敛为 data/flipped.db
（env FLIPPED_DB 可覆盖，统一入口 src/driving/db.py）。本脚本负责把旧库数据搬过去。

流程（对 data-dir 下存在的每个旧库）：
  1. ATTACH 到目标库连接（目标库用 driving.db.connect() 打开，统一 WAL/pragma）；
  2. 从旧库 sqlite_master 取各映射表的建表 SQL，规范化为 CREATE TABLE IF NOT EXISTS
     后在目标库执行；
  3. INSERT OR IGNORE INTO main.<t> SELECT * FROM old.<t> —— 主键/唯一约束天然去重，
     幂等可重跑（checkpoints/writes 三旧库靠 LangGraph 主键
     (thread_id, checkpoint_ns, checkpoint_id) 合并去重）；
  4. 行数校验（目标 >= 旧），成功后把旧库文件改名为 <name>.db.bak-YYYYMMDD
     （连带 -wal/-shm 边车文件；已存在 .bak 则跳过）。

红线：绝不 DROP/DELETE 旧库数据；旧库只改名保留。

用法：
  python scripts/migrate_db_merge.py [--dry-run] [--data-dir DIR] [--target PATH]

  --dry-run   只打印将执行的库/表/行数计划，不写目标库、不改名旧库
  --data-dir  旧库所在目录（默认 data/）
  --target    目标库路径（默认 env FLIPPED_DB，其次 data/flipped.db）

退出码：0 = 全部成功（或没有旧库）；1 = 有库失败（失败详情见日志，其余库照常迁移）。
"""
from __future__ import annotations

import argparse
import re
import sqlite3
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

# sys.path 注入 src/（对齐 scripts/verify_m99_gold_memory_loop.py 的做法）
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from driving.db import connect, default_db_path  # noqa: E402

# 八库 → 需迁移的表（顺序即迁移顺序）
DB_TABLE_MAP: dict[str, list[str]] = {
    "factory.db": ["factory_states", "factory_events"],
    "factory_checkpoints.db": ["checkpoints", "writes"],
    "checkpoints.db": ["checkpoints", "writes"],
    "delegate_checkpoints.db": ["checkpoints", "writes"],
    "failures.db": ["failures"],
    "gold_memory.db": ["gold_memory"],
    "skills.db": ["skills"],
    "infinite_loop.db": ["infinite_loops"],
}

_CREATE_TABLE_RE = re.compile(r"^\s*CREATE\s+TABLE\s+(?!IF\s+NOT\s+EXISTS)", re.IGNORECASE)

LogFn = Callable[[str], None]


@dataclass
class TablePlan:
    table: str
    rows: int
    present: bool = True


@dataclass
class DbPlan:
    db_name: str
    db_path: Path
    tables: list[TablePlan] = field(default_factory=list)


def _quote(name: str) -> str:
    """标识符加双引号（表名均为 DB_TABLE_MAP 内的常量，这里只兜底）。"""
    return '"' + name.replace('"', '""') + '"'


def _normalize_create_sql(sql: str) -> str:
    """旧库 sqlite_master 里的建表 SQL 统一补 IF NOT EXISTS（多旧库共用目标表时可重复执行）。"""
    return _CREATE_TABLE_RE.sub("CREATE TABLE IF NOT EXISTS ", sql, count=1)


def _exec(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> None:
    """执行语句并显式关闭游标（未关闭的 SELECT 游标会持锁导致 COMMIT 报 table is locked）。"""
    cur = conn.execute(sql, params)
    cur.close()


def _one(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> tuple | None:
    """取一行并显式关闭游标。"""
    cur = conn.execute(sql, params)
    try:
        return cur.fetchone()
    finally:
        cur.close()


def _open_old_readonly(path: Path) -> sqlite3.Connection:
    """计划阶段只读打开旧库；WAL 库只读打开失败时退回普通连接（读 COUNT 不写数据）。"""
    try:
        return sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    except sqlite3.Error:
        return sqlite3.connect(str(path))


def collect_plan(data_dir: Path, log: LogFn = print) -> list[DbPlan]:
    """扫描 data-dir 下存在的旧库，统计各映射表的行数（不存在的库/表跳过）。"""
    plans: list[DbPlan] = []
    for db_name, tables in DB_TABLE_MAP.items():
        db_path = data_dir / db_name
        if not db_path.exists():
            log(f"[skip] {db_name} 不存在，跳过")
            continue
        plan = DbPlan(db_name=db_name, db_path=db_path)
        conn = _open_old_readonly(db_path)
        try:
            for table in tables:
                row = _one(
                    conn,
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                    (table,),
                )
                if row is None:
                    plan.tables.append(TablePlan(table=table, rows=0, present=False))
                else:
                    cnt = _one(conn, f"SELECT COUNT(*) FROM {_quote(table)}")
                    plan.tables.append(TablePlan(table=table, rows=int(cnt[0])))
        finally:
            conn.close()
        plans.append(plan)
    return plans


def _columns(conn: sqlite3.Connection, schema: str, table: str) -> list[str]:
    cur = conn.execute(f"PRAGMA {schema}.table_info({_quote(table)})")
    try:
        return [r[1] for r in cur]
    finally:
        cur.close()


def _migrate_one(conn: sqlite3.Connection, plan: DbPlan, log: LogFn) -> None:
    """迁移单个旧库：ATTACH → 建表 → INSERT OR IGNORE → 行数校验。失败抛异常由上层汇总。"""
    _exec(conn, "ATTACH DATABASE ? AS old", (str(plan.db_path),))
    try:
        for tp in plan.tables:
            if not tp.present:
                log(f"  [warn] {plan.db_name}: 表 {tp.table} 不存在，跳过")
                continue
            row = _one(
                conn,
                "SELECT sql FROM old.sqlite_master WHERE type='table' AND name=?",
                (tp.table,),
            )
            _exec(conn, _normalize_create_sql(row[0]))
            q = _quote(tp.table)
            old_cols = _columns(conn, "old", tp.table)
            main_cols = _columns(conn, "main", tp.table)
            if old_cols == main_cols:
                insert_sql = f"INSERT OR IGNORE INTO main.{q} SELECT * FROM old.{q}"
            else:
                # 目标表已存在且列不一致（如目标由更新 schema 先建）：按列名交集插入
                common = [c for c in main_cols if c in set(old_cols)]
                if not common:
                    raise RuntimeError(f"表 {tp.table} 新旧 schema 无公共列，无法合并")
                cols = ", ".join(_quote(c) for c in common)
                insert_sql = f"INSERT OR IGNORE INTO main.{q} ({cols}) SELECT {cols} FROM old.{q}"
                log(f"  [warn] {tp.table} 新旧 schema 列不一致，按公共列 {common} 合并")
            before = _one(conn, f"SELECT COUNT(*) FROM old.{q}")[0]
            _exec(conn, insert_sql)
            after = _one(conn, f"SELECT COUNT(*) FROM main.{q}")[0]
            log(f"  [ok] {tp.table}: 旧库 {before} 行 → 目标累计 {after} 行")
            if after < before:
                raise RuntimeError(f"行数校验失败: {tp.table} 目标 {after} < 旧库 {before}")
        conn.commit()
        # 改名前把旧库 WAL 落回主文件，避免数据滞留边车文件
        # （必须先 commit：连接持有未提交事务时 wal_checkpoint 会报 database table is locked）
        _one(conn, "PRAGMA old.wal_checkpoint(TRUNCATE)")
    except Exception:
        conn.rollback()
        raise
    finally:
        _exec(conn, "DETACH DATABASE old")


def _rename_old(plan: DbPlan, date_tag: str, log: LogFn) -> None:
    """旧库改名 <name>.db.bak-YYYYMMDD（连带 -wal/-shm；已存在 .bak 则跳过，不覆盖）。"""
    for suffix in ("", "-wal", "-shm"):
        src = plan.db_path.with_name(plan.db_path.name + suffix)
        if not src.exists():
            continue
        dst = src.with_name(src.name + ".bak-" + date_tag)
        if dst.exists():
            log(f"  [skip] {dst.name} 已存在，不改名 {src.name}")
            continue
        src.rename(dst)
        log(f"  [bak] {src.name} → {dst.name}")


def migrate(
    data_dir: str | Path = "data",
    target: str | None = None,
    dry_run: bool = False,
    log: LogFn = print,
) -> int:
    """执行八库合一迁移，返回退出码（0 全成/无库，1 有库失败）。"""
    data_dir = Path(data_dir)
    target = target or default_db_path()
    plans = collect_plan(data_dir, log)
    if not plans:
        log("[done] data-dir 下没有需要迁移的旧库")
        return 0

    total_rows = sum(t.rows for p in plans for t in p.tables if t.present)
    log(f"[plan] 目标库: {target} | 旧库 {len(plans)} 个 | 待迁移约 {total_rows} 行")
    for p in plans:
        parts = [
            f"{t.table}({t.rows} 行)" if t.present else f"{t.table}(缺表)"
            for t in p.tables
        ]
        log(f"  - {p.db_name}: " + ", ".join(parts))

    if dry_run:
        log("[dry-run] 不写入目标库、不改名旧库，计划打印完毕")
        return 0

    Path(target).parent.mkdir(parents=True, exist_ok=True)
    conn = connect(str(target))
    date_tag = datetime.now().strftime("%Y%m%d")
    failed: list[str] = []
    try:
        for plan in plans:
            if plan.db_path.resolve() == Path(target).resolve():
                log(f"[skip] {plan.db_name} 与目标库同路径，跳过")
                continue
            log(f"[migrate] {plan.db_name}")
            try:
                _migrate_one(conn, plan, log)
            except Exception as exc:  # noqa: BLE001 — 单库失败记录并继续其它库
                conn.rollback()
                failed.append(plan.db_name)
                log(f"  [error] {plan.db_name} 迁移失败: {exc}")
                continue
            _rename_old(plan, date_tag, log)
    finally:
        conn.close()

    if failed:
        log(f"[done] 完成但有 {len(failed)} 个库失败: {', '.join(failed)}")
        return 1
    log("[done] 全部旧库迁移成功")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="M137 八库合一迁移：8 个历史 SQLite 库合并进单一 flipped.db")
    parser.add_argument("--dry-run", action="store_true", help="只打印库/表/行数计划，不写目标库、不改名旧库")
    parser.add_argument("--data-dir", default="data", help="旧库所在目录（默认 data/）")
    parser.add_argument("--target", default=None, help="目标库路径（默认 env FLIPPED_DB 或 data/flipped.db）")
    args = parser.parse_args(argv)
    return migrate(data_dir=args.data_dir, target=args.target, dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
