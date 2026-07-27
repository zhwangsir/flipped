"""M144-C 真实产线基准 · FLIPPED_MAX_PARALLEL=3 工厂并行 e2e。

用真实 GLM-5.2 planner + Kimi-K2.7 orchestrator + OpenHands 沙箱，
跑一个 3 个完全独立任务的工厂并行循环，验证：
1. 真实 LLM 并发下 ≥3 任务 completed
2. task_done 幂等键无重复
3. 事件时间戳显示真实并发（≥2 个 task_start 接近同时）
4. 无 infra_failure（或有但工厂最终 done）

前置：OpenHands agent-server 运行中（:8000/alive）、exo 模型集群可达。
"""
import os
import shutil
import signal
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# M164 · venv 自举：若 .venv 存在且当前不是 venv Python，自动重启自己。
# 否则用系统 Python 跑会因缺 langgraph 等依赖崩溃（scripts 设计为可 cron/直接跑，不能假设 venv 已激活）。
_VENV_PY = str(ROOT / ".venv" / "bin" / "python3")
if os.path.exists(_VENV_PY) and os.path.realpath(sys.executable) != os.path.realpath(_VENV_PY):
    os.execv(_VENV_PY, [_VENV_PY] + sys.argv)

sys.path.insert(0, str(ROOT / "src"))

WATCHDOG_SECONDS = 20 * 60  # 整体超时 20 分钟


class _WatchdogTimeout(Exception):
    pass


def _on_alarm(signum, frame):
    raise _WatchdogTimeout(f"watchdog 超时（{WATCHDOG_SECONDS}s）")


def _db_events(db_path: str, factory_id: str) -> list[dict]:
    """直接读 factory_events 表（不依赖内部 API，只做只读查询）。"""
    rows = []
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.execute(
            "SELECT seq, ts, kind, idempotency_key FROM factory_events "
            "WHERE factory_id = ? ORDER BY seq ASC",
            (factory_id,),
        )
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
    except Exception as exc:  # noqa: BLE001
        print(f"[DB] 读 factory_events 失败: {exc}")
    return rows


def main():
    # 绕过 http_proxy 拦截内网模型端点（必须 unset，langchain httpx 会走系统代理）
    for k in ("http_proxy", "HTTP_PROXY", "https_proxy", "HTTPS_PROXY", "ALL_PROXY", "all_proxy"):
        os.environ.pop(k, None)
    os.environ["NO_PROXY"] = "100.64.201.37,localhost,127.0.0.1,host.docker.internal"
    os.environ["no_proxy"] = "100.64.201.37,localhost,127.0.0.1,host.docker.internal"

    # M144-C 核心：任务级并行度 = 3（对照实验可用 FLIPPED_E2E_MP / FLIPPED_E2E_TAG 覆盖）
    mp = os.environ.get("FLIPPED_E2E_MP", "3")
    tag = os.environ.get("FLIPPED_E2E_TAG", "")
    os.environ["FLIPPED_MAX_PARALLEL"] = mp

    from driving.factory_loop import run_factory_loop

    # 干净工作区（OpenHands 容器需能访问，/var/folders 在 macOS 上无权限）
    workdir = f"/tmp/flipped_m144_e2e{tag}"
    shutil.rmtree(workdir, ignore_errors=True)
    os.makedirs(workdir, exist_ok=True)

    # 干净 DB（相对项目根，与 e2e_10_tasks 一致）
    db_path = f"data/factory_m144_e2e{tag}.db"
    abs_db = str(ROOT / db_path)
    if os.path.exists(abs_db):
        os.remove(abs_db)
        print(f"[E2E] 已删除旧库: {abs_db}")

    goal = (
        "在项目中创建三个完全相互独立的 Python 模块："
        "a.py（提供 add(a, b) 返回两数之和）、"
        "b.py（提供 sub(a, b) 返回两数之差）、"
        "c.py（提供 mul(a, b) 返回两数之积），"
        "各配独立 pytest 测试文件 tests/test_a.py、tests/test_b.py、tests/test_c.py。"
        "三者互不 import、可完全并行开发。"
        "分 3 个任务实现，每个任务一个模块+其测试。"
    )
    print(f"[E2E] 工作目录: {workdir}")
    print(f"[E2E] 产品目标: {goal}")
    print(f"[E2E] max_tasks=4  FLIPPED_MAX_PARALLEL={mp}")
    print(f"[E2E] watchdog={WATCHDOG_SECONDS}s")
    print()

    signal.signal(signal.SIGALRM, _on_alarm)
    signal.alarm(WATCHDOG_SECONDS)

    t0 = time.monotonic()
    timed_out = False
    state = None
    try:
        state = run_factory_loop(
            product_goal=goal,
            cwd=workdir,
            max_tasks=4,  # 防 planner 拆出第 4 个任务时预算耗尽仍可控
            db_path=db_path,
        )
    except _WatchdogTimeout as exc:
        timed_out = True
        print(f"\n[E2E] WATCHDOG 超时: {exc} —— 部分完成，按现有 DB 证据判定")
    finally:
        signal.alarm(0)
    wall = time.monotonic() - t0

    print()
    print("=" * 60)
    print(f"[E2E 结果] 墙钟: {wall:.1f}s ({wall / 60:.1f}min)  超时: {'是' if timed_out else '否'}")

    completed_n = 0
    failed_n = 0
    final_status = "unknown(timeout)" if timed_out else "unknown"
    roadmap = []
    factory_id = None
    if state is not None:
        factory_id = state.factory_id
        final_status = state.status.value
        completed_n = len(state.completed)
        failed_n = len(state.failed)
        roadmap = state.roadmap
        print(f"  工厂 ID: {factory_id}")
        print(f"  最终状态: {final_status}")
        print(f"  迭代次数: {state.iteration_count}")
        print(f"  roadmap 任务数: {len(roadmap)}")
        print(f"  完成: {completed_n}  失败: {failed_n}")
        print()
        print("[Roadmap]")
        for t in roadmap:
            print(f"  {t.id} [{t.status.value}] attempts={t.attempts}")
            print(f"    desc: {t.description[:80]}")
            print(f"    verify: {t.verify_cmd}")
            if t.feedback:
                print(f"    feedback: {t.feedback[:120]}")
        if state.completed:
            print()
            print("[完成的任务]")
            for r in state.completed:
                print(f"  {r.task.id}: verified={r.verified} iter={r.iteration} reason={r.stop_reason}")
        if state.failed:
            print()
            print("[失败的任务]")
            for r in state.failed:
                print(f"  {r.task.id}: verified={r.verified} reason={r.stop_reason}")
                print(f"    summary: {r.summary[:200]}")

    # ---- DB 事件证据：计数 + 幂等键重复检查 + 并发时间戳 ----
    if factory_id is None:
        # 超时时 state 未返回，从库中取最近 factory_id
        try:
            conn = sqlite3.connect(abs_db)
            row = conn.execute(
                "SELECT factory_id FROM factory_events ORDER BY seq DESC LIMIT 1"
            ).fetchone()
            conn.close()
            factory_id = row[0] if row else None
        except Exception:  # noqa: BLE001
            factory_id = None
        print(f"[DB] 超时后回查 factory_id: {factory_id}")

    events = _db_events(abs_db, factory_id) if factory_id else []
    starts = [e for e in events if e["kind"] == "task_start"]
    dones = [e for e in events if e["kind"] == "task_done"]
    infra = [e for e in events if "infra" in e["kind"].lower()]

    print()
    print("[事件日志]")
    print(f"  总事件数: {len(events)}")
    print(f"  task_start: {len(starts)}  task_done: {len(dones)}  infra 相关: {len(infra)}")

    keys = [e["idempotency_key"] for e in events if e["idempotency_key"]]
    dup_keys = sorted({k for k in keys if keys.count(k) > 1})
    print(f"  幂等键总数: {len(keys)}  重复键: {len(dup_keys)}")
    for k in dup_keys:
        print(f"    [违规] 重复幂等键: {k}")

    # 并发证据：task_start 时间戳两两最小间隔 << 单任务耗时
    print()
    print("[task_start 时间戳]")
    start_ts = []
    for e in starts:
        ts = e["ts"]
        start_ts.append(datetime.fromisoformat(ts).timestamp())
        print(f"  seq={e['seq']} ts={ts} key={e['idempotency_key']}")
    concurrency_evidence = False
    min_gap = None
    if len(start_ts) >= 2:
        gaps = [abs(b - a) for a, b in zip(start_ts, start_ts[1:])]
        min_gap = min(gaps)
        # 并行波次内 task_start 由主线程串行落账，正常应在秒级内连续发出
        concurrency_evidence = min_gap < 60
        print(f"  相邻 task_start 最小间隔: {min_gap:.1f}s → 并发证据: {'是' if concurrency_evidence else '否'}")

    if dones:
        print("[task_done 时间戳]")
        for e in dones:
            print(f"  seq={e['seq']} ts={e['ts']} key={e['idempotency_key']}")

    # ---- 判定 ----
    ok_completed = completed_n >= 3 or (timed_out and len(dones) >= 3)
    ok_idem = not dup_keys
    ok_concurrency = concurrency_evidence
    ok_infra = (not infra) or (final_status == "done")
    passed = ok_completed and ok_idem and ok_concurrency and ok_infra and not timed_out

    print()
    print("[判定依据]")
    print(f"  completed >= 3: {'✅' if ok_completed else '❌'} ({completed_n})")
    print(f"  幂等键无重复:   {'✅' if ok_idem else '❌'}")
    print(f"  真实并发证据:   {'✅' if ok_concurrency else '❌'}")
    print(f"  无 infra 失败:  {'✅' if ok_infra else '❌'} (infra 事件 {len(infra)} 条, status={final_status})")
    print(f"  未超时:         {'✅' if not timed_out else '❌'}")
    print()
    if passed:
        print(f"[判定] PASS ✅  墙钟 {wall:.1f}s，{completed_n} 任务完成，并行幂等语义在真实 LLM 下成立")
        return 0
    print(f"[判定] FAIL ❌  墙钟 {wall:.1f}s，status={final_status} completed={completed_n} failed={failed_n}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
