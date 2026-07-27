#!/usr/bin/env python3
"""M139-A · 真实 kill -9 崩溃恢复 E2E（无 LLM 依赖）。

流程：
1. 子进程 A 启动 factory loop（factory_id="e2e-crash-resume"），
   使用"文件标记型慢 orchestrator"：每个 task 写 {tmp}/{task.id}.marker 后 sleep(1s)，
   模拟真实耗时任务。
2. 父进程 polling 到至少 1 个 .marker 出现后，对子进程 A 发送 SIGKILL（kill -9）。
3. 父进程启动子进程 B（快速 orchestrator，无 sleep），用相同 factory_id resume；
   快速 orchestrator 检测已完成的 task 的 .marker 存在即跳过写入（幂等）。
4. 断言：
   - 每个 task 的 .marker 恰好 1 个
   - factory_events 中每个 task 的 task_start/task_done 幂等键各仅 1 条
   - 子进程 B 退出码 0，最终 state 为 done，completed 3 条且无重复
退出码：全部断言通过 0，否则 1。
"""
from __future__ import annotations

import os
import signal
import sqlite3
import subprocess
import sys
import tempfile
import time

FACTORY_ID = "e2e-crash-resume"
TASK_IDS = ("t1", "t2", "t3")
SRC_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))

# M164 · venv 自举：若 .venv 存在且当前不是 venv Python，自动重启自己。
# 否则用系统 Python 跑会因缺 langgraph 等依赖崩溃（子进程继承 sys.executable，必须先自举父进程）。
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_VENV_PY = os.path.join(ROOT, ".venv", "bin", "python3")
if os.path.exists(_VENV_PY) and os.path.realpath(sys.executable) != os.path.realpath(_VENV_PY):
    os.execv(_VENV_PY, [_VENV_PY] + sys.argv)

# 子进程内联代码：mode="slow"（写 marker + sleep）或 "fast"（marker 已存在则跳过）。
CHILD_CODE = '''
import os, sys, time
sys.path.insert(0, {src!r})
os.environ["FLIPPED_AUTO_PROPOSER"] = "0"  # 禁用 GLM 自主任务生成，保持确定性
from driving.factory_loop import FactoryTask, TaskResult, run_factory_loop

MODE = {mode!r}
TMP = {tmp!r}
DB = {db!r}
FID = {fid!r}
TASK_IDS = {task_ids!r}

def planner(state):
    return [FactoryTask(id=tid, description=f"task {{tid}}", verify_cmd=["true"])
            for tid in TASK_IDS]

def orchestrator(task, state):
    marker = os.path.join(TMP, task.id + ".marker")
    if MODE == "fast" and os.path.exists(marker):
        # 幂等：该 task 崩溃前已完成实际工作，跳过副作用写入
        return TaskResult(task=task, verified=True, stop_reason="completed",
                          iteration=1, summary="skip: marker exists")
    with open(marker, "w") as f:
        f.write(task.id)
    if MODE == "slow":
        time.sleep(1.0)  # 模拟真实耗时任务，给父进程留出 kill 窗口
    return TaskResult(task=task, verified=True, stop_reason="completed",
                      iteration=1, summary="ok")

state = run_factory_loop(
    product_goal="e2e crash resume",
    cwd=TMP,
    factory_id=FID,
    db_path=DB,
    planner=planner,
    orchestrator_fn=orchestrator,
    max_tasks=10,
)
print("FINAL_STATUS=" + state.status.value, flush=True)
print("COMPLETED=" + str(len(state.completed)), flush=True)
'''


def _start_child(mode: str, tmp: str, db: str) -> subprocess.Popen:
    code = CHILD_CODE.format(
        src=SRC_DIR, mode=mode, tmp=tmp, db=db, fid=FACTORY_ID, task_ids=list(TASK_IDS),
    )
    env = dict(os.environ)
    env["FLIPPED_DB"] = db  # 所有 default_db_path() 副作用（gold_memory/skill）隔离到 tmp
    return subprocess.Popen(
        [sys.executable, "-c", code],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env=env,
    )


def _wait_for_markers(tmp: str, count: int, timeout: float = 15.0) -> int:
    """polling 直到至少 count 个 .marker 出现，返回当前 marker 数。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        n = len([t for t in TASK_IDS if os.path.exists(os.path.join(tmp, f"{t}.marker"))])
        if n >= count:
            return n
        time.sleep(0.05)
    return len([t for t in TASK_IDS if os.path.exists(os.path.join(tmp, f"{t}.marker"))])


def _count_key(db: str, key: str) -> int:
    with sqlite3.connect(db) as conn:
        cur = conn.execute(
            "SELECT COUNT(*) FROM factory_events WHERE idempotency_key = ?", (key,)
        )
        return cur.fetchone()[0]


def main() -> int:
    failures: list[str] = []

    with tempfile.TemporaryDirectory() as tmp:
        db = os.path.join(tmp, "flipped.db")

        # ---- 阶段 1：慢速子进程 + kill -9 ----
        print(f"[e2e] phase1: start slow factory (fid={FACTORY_ID})", flush=True)
        child_a = _start_child("slow", tmp, db)
        seen = _wait_for_markers(tmp, count=1)
        print(f"[e2e] {seen} marker(s) observed, sending SIGKILL to pid={child_a.pid}", flush=True)
        if seen < 1:
            child_a.kill()
            failures.append("子进程 A 在超时内未产生任何 marker")
        os.kill(child_a.pid, signal.SIGKILL)
        rc_a = child_a.wait(timeout=10)
        out_a = child_a.stdout.read() if child_a.stdout else ""
        print(f"[e2e] child A exit={rc_a} (expect -{signal.SIGKILL})", flush=True)
        if rc_a != -signal.SIGKILL:
            failures.append(f"子进程 A 退出码 {rc_a}，预期 -{signal.SIGKILL}\n{out_a}")

        # ---- 阶段 2：快速子进程 resume ----
        print("[e2e] phase2: resume with fast factory", flush=True)
        child_b = _start_child("fast", tmp, db)
        try:
            rc_b = child_b.wait(timeout=60)
        except subprocess.TimeoutExpired:
            child_b.kill()
            rc_b = child_b.wait()
            failures.append("子进程 B 超时（60s）未完成")
        out_b = child_b.stdout.read() if child_b.stdout else ""
        print(out_b, end="", flush=True)
        print(f"[e2e] child B exit={rc_b}", flush=True)
        if rc_b != 0:
            failures.append(f"子进程 B 退出码 {rc_b}，预期 0\n{out_b}")
        if "FINAL_STATUS=done" not in out_b:
            failures.append(f"子进程 B 最终状态非 done\n{out_b}")
        if "COMPLETED=3" not in out_b:
            failures.append(f"子进程 B completed != 3\n{out_b}")

        # ---- 断言：marker 恰好各 1 个 ----
        for tid in TASK_IDS:
            marker = os.path.join(tmp, f"{tid}.marker")
            if not os.path.exists(marker):
                failures.append(f"{tid}.marker 不存在")
        marker_files = [f for f in os.listdir(tmp) if f.endswith(".marker")]
        print(f"[e2e] markers on disk: {sorted(marker_files)}", flush=True)
        if len(marker_files) != len(TASK_IDS):
            failures.append(f"marker 文件数 {len(marker_files)} != {len(TASK_IDS)}")

        # ---- 断言：事件日志幂等键无重复 ----
        for tid in TASK_IDS:
            for suffix in ("start", "done"):
                key = f"{FACTORY_ID}:{tid}:{suffix}"
                n = _count_key(db, key)
                print(f"[e2e] event {key}: count={n}", flush=True)
                if n != 1:
                    failures.append(f"幂等键 {key} 出现 {n} 次，预期 1 次")
        n_start = _count_key(db, f"{FACTORY_ID}:factory_start")
        print(f"[e2e] event {FACTORY_ID}:factory_start: count={n_start}", flush=True)
        if n_start != 1:
            failures.append(f"factory_start 幂等键出现 {n_start} 次，预期 1 次")

        # ---- 断言：DB 最终状态 ----
        sys.path.insert(0, SRC_DIR)
        from driving.factory_loop import FactoryStatus, load_factory_state

        state = load_factory_state(FACTORY_ID, db)
        if state is None:
            failures.append("DB 中无 factory 状态")
        else:
            print(f"[e2e] db state: status={state.status.value} "
                  f"completed={[r.task.id for r in state.completed]}", flush=True)
            if state.status != FactoryStatus.done:
                failures.append(f"DB 状态 {state.status.value} != done")
            if len(state.completed) != len(TASK_IDS):
                failures.append(f"DB completed {len(state.completed)} != {len(TASK_IDS)}")
            ids = sorted(r.task.id for r in state.completed)
            if ids != sorted(TASK_IDS):
                failures.append(f"completed task ids {ids} 与预期 {sorted(TASK_IDS)} 不符（疑似重复）")

    if failures:
        print("\n[e2e] FAIL:", flush=True)
        for f in failures:
            print(f"  - {f}", flush=True)
        return 1
    print("\n[e2e] PASS: crash-resume 无重复副作用，状态收敛 done", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
