#!/usr/bin/env python3
"""M98 flipped 并发编排压测脚本。

验证 M96 的并发安全加固在真实高并发多线程下的正确性:
  - rca.py 的 _failure_counter_lock 保护 _failure_counter dict
  - gold_memory.py 的 _gold_memory_write_lock + _enable_wal (SQLite WAL + busy_timeout=5000)

覆盖场景:
  1. 同 cause 并发计数: N 线程同时 _track_failure(SYNTAX_ERROR) -> counter == N
  2. 混合 cause 并发计数: N/2 track TIMEOUT + N/2 track SYNTAX_ERROR -> 无 crash, 状态一致
  3. Gold Memory 并发写完整性: N 线程并发写不同 task -> SELECT COUNT(*) == N, 无丢失
  4. 并发期间无 "database is locked" 异常: N/2 写 + N/2 读, 断言无 locked 错误
  5. 并发 reset 不破坏计数: 部分 reset + 部分 track -> 无 crash, 最终 counter 一致

不依赖 pytest, 可独立运行:
  cd /Users/wangzhenyu/Desktop/ALLProject/flipped && python scripts/verify_m98_concurrency.py --threads 20

约束:
  - 不改动 src/ 下任何代码
  - Gold Memory DB 用 tempfile.mkdtemp() 临时目录, 不污染真实 data/gold_memory.db
  - 中文注释

输出: JSON 报告打印到 stdout, 人类可读摘要打印到 stderr。退出码 0=全通过, 1=有失败。
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import tempfile
import threading
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# M164 · venv 自举：若 .venv 存在且当前不是 venv Python，自动重启自己。
# 否则用系统 Python 跑会因缺 langgraph 等依赖崩溃（scripts 设计为可 cron/直接跑，不能假设 venv 已激活）。
_VENV_PY = str(ROOT / ".venv" / "bin" / "python3")
if os.path.exists(_VENV_PY) and os.path.realpath(sys.executable) != os.path.realpath(_VENV_PY):
    os.execv(_VENV_PY, [_VENV_PY] + sys.argv)

# 注入 src/ 到 sys.path (对齐 tests/test_m96_concurrency.py 与 scripts/verify_m93_e2e.py 的做法)
sys.path.insert(0, str(ROOT / "src"))

from driving.rca import (  # noqa: E402
    RcaResult,
    RootCause,
    _track_failure,
    reset_failure_counter,
    get_failure_counter,
)
from driving.gold_memory import record_task_result  # noqa: E402
from driving.factory_loop import FactoryTask, FactoryState, TaskResult  # noqa: E402

# 压测聚焦于锁/WAL 的并发正确性。patch 掉 embedding, 避免 sentence-transformers
# 单例并发初始化的不确定性 (与 M96 锁逻辑无关), 让每个线程直奔 SQLite 写路径。
import driving.gold_memory as _gm_mod  # noqa: E402

_gm_mod._embed = lambda text: []  # type: ignore[assignment]


# ---------- 工具函数 ----------


def _make_rca_result(cause: RootCause) -> RcaResult:
    """构造一个最小合法的 RcaResult (每个线程独立实例, 避免共享对象)。"""
    return RcaResult(
        cause=cause,
        confidence=0.8,
        detail="m98 stress",
        fix_suggestion="fix it",
    )


def _make_factory_state(tmpdir: str) -> FactoryState:
    """构造一个最小合法的 FactoryState (design_style 默认 auto)。"""
    return FactoryState(
        factory_id="m98-stress",
        product_goal="M98 concurrency stress",
        cwd=tmpdir,
        roadmap=[],
    )


def _idx_to_word(i: int) -> str:
    """把序号转成唯一字母词: ka, kb, ..., kz, kaa, kab, ...

    用于让 _signature() 产出唯一签名 (gold_memory 的 _signature 用 [a-z_]+ 提取关键词,
    数字会被丢弃, 所以必须用纯字母词保证 N 个不同 task 得到 N 个不同签名 ->
    UNIQUE(task_signature, design_style, verify_cmd) 不会 UPSERT 合并)。
    """
    s = ""
    n = i + 1
    while n > 0:
        n, r = divmod(n - 1, 26)
        s = chr(ord("a") + r) + s
    return "k" + s


def _distinct_description(i: int) -> str:
    """生成第 i 个线程的 task description (保证唯一签名)。"""
    return f"concurrency stress task {_idx_to_word(i)}"


def _gold_row_count(db_path: str) -> int:
    """直接用 sqlite3 查 gold_memory 表行数。"""
    with sqlite3.connect(db_path) as conn:
        return int(conn.execute("SELECT COUNT(*) FROM gold_memory").fetchone()[0])


def _start_join(threads: list[threading.Thread]) -> None:
    """统一 start + join 一组线程。"""
    for t in threads:
        t.start()
    for t in threads:
        t.join()


# ---------- 场景 ----------


def scenario1_same_cause_count(n: int) -> dict:
    """场景1: 同 cause 并发计数。

    N 线程用 Barrier 同步后同时 _track_failure(SYNTAX_ERROR)。
    期望: get_failure_counter()[SYNTAX_ERROR] == N (锁保证无丢更新)。
    """
    reset_failure_counter()
    barrier = threading.Barrier(n)
    errors: list[str] = []

    def worker():
        try:
            barrier.wait()  # 所有线程到齐后同时释放, 最大化并发竞争
            _track_failure(_make_rca_result(RootCause.SYNTAX_ERROR))
        except Exception as e:  # noqa: BLE001
            errors.append(f"{type(e).__name__}: {e}")

    _start_join([threading.Thread(target=worker) for _ in range(n)])

    counter = get_failure_counter()
    actual = counter.get(RootCause.SYNTAX_ERROR, 0)
    passed = (not errors) and actual == n
    return {
        "name": "scenario1_same_cause_count",
        "passed": passed,
        "detail": {
            "cause": RootCause.SYNTAX_ERROR.value,
            "expected": n,
            "actual": actual,
            "errors": errors,
        },
    }


def scenario2_mixed_causes_count(n: int) -> dict:
    """场景2: 混合 cause 并发计数。

    N/2 线程 track TIMEOUT, N/2 线程 track SYNTAX_ERROR, Barrier 同步同时启动。

    注意 _track_failure 的实际语义是"连续同类失败计数器":
      - 新 cause (current==0) 会把整个 dict 清空为 {cause: 1}
      - 相同 cause 才 += 1
    因此并发混合 cause 时, dict 最终只保留 1 个 cause (最后"赢"的那个), count 在 [1, N]。
    不可能两个 cause 各自累加到 N/2 (那是简单计数器语义, 非 rca.py 的实现)。

    本场景验证锁在混合 cause 并发下的正确性: 无 crash + dict 状态一致 (恰好 1 个 key,
    count 在有效区间内), 证明锁没有让 dict 进入损坏/中间态。
    """
    reset_failure_counter()
    half_timeout = n // 2
    half_syntax = n - half_timeout  # 处理奇数: 总和 == n
    total = half_timeout + half_syntax
    barrier = threading.Barrier(total)
    errors: list[str] = []

    def track_timeout():
        try:
            barrier.wait()
            _track_failure(_make_rca_result(RootCause.TIMEOUT))
        except Exception as e:  # noqa: BLE001
            errors.append(f"{type(e).__name__}: {e}")

    def track_syntax():
        try:
            barrier.wait()
            _track_failure(_make_rca_result(RootCause.SYNTAX_ERROR))
        except Exception as e:  # noqa: BLE001
            errors.append(f"{type(e).__name__}: {e}")

    threads = [threading.Thread(target=track_timeout) for _ in range(half_timeout)]
    threads += [threading.Thread(target=track_syntax) for _ in range(half_syntax)]
    _start_join(threads)

    counter = get_failure_counter()
    keys = list(counter.keys())
    # 实现保证 dict 恒为 0 或 1 个 key (新 cause 会清空整个 dict)
    consistent = len(keys) == 1
    count_val = list(counter.values())[0] if keys else 0
    in_range = 1 <= count_val <= total
    passed = (not errors) and consistent and in_range
    return {
        "name": "scenario2_mixed_causes_count",
        "passed": passed,
        "detail": {
            "timeout_threads": half_timeout,
            "syntax_threads": half_syntax,
            "final_keys": [k.value for k in keys],
            "final_count": count_val,
            "consistent_state": consistent,
            "count_in_range": in_range,
            "note": "rca._track_failure 是连续同类计数器, 新 cause 会清空旧计数; "
                    "混合并发最终只保留 1 个 cause, count 为该 cause 连续命中数",
            "errors": errors,
        },
    }


def scenario3_gold_memory_write_integrity(n: int, db_path: str, state: FactoryState) -> dict:
    """场景3: Gold Memory 并发写完整性。

    N 线程并发 record_task_result 写不同 task (唯一签名), 验证 SELECT COUNT(*) == N,
    无丢失。写锁 + WAL 保证不丢数据。
    """
    barrier = threading.Barrier(n)
    errors: list[str] = []

    def writer(i: int):
        try:
            barrier.wait()
            task = FactoryTask(description=_distinct_description(i), verify_cmd=["true"])
            result = TaskResult(
                task=task,
                verified=True,
                stop_reason="verified",
                iteration=1,
                summary=f"success {i}",
            )
            record_task_result(task, state, result, db_path=db_path)
        except Exception as e:  # noqa: BLE001
            errors.append(f"thread-{i} {type(e).__name__}: {e}")

    threads = [threading.Thread(target=writer, args=(i,)) for i in range(n)]
    _start_join(threads)

    actual = _gold_row_count(db_path)
    passed = (not errors) and actual == n
    return {
        "name": "scenario3_gold_memory_write_integrity",
        "passed": passed,
        "detail": {
            "expected_rows": n,
            "actual_rows": actual,
            "errors": errors,
        },
    }


def scenario4_no_database_locked(n: int, db_path: str, state: FactoryState) -> dict:
    """场景4: 并发期间无 "database is locked" 异常。

    N/2 写线程 (每个写 1 个不同 task) + N/2 读线程 (每个 query_similar_failures 几次)
    并发运行, 捕获所有线程异常, 断言无 sqlite3.OperationalError "database is locked"。

    WAL + busy_timeout=5000 + _gold_memory_write_lock 应让写串行、读并发, 不出现 locked。
    """
    # 延迟导入 reader 函数 (与 gold_memory 同模块, 已 patch _embed)
    from driving.gold_memory import query_similar_failures

    half = n // 2
    readers = n - half
    total = half + readers
    barrier = threading.Barrier(total)
    errors: list[str] = []
    # 读线程的描述使用独立的 offset, 避免与 scenario3 的签名冲突 (本场景用独立 DB)
    write_offset = 1000

    def writer(i: int):
        try:
            barrier.wait()
            task = FactoryTask(
                description=_distinct_description(write_offset + i),
                verify_cmd=["true"],
            )
            result = TaskResult(
                task=task,
                verified=False,
                stop_reason="verify_failed",
                iteration=1,
                summary=f"fail {i}",
            )
            record_task_result(task, state, result, db_path=db_path)
        except Exception as e:  # noqa: BLE001
            errors.append(f"writer-{i} {type(e).__name__}: {e}")

    def reader(i: int):
        try:
            barrier.wait()
            for _ in range(3):
                query_similar_failures("concurrency stress task", db_path=db_path)
        except Exception as e:  # noqa: BLE001
            errors.append(f"reader-{i} {type(e).__name__}: {e}")

    threads = [threading.Thread(target=writer, args=(i,)) for i in range(half)]
    threads += [threading.Thread(target=reader, args=(i,)) for i in range(readers)]
    _start_join(threads)

    lock_errors = [e for e in errors if "locked" in e.lower()]
    passed = len(lock_errors) == 0
    return {
        "name": "scenario4_no_database_locked",
        "passed": passed,
        "detail": {
            "writers": half,
            "readers": readers,
            "total_exceptions": len(errors),
            "lock_errors": lock_errors,
            "all_errors": errors[:20],  # 截断防过长
        },
    }


def scenario5_reset_during_track(n: int) -> dict:
    """场景5: 并发 reset 不破坏计数。

    N/2 线程反复 reset_failure_counter(), N/2 线程反复 _track_failure(SYNTAX_ERROR),
    Barrier 同步启动。验证: 无 crash, 最终 get_failure_counter() 返回合法 dict。
    """
    reset_failure_counter()
    half_reset = n // 2
    half_track = n - half_reset
    total = half_reset + half_track
    barrier = threading.Barrier(total)
    errors: list[str] = []
    iters = 20  # 每个线程多做几轮, 放大 reset/track 交错概率

    def resetter(i: int):
        try:
            barrier.wait()
            for _ in range(iters):
                reset_failure_counter()
        except Exception as e:  # noqa: BLE001
            errors.append(f"resetter-{i} {type(e).__name__}: {e}")

    def tracker(i: int):
        try:
            barrier.wait()
            for _ in range(iters):
                _track_failure(_make_rca_result(RootCause.SYNTAX_ERROR))
        except Exception as e:  # noqa: BLE001
            errors.append(f"tracker-{i} {type(e).__name__}: {e}")

    threads = [threading.Thread(target=resetter, args=(i,)) for i in range(half_reset)]
    threads += [threading.Thread(target=tracker, args=(i,)) for i in range(half_track)]
    _start_join(threads)

    # 最终状态应是合法 dict (0 或 1 个 key, value >= 0)
    counter = get_failure_counter()
    valid = isinstance(counter, dict) and all(
        isinstance(k, RootCause) and isinstance(v, int) and v >= 0 for k, v in counter.items()
    )
    passed = (not errors) and valid
    return {
        "name": "scenario5_reset_during_track",
        "passed": passed,
        "detail": {
            "reset_threads": half_reset,
            "track_threads": half_track,
            "iters_per_thread": iters,
            "final_counter": {k.value: v for k, v in counter.items()},
            "valid_state": valid,
            "errors": errors,
        },
    }


# ---------- 主流程 ----------


def run_all(n: int) -> dict:
    """运行全部场景, 返回汇总报告 dict。"""
    tmpdir = tempfile.mkdtemp(prefix="m98_stress_")
    db_write = os.path.join(tmpdir, "gold_write.db")
    db_rw = os.path.join(tmpdir, "gold_rw.db")
    state = _make_factory_state(tmpdir)

    scenarios = [
        lambda: scenario1_same_cause_count(n),
        lambda: scenario2_mixed_causes_count(n),
        lambda: scenario3_gold_memory_write_integrity(n, db_write, state),
        lambda: scenario4_no_database_locked(n, db_rw, state),
        lambda: scenario5_reset_during_track(n),
    ]

    results = []
    t0 = time.perf_counter()
    for fn in scenarios:
        ts = time.perf_counter()
        try:
            r = fn()
        except Exception as e:  # noqa: BLE001 场景自身不应抛出, 兜底
            r = {
                "name": getattr(fn, "__name__", "unknown"),
                "passed": False,
                "detail": {"unexpected": f"{type(e).__name__}: {e}",
                           "traceback": traceback.format_exc(limit=5)},
            }
        r["elapsed_s"] = round(time.perf_counter() - ts, 4)
        results.append(r)
    total_elapsed = round(time.perf_counter() - t0, 4)

    passed_count = sum(1 for r in results if r["passed"])
    failed_count = len(results) - passed_count
    total_exceptions = sum(
        len(r.get("detail", {}).get("errors", []))
        + len(r.get("detail", {}).get("lock_errors", []))
        + (1 if r.get("detail", {}).get("unexpected") else 0)
        for r in results
    )

    report = {
        "milestone": "M98",
        "total_threads": n,
        "total_elapsed_s": total_elapsed,
        "passed": failed_count == 0,
        "summary": {
            "scenario_count": len(results),
            "passed_count": passed_count,
            "failed_count": failed_count,
            "total_exceptions": total_exceptions,
        },
        "scenarios": results,
        "tmpdir": tmpdir,
    }
    return report


def _print_console_summary(report: dict) -> None:
    """人类可读摘要打印到 stderr (stdout 留给 JSON)。"""
    s = report["summary"]
    print("=" * 64, file=sys.stderr)
    print(f"M98 并发压测报告  (threads={report['total_threads']}, "
          f"elapsed={report['total_elapsed_s']}s)", file=sys.stderr)
    print("=" * 64, file=sys.stderr)
    for r in report["scenarios"]:
        flag = "PASS" if r["passed"] else "FAIL"
        d = r.get("detail", {})
        extra = ""
        if r["name"] == "scenario1_same_cause_count":
            extra = f"expected={d.get('expected')} actual={d.get('actual')}"
        elif r["name"] == "scenario2_mixed_causes_count":
            extra = f"keys={d.get('final_keys')} count={d.get('final_count')}"
        elif r["name"] == "scenario3_gold_memory_write_integrity":
            extra = f"expected_rows={d.get('expected_rows')} actual_rows={d.get('actual_rows')}"
        elif r["name"] == "scenario4_no_database_locked":
            extra = (f"writers={d.get('writers')} readers={d.get('readers')} "
                     f"lock_errors={len(d.get('lock_errors', []))} "
                     f"total_exc={d.get('total_exceptions')}")
        elif r["name"] == "scenario5_reset_during_track":
            extra = f"final_counter={d.get('final_counter')} valid={d.get('valid_state')}"
        print(f"  [{flag}] {r['name']}  ({r.get('elapsed_s')}s)  {extra}", file=sys.stderr)
        if not r["passed"]:
            errs = d.get("errors", []) or []
            if errs:
                for e in errs[:5]:
                    print(f"          ! {e}", file=sys.stderr)
            if d.get("unexpected"):
                print(f"          ! {d['unexpected']}", file=sys.stderr)
    print("-" * 64, file=sys.stderr)
    print(f"通过 {s['passed_count']}/{s['scenario_count']}, "
          f"失败 {s['failed_count']}, 总异常 {s['total_exceptions']}", file=sys.stderr)
    print(f"结果: {'ALL PASS' if report['passed'] else 'HAS FAILURES'}", file=sys.stderr)
    print("=" * 64, file=sys.stderr)


def main() -> int:
    parser = argparse.ArgumentParser(description="M98 flipped 并发编排压测脚本")
    parser.add_argument("--threads", type=int, default=20, help="并发线程数 (默认 20)")
    args = parser.parse_args()
    n = args.threads
    if n < 2:
        print("ERROR: --threads 至少为 2", file=sys.stderr)
        return 1

    report = run_all(n)
    _print_console_summary(report)
    # JSON 报告打印到 stdout (机器可解析)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
