#!/usr/bin/env python3
"""M156.11 · factory_loop 最小冒烟测试（M156.10 import time 修复后验证编排层）。

诊断脚本 diag_openhands_worker.py 已证明 OpenHandsWorker 层正常（Kimi coder
35.4s 完成 hello.py）。本脚本验证上一层：factory_loop 编排层（planner 拆 roadmap
+ orchestrator 调 worker + verify 验收）是否真的能跑通。

策略：max_tasks=2 + 简单 goal + 关 auto_proposer，10min watchdog 内出结论：
  - 成功 → factory_loop 层正常，M147-A 完整 10-task E2E 可重跑
  - 失败/卡住 → 看 factory_loop 哪一层出问题（planner/orchestrator/verify）

用法：.venv/bin/python -u scripts/smoke_factory_loop.py
"""
from __future__ import annotations

import os
import shutil
import signal
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

WATCHDOG_SECONDS = int(os.environ.get("FLIPPED_SMOKE_WATCHDOG", "900"))


class _WatchdogTimeout(BaseException):
    """继承 BaseException 穿透 except Exception（对齐 e2e_m147 的 _WatchdogTimeout）。"""


def _load_dotenv(env_path: Path) -> None:
    if not env_path.exists():
        return
    for raw in env_path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        k = k.strip()
        v = v.strip().strip('"').strip("'")
        if k and k not in os.environ:
            os.environ[k] = v


def _on_alarm(signum, frame):
    raise _WatchdogTimeout(f"smoke watchdog {WATCHDOG_SECONDS}s 超时")


def main() -> int:
    # 1) 环境清理 + .env 加载
    for k in ("http_proxy", "HTTP_PROXY", "https_proxy", "HTTPS_PROXY", "ALL_PROXY", "all_proxy"):
        os.environ.pop(k, None)
    os.environ["NO_PROXY"] = "studio01-1,.ts.net,100.67.43.40,localhost,127.0.0.1,host.docker.internal"
    os.environ["no_proxy"] = os.environ["NO_PROXY"]
    _load_dotenv(ROOT / ".env")

    # M156 双模型：coder=Kimi（.env 已配，这里防御性确认）
    os.environ.setdefault("FLIPPED_CODER_MODEL", "mlx-community/Kimi-K2.7-Code-4bit")
    os.environ.setdefault("FLIPPED_ARCHITECT_MODEL", "mlx-community/GLM-5.2-fp8")
    # thinking 关（M149.6 决策，Kimi 也保持一致避免变量）
    os.environ["FLIPPED_WORKER_ENABLE_THINKING"] = "0"
    # M156.13: GLM planner 超时 180s（默认 1800s=30min 太长，smoke 10min watchdog 内跑不完）。
    # 实测简单 prompt 60s，复杂 default_planner prompt 可能 2-3min，180s 留足裕量。
    os.environ.setdefault("FLIPPED_GLM_TIMEOUT", "180")
    # 关 auto_proposer：roadmap 跑完就停，不要无限生成新任务
    os.environ["FLIPPED_AUTO_PROPOSER"] = "0"
    # 单任务超时 300s（smoke 任务简单，5min 足够）
    os.environ.setdefault("FLIPPED_TASK_TIMEOUT", "300")
    # worker 超时 300s（对齐诊断脚本）
    os.environ.setdefault("FLIPPED_WORKER_TIMEOUT", "300")
    os.environ.setdefault("FLIPPED_WORKER_MAX_ITERATIONS", "5")

    print(f"[SMOKE] === M156.11 factory_loop 冒烟测试 ===", flush=True)
    print(f"[SMOKE] FLIPPED_CODER_MODEL={os.environ.get('FLIPPED_CODER_MODEL')}", flush=True)
    print(f"[SMOKE] FLIPPED_ARCHITECT_MODEL={os.environ.get('FLIPPED_ARCHITECT_MODEL')}", flush=True)
    print(f"[SMOKE] watchdog={WATCHDOG_SECONDS}s  max_tasks=2  auto_proposer=off", flush=True)

    # 2) 前置探针：LiteLLM + agent-server
    print("\n[SMOKE] === 前置探针 ===", flush=True)
    import httpx
    _key = os.environ.get("LITELLM_MASTER_KEY") or os.environ.get("EXO_API_KEY")
    _headers = {"Authorization": f"Bearer {_key}"} if _key else {}
    try:
        r = httpx.get("http://localhost:4000/v1/models", headers=_headers, timeout=5.0)
        models = [m["id"] for m in r.json().get("data", [])]
        print(f"[SMOKE] LiteLLM :4000 OK, models={models}", flush=True)
        assert "architect" in models and "coder" in models
    except Exception as e:
        print(f"[SMOKE] ✗ LiteLLM 不可用: {e}", flush=True)
        return 1
    try:
        r = httpx.get("http://localhost:8000/alive", timeout=5.0)
        print(f"[SMOKE] agent-server :8000 OK, alive={r.json()}", flush=True)
    except Exception as e:
        print(f"[SMOKE] ✗ agent-server 不可用: {e}", flush=True)
        return 1

    # 3) 准备 workdir（必须在 ~/projects 下，容器挂载点）
    workdir = os.path.expanduser("~/projects/flipped_smoke_m156")
    shutil.rmtree(workdir, ignore_errors=True)
    os.makedirs(workdir, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=workdir, check=True)
    subprocess.run(
        ["git", "-c", "user.name=smoke", "-c", "user.email=smoke@local",
         "commit", "-q", "--allow-empty", "-m", "init"],
        cwd=workdir, check=True,
    )
    print(f"\n[SMOKE] workdir={workdir}", flush=True)

    # 4) 简单 goal：让 planner 拆 1-2 个 task
    goal = (
        "创建一个最小的 Python 项目，包含：\n"
        "1. hello.py：打印 'hello world'\n"
        "2. test_hello.py：pytest 测试验证 hello.py 的输出\n"
        "要求：代码简洁，有类型注解。"
    )
    print(f"[SMOKE] goal={goal[:80]}...", flush=True)

    db_path = "data/factory_smoke_m156.db"
    abs_db = str(ROOT / db_path)
    if os.path.exists(abs_db):
        os.remove(abs_db)

    # 5) 跑 factory_loop（watchdog 保护）
    from driving.factory_loop import run_factory_loop

    signal.signal(signal.SIGALRM, _on_alarm)
    signal.alarm(WATCHDOG_SECONDS)

    t0 = time.monotonic()
    timed_out = False
    state = None
    print(f"\n[SMOKE] [{time.monotonic()-t0:.1f}s] 调用 run_factory_loop(max_tasks=2) ...", flush=True)
    try:
        state = run_factory_loop(
            product_goal=goal,
            cwd=workdir,
            max_tasks=2,
            max_rounds=1,  # 只跑 1 轮，不自主生成
            db_path=db_path,
        )
    except _WatchdogTimeout as exc:
        timed_out = True
        print(f"\n[SMOKE] ⚠ WATCHDOG 超时: {exc}", flush=True)
    except Exception as exc:
        elapsed = time.monotonic() - t0
        print(f"\n[SMOKE] [{elapsed:.1f}s] ✗ run_factory_loop 抛异常: "
              f"{type(exc).__name__}: {exc}", flush=True)
        import traceback
        traceback.print_exc()
        signal.alarm(0)
        return 2
    finally:
        signal.alarm(0)

    wall = time.monotonic() - t0

    # 6) 结果分析
    print()
    print("=" * 60, flush=True)
    print(f"[SMOKE 结果] 墙钟: {wall:.1f}s ({wall/60:.1f}min)  超时: {'是' if timed_out else '否'}", flush=True)

    if state is None:
        print("[SMOKE] ✗ state 为 None（factory_loop 未返回有效状态）", flush=True)
        return 2

    roadmap = getattr(state, "roadmap", []) or []
    completed = getattr(state, "completed", []) or []
    failed = getattr(state, "failed", []) or []
    status = getattr(state, "status", "unknown")
    print(f"[SMOKE] factory status={status}", flush=True)
    print(f"[SMOKE] roadmap 任务数: {len(roadmap)}", flush=True)
    print(f"[SMOKE] completed: {len(completed)}  failed: {len(failed)}", flush=True)

    print("\n[SMOKE] === roadmap 详情 ===", flush=True)
    for i, t in enumerate(roadmap):
        print(f"  task[{i}] id={t.id} status={t.status} attempts={t.attempts}", flush=True)
        print(f"    desc: {t.description[:100]}", flush=True)

    print("\n[SMOKE] === workdir 产出 ===", flush=True)
    for p in sorted(Path(workdir).iterdir()):
        if p.name == ".git":
            continue
        size = p.stat().st_size
        print(f"  {p.name} ({size} bytes)", flush=True)
        if p.suffix == ".py" and size < 500:
            print(f"    内容: {p.read_text().strip()[:200]}", flush=True)

    # 7) 判定
    print("\n[SMOKE] === 判定 ===", flush=True)
    completed_n = len(completed)
    if timed_out:
        print(f"[SMOKE] ⚠ 超时（{wall:.0f}s），factory_loop 层仍有卡点", flush=True)
        print("[SMOKE] 建议：检查 planner 是否卡在 GLM 调用，或 orchestrator worker 调用", flush=True)
        return 3
    elif completed_n >= 1 and not failed:
        print(f"[SMOKE] ✓ PASS：{completed_n} 任务完成，0 失败，factory_loop 层正常", flush=True)
        print("[SMOKE] === 结论：M156.10 import time 修复后 factory_loop 编排层恢复，M147-A 完整 E2E 可重跑 ===", flush=True)
        return 0
    elif completed_n >= 1:
        print(f"[SMOKE] ⚠ 部分 PASS：{completed_n} 完成，{len(failed)} 失败", flush=True)
        for f in failed:
            print(f"  failed: {f.task.id} reason={f.stop_reason}", flush=True)
        return 0  # 有完成就算编排层通
    else:
        print(f"[SMOKE] ✗ FAIL：0 完成，{len(failed)} 失败", flush=True)
        for f in failed:
            print(f"  failed: {f.task.id} reason={f.stop_reason} summary={f.summary[:150]}", flush=True)
        return 2


if __name__ == "__main__":
    sys.exit(main())
