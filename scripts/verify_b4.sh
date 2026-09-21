#!/bin/bash
# B4 验收：tool-calling 加固 + cost warning 修复
# 跑一个真实的 orchestrator 闭环：GLM Supervisor → OpenHands Worker(Kimi) → GLM Overseer → 强制验证。
# Verifier 用 docker exec 检查容器内文件，因为 Worker 在 Docker 沙盒中执行。
set -euo pipefail

cd "$(dirname "$0")/.."
ROOT=$(pwd)

source .venv/bin/activate

# 直连 exo，绕过当前 LiteLLM proxy 的 Postgres/prisma 阻塞
# M192: 主机名漂移跟进（dgmt-studio01mac-studio）+ 单模型默认（GLM-5.2-fp8，Kimi 已下线）
export NO_PROXY="dgmt-studio01mac-studio,.ts.net,${NO_PROXY:-localhost,127.0.0.1,::1}"
export PYTHONPATH="${ROOT}/src"
export FLIPPED_MODEL_BASE_URL="${FLIPPED_MODEL_BASE_URL:-http://dgmt-studio01mac-studio:52415/v1}"
export FLIPPED_ARCHITECT_MODEL="${FLIPPED_ARCHITECT_MODEL:-mlx-community/GLM-5.2-fp8}"
export FLIPPED_CODER_MODEL="${FLIPPED_CODER_MODEL:-mlx-community/GLM-5.2-fp8}"
export OPENHANDS_BASE_URL="${OPENHANDS_BASE_URL:-http://dgmt-studio01mac-studio:52415/v1}"
export OPENHANDS_MODEL="${OPENHANDS_MODEL:-openai/mlx-community/GLM-5.2-fp8}"
export EXO_API_KEY="${EXO_API_KEY:-dummy}"

CONTAINER="flipped-oh-canvas"
GOAL="在 /workspace 下创建文件 b4_done.txt，内容写 hello；然后确认文件存在且内容正确。"
VERIFY_IN_CONTAINER="test -f /workspace/b4_done.txt && grep -q hello /workspace/b4_done.txt"
export CONTAINER GOAL VERIFY_IN_CONTAINER

echo "[B4] Supervisor 模型=${FLIPPED_ARCHITECT_MODEL}"
echo "[B4] Worker  模型=${OPENHANDS_MODEL}"
echo "[B4] 模型 base_url=${FLIPPED_MODEL_BASE_URL}"

# 清理上一轮可能残留的文件
docker exec "${CONTAINER}" sh -c "rm -f /workspace/b4_done.txt" 2>/dev/null || true

python3 - <<PY
import os, subprocess, sys
from langgraph.checkpoint.sqlite import SqliteSaver

from driving.orchestrator import (
    build_orchestrator,
    default_supervisor,
    openhands_worker,
    default_overseer,
)


def docker_verifier(cmd: list[str], cwd: str):
    # 实际验证在 Docker 容器内执行，cwd 参数对 docker exec 无意义
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    return p.returncode == 0, (p.stdout + p.stderr)[-2000:]


initial = {
    "goal": os.environ["GOAL"],
    "cwd": "/workspace",
    "verify_cmd": ["docker", "exec", os.environ["CONTAINER"], "sh", "-c", os.environ["VERIFY_IN_CONTAINER"]],
    "max_iterations": 3,
    "loop_threshold": 3,
    "iteration": 0,
    "signatures": [],
    "feedback": "",
    "verified": False,
    "done": False,
    "stop_reason": "",
    "history": [],
    "require_approval": False,
    "worker_error": False,
}

with SqliteSaver.from_conn_string(":memory:") as cp:
    graph = build_orchestrator(
        default_supervisor,
        openhands_worker,
        default_overseer,
        docker_verifier,
        checkpointer=cp,
    )
    final = graph.invoke(initial, config={"configurable": {"thread_id": "b4"}})

print("\n最终状态:")
print(f"  verified={final.get('verified')}")
print(f"  stop_reason={final.get('stop_reason')}")
print(f"  iteration={final.get('iteration')}")
print(f"  history steps={len(final.get('history', []))}")

if final.get("verified") and final.get("stop_reason") == "verified":
    print("PASS: B4 tool-calling + cost warning 闭环验收通过")
    sys.exit(0)
else:
    print("FAIL: 未通过强制验证", file=sys.stderr)
    sys.exit(1)
PY
