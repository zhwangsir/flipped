#!/usr/bin/env python3
"""M156.9 · OpenHandsWorker 最小诊断脚本。

目的：隔离 M147-A E2E v2 在 factory_loop planner 阶段卡住的根因。
策略：绕过 factory_loop 编排层，直接调 OpenHandsWorker.run() 跑一个最小任务
      （创建 hello.py），5 分钟内给出明确结论：
        - 如果成功 → 问题在 factory_loop 层（planner/roadmap/编排逻辑）
        - 如果失败 → 问题在 OpenHandsWorker 层（LLM/agent-server/SDK）
        - 如果卡住 → 看卡在哪一步（LLM 调用 / agent-server 连接 / conversation.run）

用法：.venv/bin/python -u scripts/diag_openhands_worker.py
"""
from __future__ import annotations

import os
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))


def _load_dotenv(env_path: Path) -> None:
    """复用 e2e_m147 的 .env 加载逻辑（worker 需要 LITELLM_MASTER_KEY）。"""
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


def main() -> int:
    # 1) 环境清理 + .env 加载
    for k in ("http_proxy", "HTTP_PROXY", "https_proxy", "HTTPS_PROXY", "ALL_PROXY", "all_proxy"):
        os.environ.pop(k, None)
    os.environ["NO_PROXY"] = "dgmt-studio01mac-studio,.ts.net,100.67.43.40,localhost,127.0.0.1,host.docker.internal"
    os.environ["no_proxy"] = os.environ["NO_PROXY"]
    _load_dotenv(ROOT / ".env")

    # 单模型模式：coder=GLM-5.2-fp8（与 .env / model_router 默认一致）
    os.environ["FLIPPED_CODER_MODEL"] = "mlx-community/GLM-5.2-fp8"
    # M149.6：thinking 默认关（GLM 单模型期决策，防 reasoning_content 抢占 content）
    os.environ["FLIPPED_WORKER_ENABLE_THINKING"] = "0"
    # 缩短 timeout 避免无限等待（5 分钟内必须出结果）
    os.environ["FLIPPED_WORKER_TIMEOUT"] = "300"
    os.environ["FLIPPED_WORKER_MAX_ITERATIONS"] = "5"
    # M156.10 修复：不覆盖 OPENHANDS_PROXY_BASE_URL。该变量是给容器内 agent-server
    # 用的，必须 host.docker.internal（容器视角）；之前误设 localhost:4000 导致
    # 容器内连不到宿主机 LiteLLM → Connection error。
    # resolve_worker_model_config 默认返回 DEFAULT_WORKER_PROXY_URL=host.docker.internal:4000。

    print("[DIAG] === M156.9 OpenHandsWorker 最小诊断 ===", flush=True)
    print(f"[DIAG] FLIPPED_CODER_MODEL={os.environ.get('FLIPPED_CODER_MODEL')}", flush=True)
    print(f"[DIAG] FLIPPED_WORKER_ENABLE_THINKING={os.environ.get('FLIPPED_WORKER_ENABLE_THINKING')}", flush=True)
    print(f"[DIAG] FLIPPED_WORKER_TIMEOUT={os.environ.get('FLIPPED_WORKER_TIMEOUT')}", flush=True)
    print(f"[DIAG] LITELLM_MASTER_KEY={'***set***' if os.environ.get('LITELLM_MASTER_KEY') else 'NOT SET'}", flush=True)

    # 2) 前置探针：LiteLLM proxy + OpenHands agent-server
    print("\n[DIAG] === 前置探针 ===", flush=True)
    import httpx
    _master_key = os.environ.get("LITELLM_MASTER_KEY") or os.environ.get("EXO_API_KEY")
    _headers = {"Authorization": f"Bearer {_master_key}"} if _master_key else {}
    try:
        r = httpx.get("http://localhost:4000/v1/models", headers=_headers, timeout=5.0)
        models = [m["id"] for m in r.json().get("data", [])]
        print(f"[DIAG] LiteLLM proxy :4000 OK, models={models}", flush=True)
        assert "architect" in models and "coder" in models, "双别名缺失"
    except Exception as e:
        print(f"[DIAG] ✗ LiteLLM proxy 不可用: {type(e).__name__}: {e}", flush=True)
        return 1

    try:
        r = httpx.get("http://localhost:8000/alive", timeout=5.0)
        print(f"[DIAG] OpenHands agent-server :8000 OK, alive={r.json()}", flush=True)
    except Exception as e:
        print(f"[DIAG] ✗ OpenHands agent-server 不可用: {type(e).__name__}: {e}", flush=True)
        return 1

    # 3) 准备 workdir（必须在 ~/projects 下，容器挂载点）
    workdir = os.path.expanduser("~/projects/flipped_diag_m156")
    shutil.rmtree(workdir, ignore_errors=True)
    os.makedirs(workdir, exist_ok=True)
    # git init（OpenHands SDK 需要 git 仓库）
    import subprocess
    subprocess.run(["git", "init", "-q"], cwd=workdir, check=True)
    subprocess.run(
        ["git", "-c", "user.name=diag", "-c", "user.email=diag@local",
         "commit", "-q", "--allow-empty", "-m", "init"],
        cwd=workdir, check=True,
    )
    print(f"\n[DIAG] workdir={workdir}", flush=True)

    # 4) 创建 OpenHandsWorker
    print("\n[DIAG] === 创建 OpenHandsWorker ===", flush=True)
    from api.events import EventBus
    from api.session import SessionStore
    from executor.openhands_worker import OpenHandsWorker

    store = SessionStore()
    bus = EventBus(store)
    session_id = "diag-m156"
    task_id = "diag-task-1"
    # 用 resolve_worker_model_config 拿到真实路由（单模型模式：coder=GLM-5.2-fp8）
    from driving.model_router import resolve_worker_model_config
    base_url, model_name = resolve_worker_model_config("coder")
    print(f"[DIAG] resolve_worker_model_config('coder') → base_url={base_url}, model={model_name}", flush=True)
    # 走 proxy 时 model_name 是别名 "coder"，走直连时是 full model name "mlx-community/GLM-5.2-fp8"
    # 关键：LiteLLM config.yaml 里 coder 别名已指 GLM-5.2-fp8（Kimi 已下线）
    assert model_name == "coder" or "GLM" in model_name, (
        f"期望 coder 别名或 GLM 全名，实际 {model_name}"
    )

    worker = OpenHandsWorker(
        session_id=session_id,
        task_id=task_id,
        bus=bus,
        agent_host="http://localhost:8000",
        working_dir=workdir,
        model_alias="coder",  # 走 LiteLLM proxy 的 coder 别名
        base_url=base_url,
        manage_session_status=False,  # 不污染会话状态
    )
    print(f"[DIAG] worker.model_alias={worker.model_alias}", flush=True)
    print(f"[DIAG] worker.base_url={worker.base_url}", flush=True)
    print(f"[DIAG] worker.working_dir={worker.working_dir}", flush=True)
    print(f"[DIAG] worker.max_iterations={worker.max_iterations}", flush=True)
    print(f"[DIAG] worker.timeout={worker.timeout}", flush=True)

    # 5) 订阅 bus 事件实时打印（看卡在哪一步）
    print("\n[DIAG] === 派发任务 ===", flush=True)
    task_desc = "创建 hello.py 文件，内容为：print('hello world')。然后用 python hello.py 验证能运行。"
    print(f"[DIAG] task={task_desc}", flush=True)

    # 实时打印 bus 事件
    import threading
    seen_events = []
    stop_listener = threading.Event()

    def _listen():
        last_count = 0
        while not stop_listener.is_set():
            events = store.events(session_id)
            if len(events) > last_count:
                for e in events[last_count:]:
                    seen_events.append(e)
                    ts = getattr(e, "ts", "")
                    print(f"[EVENT] {ts[-15:]} type={e.type} agent={getattr(e, 'agent', '')} "
                          f"payload={str(getattr(e, 'payload', ''))[:200]}", flush=True)
                last_count = len(events)
            time.sleep(0.5)

    listener = threading.Thread(target=_listen, daemon=True)
    listener.start()

    # 6) 调 worker.run()（阻塞，最多 300s）
    t0 = time.monotonic()
    print(f"\n[DIAG] [{time.monotonic()-t0:.1f}s] 调用 worker.run() ...", flush=True)
    try:
        result = worker.run(task_desc)
        elapsed = time.monotonic() - t0
        print(f"\n[DIAG] [{elapsed:.1f}s] worker.run() 返回: {result}", flush=True)
        # M199 跟进：worker 返回的是枚举 repr 'ConversationExecutionStatus.FINISHED'，
        # 不是裸 'finished'——子串匹配兼容两种形态。
        _st = str(result.get("status", "")).lower()
        success = "finished" in _st or _st == "done"
        print(f"[DIAG] status={'✓ SUCCESS' if success else '⚠ UNEXPECTED STATUS'}", flush=True)
    except Exception as e:
        elapsed = time.monotonic() - t0
        print(f"\n[DIAG] [{elapsed:.1f}s] ✗ worker.run() 抛异常: {type(e).__name__}: {e}", flush=True)
        import traceback
        traceback.print_exc()
    finally:
        stop_listener.set()
        listener.join(timeout=2.0)

    # 7) 检查 workdir 是否有 hello.py
    print(f"\n[DIAG] === 检查 workdir 产出 ===", flush=True)
    print(f"[DIAG] workdir contents:", flush=True)
    for p in sorted(Path(workdir).iterdir()):
        print(f"  {p.name} ({p.stat().st_size} bytes)", flush=True)

    hello_py = Path(workdir) / "hello.py"
    if hello_py.exists():
        print(f"\n[DIAG] ✓ hello.py 已创建，内容:", flush=True)
        print(hello_py.read_text(), flush=True)
        print(f"[DIAG] === 结论：OpenHandsWorker 层正常，问题在 factory_loop 编排层 ===", flush=True)
        return 0
    else:
        print(f"\n[DIAG] ✗ hello.py 未创建", flush=True)
        print(f"[DIAG] === 结论：OpenHandsWorker 层未能产出文件，需进一步诊断 worker 事件流 ===", flush=True)
        print(f"[DIAG] 总事件数: {len(seen_events)}", flush=True)
        # 打印 worker.events 类型分布
        from collections import Counter
        type_counts = Counter(str(e.type) for e in seen_events)
        print(f"[DIAG] 事件类型分布: {dict(type_counts)}", flush=True)
        return 2


if __name__ == "__main__":
    sys.exit(main())
