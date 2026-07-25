"""M147-A · 真实工厂 10-task E2E（M149 单模型重跑版）。

用真实 GLM-5.2-fp8 planner + orchestrator（M149 单模型模式，原 Kimi-K2.7 已切 GLM）
+ OpenHands 沙箱，跑一个 10 任务的完整产线，验证：
1. 真实 LLM 下 ≥8 任务 completed（允许少量失败重试后通过）
2. task_done 幂等键无重复
3. 事件时间戳显示真实并发
4. 无持续性 infra_failure（工厂最终 done）
5. 自动迭代能力：planner 拆 roadmap + worker 执行 + auto-fix + verify

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
sys.path.insert(0, str(ROOT / "src"))

# M149.7：默认 12h（GLM-fp8 单任务实测 1-1.5h×10 任务 MP=1 串行），env 可覆盖
WATCHDOG_SECONDS = int(os.environ.get("FLIPPED_E2E_WATCHDOG", str(12 * 3600)))

# M149.5 前置探针：M147-A v6 曾空跑 40 分钟才发现 exo 数据面 wedge。
# 正式跑工厂前先发一个 ~15k tokens 代表性 prompt（OpenHands 系统提示规模）
# 经 LiteLLM proxy 测首 token，超时即判数据面不可用、直接退出，拒绝空跑。
PREFLIGHT_TIMEOUT_S = int(os.environ.get("FLIPPED_E2E_PREFLIGHT_TIMEOUT", "300"))


class _WatchdogTimeout(BaseException):
    """M149.7：必须继承 BaseException——v8 实测继承 Exception 时，SIGALRM 在
    主线程 t.join(task_timeout) 上抛出的本异常被 _execute_task 的
    `except Exception`（factory_loop.py:1356，"任何异常都转为失败 TaskResult"
    契约）吞掉 → 任务标 failed → 工厂无限重试，watchdog 形同虚设。
    BaseException 穿透所有 except Exception，直达本脚本 main 的捕获点。"""


class _PreflightFailed(Exception):
    pass


def _preflight_data_plane() -> None:
    """经 LiteLLM proxy 发 ~15k tokens prompt，要求 PREFLIGHT_TIMEOUT_S 内出首 token。"""
    import json
    import urllib.request

    base = os.environ.get("FLIPPED_LITELLM_BASE", "http://localhost:4000")
    key = os.environ.get("LITELLM_MASTER_KEY", "")
    filler = (
        "You are an autonomous software engineer agent. You must use tools to "
        "complete tasks. Follow safety rules. Always verify your work. "
    ) * 500  # ~15k tokens
    payload = {
        "model": "coder",
        "messages": [
            {"role": "system", "content": filler},
            {"role": "user", "content": "Reply with exactly: OK"},
        ],
        "temperature": 0,
        "max_tokens": 4,
        "stream": True,
    }
    req = urllib.request.Request(
        f"{base}/v1/chat/completions",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
        method="POST",
    )
    print(f"[前置探针] ~15k tokens 经 {base} 测数据面（限 {PREFLIGHT_TIMEOUT_S}s 首 token）...")
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=PREFLIGHT_TIMEOUT_S) as resp:
            for raw in resp:
                if raw.strip() and raw.strip() != b"data: [DONE]":
                    first = time.monotonic() - t0
                    print(f"[前置探针] 首 token {first:.1f}s ✅ 数据面健康")
                    return
    except Exception as exc:  # noqa: BLE001
        raise _PreflightFailed(
            f"数据面探针失败：{PREFLIGHT_TIMEOUT_S}s 内无首 token（{exc}）。"
            "exo 实例可能 wedge——请先 DELETE 卡死实例并 place_instance 重载，"
            "参考 TEST_LOG.md M149.3/5 排障流程。"
        ) from exc
    raise _PreflightFailed("数据面探针失败：流结束但未收到任何数据 chunk")


def _on_alarm(signum, frame):
    raise _WatchdogTimeout(f"watchdog 超时（{WATCHDOG_SECONDS}s）")


def _db_events(db_path: str, factory_id: str) -> list[dict]:
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


def _load_dotenv_into_environ(path: Path) -> None:
    """加载 .env 到 os.environ（不覆盖已存在变量）。

    为何需要：worker 通过 os.environ.get("LITELLM_MASTER_KEY") 取 LiteLLM 鉴权 key；
    E2E 脚本若直接 `python scripts/e2e_m147_10tasks.py` 启动、shell 未 source .env，
    worker 会 fallback 到 EXO_API_KEY=dummy → LiteLLM 走 DB 校验路径 → 无 DB → 400，
    所有 LLM 调用静默失败，任务看似"卡死"实则在等永远拿不到的响应。
    与 scripts/start_proxy.sh 的 `set -a; . ./.env` 等价。
    """
    if not path.exists():
        return
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        k = k.strip()
        v = v.strip().strip('"').strip("'")
        if k and k not in os.environ:
            os.environ[k] = v


def main():
    for k in ("http_proxy", "HTTP_PROXY", "https_proxy", "HTTPS_PROXY", "ALL_PROXY", "all_proxy"):
        os.environ.pop(k, None)
    # M149: exo 端点改 MagicDNS studio01-1（旧裸 IP 100.64.201.37 已失效），.ts.net 后缀免疫 IP 漂移
    os.environ["NO_PROXY"] = "studio01-1,.ts.net,100.67.43.40,localhost,127.0.0.1,host.docker.internal"
    os.environ["no_proxy"] = os.environ["NO_PROXY"]

    # 关键：加载 .env → worker 才能拿到 LITELLM_MASTER_KEY 调 LiteLLM
    _load_dotenv_into_environ(ROOT / ".env")

    mp = os.environ.get("FLIPPED_E2E_MP", "3")
    tag = os.environ.get("FLIPPED_E2E_TAG", "")
    os.environ["FLIPPED_MAX_PARALLEL"] = mp
    os.environ["FLIPPED_AUTO_PROPOSER"] = "1"
    os.environ["FLIPPED_TASK_TIMEOUT"] = os.environ.get(
        "FLIPPED_TASK_TIMEOUT", "10800"
    )  # 单任务 3h：GLM-fp8 实测单任务 1-1.5h（thinking off），留 2x 裕量
    # M149.6：GLM-5.2-fp8 经 exo 时 thinking on 必乱码（变体 C/F 实测），
    # E2E 强制关 thinking；worker M149.6 起默认已 false，此处防御 shell 环境污染。
    os.environ["FLIPPED_WORKER_ENABLE_THINKING"] = "0"

    from driving.factory_loop import run_factory_loop

    # workdir 必须在 $HOME/projects 下——OpenHands 容器挂载 $HOME/projects:/projects，
    # /tmp 在容器内是独立 tmpfs，worker 写的文件宿主机 verify_cmd 读不到 → 必败。
    workdir = os.path.expanduser(f"~/projects/flipped_m147_e2e{tag}")
    shutil.rmtree(workdir, ignore_errors=True)
    os.makedirs(workdir, exist_ok=True)
    # M149.7：git init + 空 commit——v8 实测 worktree_manager 对非 git 目录报
    # "not a git repository"、对无 commit 目录报 "invalid reference: HEAD"，
    # worktree_path 为空导致任务隔离失效（每次重试都刷 ERROR）
    import subprocess
    subprocess.run(["git", "init", "-q"], cwd=workdir, check=True)
    subprocess.run(
        ["git", "-c", "user.name=e2e", "-c", "user.email=e2e@local",
         "commit", "-q", "--allow-empty", "-m", "init"],
        cwd=workdir, check=True,
    )

    db_path = f"data/factory_m147_e2e{tag}.db"
    abs_db = str(ROOT / db_path)
    if os.path.exists(abs_db):
        os.remove(abs_db)
        print(f"[E2E] 已删除旧库: {abs_db}")

    goal = (
        "创建一个小型 Python 工具项目，包含：\n"
        "1. config.py：配置管理（JSON 读写、环境变量覆盖）\n"
        "2. utils.py：工具函数（字符串处理、日期格式化）\n"
        "3. tests/test_config.py 和 tests/test_utils.py：pytest 测试\n"
        "4. pyproject.toml：项目配置\n"
        "要求：类型注解、代码风格一致。"
    )

    print(f"[E2E] 工作目录: {workdir}")
    print(f"[E2E] 产品目标: {goal[:100]}...")
    print(f"[E2E] max_tasks=12  FLIPPED_MAX_PARALLEL={mp}")
    print(f"[E2E] watchdog={WATCHDOG_SECONDS}s")
    print()

    # M149.5 前置数据面探针（~15k tokens 代表性 prompt，拒绝空跑）
    try:
        _preflight_data_plane()
    except _PreflightFailed as exc:
        print(f"[E2E] ABORT ❌ {exc}")
        return 2
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
            max_tasks=12,
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
    iteration_count = 0
    if state is not None:
        factory_id = state.factory_id
        final_status = state.status.value
        completed_n = len(state.completed)
        failed_n = len(state.failed)
        roadmap = state.roadmap
        iteration_count = state.iteration_count
        print(f"  工厂 ID: {factory_id}")
        print(f"  最终状态: {final_status}")
        print(f"  迭代次数: {iteration_count}")
        print(f"  roadmap 任务数: {len(roadmap)}")
        print(f"  完成: {completed_n}  失败: {failed_n}")
        print()
        print("[Roadmap]")
        for t in roadmap:
            print(f"  {t.id} [{t.status.value}] attempts={t.attempts}")
            print(f"    desc: {t.description[:80]}")
            print(f"    verify: {t.verify_cmd}")

    if factory_id is None:
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
    fixes = [e for e in events if "auto_fix" in e["kind"].lower()]
    proposals = [e for e in events if "proposer" in e["kind"].lower()]

    print()
    print("[事件日志]")
    print(f"  总事件数: {len(events)}")
    print(f"  task_start: {len(starts)}  task_done: {len(dones)}")
    print(f"  infra 相关: {len(infra)}  auto_fix: {len(fixes)}  proposer: {len(proposals)}")

    keys = [e["idempotency_key"] for e in events if e["idempotency_key"]]
    dup_keys = sorted({k for k in keys if keys.count(k) > 1})
    print(f"  幂等键总数: {len(keys)}  重复键: {len(dup_keys)}")
    for k in dup_keys:
        print(f"    [违规] 重复幂等键: {k}")

    print()
    print("[task_start 时间戳]")
    start_ts = []
    for e in starts:
        ts = e["ts"]
        start_ts.append(datetime.fromisoformat(ts).timestamp())
        print(f"  seq={e['seq']} ts={ts} key={e['idempotency_key']}")
    concurrency_evidence = False
    if len(start_ts) >= 2:
        gaps = [abs(b - a) for a, b in zip(start_ts, start_ts[1:])]
        min_gap = min(gaps)
        concurrency_evidence = min_gap < 60
        print(f"  相邻 task_start 最小间隔: {min_gap:.1f}s → 并发证据: {'是' if concurrency_evidence else '否'}")

    if dones:
        print("[task_done 时间戳]")
        for e in dones:
            print(f"  seq={e['seq']} ts={e['ts']} key={e['idempotency_key']}")

    # M149: MP=1 时任务本就串行派发，并发证据检查不适用（v6 误判 FAIL 的根因之一）
    mp_int = int(mp)
    ok_completed = completed_n >= 8 or (timed_out and len(dones) >= 8)
    ok_idem = not dup_keys
    ok_concurrency = concurrency_evidence or mp_int == 1
    ok_infra = (not infra) or (final_status == "done")
    passed = ok_completed and ok_idem and ok_concurrency and ok_infra and not timed_out

    print()
    print("[判定依据]")
    print(f"  completed >= 8: {'✅' if ok_completed else '❌'} ({completed_n})")
    print(f"  幂等键无重复:   {'✅' if ok_idem else '❌'}")
    if mp_int == 1:
        print(f"  真实并发证据:   ⏭️  豁免（FLIPPED_MAX_PARALLEL=1 单并发模式）")
    else:
        print(f"  真实并发证据:   {'✅' if ok_concurrency else '❌'}")
    print(f"  无 infra 失败:  {'✅' if ok_infra else '❌'}")
    print(f"  未超时:         {'✅' if not timed_out else '❌'}")
    print(f"  auto_fix 触发:  {'✅' if fixes else '⚠'} ({len(fixes)} 次)")
    print(f"  proposer 触发:  {'✅' if proposals else '⚠'} ({len(proposals)} 次)")
    print()
    if passed:
        print(f"[判定] PASS ✅  墙钟 {wall:.1f}s，{completed_n} 任务完成，10-task 完整产线验证通过")
        return 0
    print(f"[判定] FAIL ❌  墙钟 {wall:.1f}s，status={final_status} completed={completed_n} failed={failed_n}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
