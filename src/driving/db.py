"""M137 · 统一 SQLite 存储入口。

八个历史默认库（factory / factory_checkpoints / checkpoints / delegate_checkpoints /
failures / gold_memory / skills / infinite_loop）收敛为单一 ``data/flipped.db``。

- ``default_db_path()``：env ``FLIPPED_DB`` 可覆盖，默认 ``data/flipped.db``。
- ``connect(path=None)``：统一 pragma 治理（WAL + busy_timeout + synchronous=NORMAL +
  temp_store=MEMORY + mmap_size=256MB），全部 fail-open（pragma 失败不影响连接可用）。

各模块公开函数保留 ``db_path`` 参数（默认 None → 落统一库），测试注入 tmp 路径行为不变。
LangGraph SqliteSaver 不走本模块（它自管连接），仅共享同一文件路径与 thread_id 命名空间约定。
"""
from __future__ import annotations

import os
import sqlite3

DEFAULT_DB = "data/flipped.db"


def default_db_path() -> str:
    """统一库路径：env FLIPPED_DB 优先，默认 data/flipped.db。"""
    return os.environ.get("FLIPPED_DB", DEFAULT_DB)


def connect(db_path: str | None = None, **kw) -> sqlite3.Connection:
    """打开 SQLite 连接并施加统一 pragma（fail-open）。

    db_path=None → default_db_path()。":memory:" 跳过 WAL（无文件）。
    kw 透传 sqlite3.connect。
    """
    path = db_path or default_db_path()
    conn = sqlite3.connect(path, **kw)
    try:
        if path != ":memory:":
            conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA temp_store=MEMORY")
        conn.execute("PRAGMA mmap_size=268435456")  # 256MB
    except sqlite3.Error:
        pass  # pragma 失败不阻塞连接使用
    return conn
