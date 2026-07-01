#!/bin/bash
# B2 验收：Worker 迁移到 OpenHands SDK（直接调 exo，绕过当前 LiteLLM proxy DB 问题）
set -euo pipefail

cd "$(dirname "$0")/.."
ROOT=$(pwd)
API_PORT=${API_PORT:-8001}
API_URL="http://127.0.0.1:${API_PORT}"
WS_URL="ws://127.0.0.1:${API_PORT}/api/v1/sessions"

source .venv/bin/activate
set -a
. ./.env
# B2 直接调 exo 集群（ LiteLLM proxy 的 prisma DB 初始化被网络阻塞，见 B4）
export OPENHANDS_BASE_URL="${OPENHANDS_BASE_URL:-http://100.64.201.37:52415/v1}"
export OPENHANDS_MODEL="${OPENHANDS_MODEL:-openai/mlx-community/Kimi-K2.7-Code-4bit}"
export NO_PROXY="100.64.201.37,${NO_PROXY:-localhost,127.0.0.1,::1}"
set +a

echo "[B2] OPENHANDS_BASE_URL=${OPENHANDS_BASE_URL}"
echo "[B2] OPENHANDS_MODEL=${OPENHANDS_MODEL}"

echo "[B2] 启动 orchestration-api @ :${API_PORT} ..."
PYTHONPATH="${ROOT}/src" python -m uvicorn src.api.main:app --host 127.0.0.1 --port "${API_PORT}" > logs/orchestration-api.log 2>&1 &
SERVER_PID=$!

cleanup() {
    echo "[B2] 清理 API 服务器 (pid ${SERVER_PID})"
    kill "${SERVER_PID}" 2>/dev/null || true
    wait "${SERVER_PID}" 2>/dev/null || true
}
trap cleanup EXIT

# 等健康检查端点可用即可（不强制 proxy ok）
echo "[B2] 等待服务就绪 ..."
for i in $(seq 1 30); do
    if curl -fs "${API_URL}/api/v1/health" > /tmp/b2_health.json 2>/dev/null; then
        echo "[B2] health endpoint ok"
        break
    fi
    sleep 1
done
if ! curl -fs "${API_URL}/api/v1/health" > /tmp/b2_health.json 2>/dev/null; then
    cat logs/orchestration-api.log
    exit 1
fi

echo "[B2] 创建会话 ..."
SESSION_JSON=$(curl -fs -X POST "${API_URL}/api/v1/sessions?title=OpenHands%20B2%20%E9%AA%8C%E6%94%B6" -H "Content-Type: application/json")
SESSION_ID=$(echo "${SESSION_JSON}" | python -c "import sys,json; print(json.load(sys.stdin)['id'])")
echo "[B2] session_id=${SESSION_ID}"

echo "[B2] 派发真实任务到 OpenHands 沙盒 ..."
curl -fs -X POST "${API_URL}/api/v1/sessions/${SESSION_ID}/tasks" \
    -H "Content-Type: application/json" \
    -d '{"description":"在 /workspace 下创建 b2_hello.py，包含 def add(a,b): return a+b；创建 b2_hello_test.py，写一个 pytest 用例验证 add(2,3)==5；然后运行 python -m pytest -q /workspace/b2_hello_test.py 并确认通过。"}'

echo "[B2] 连接 WebSocket 收集真实事件 ..."
python - <<PY
import asyncio, json, sys, websockets

async def main():
    uri = "${WS_URL}/${SESSION_ID}/events"
    events = []
    done = False
    try:
        async with websockets.connect(uri, open_timeout=5, close_timeout=5) as ws:
            await ws.send(json.dumps({"type":"ping"}))
            for _ in range(300):  # 最多 10 分钟（每次等 2 秒）
                try:
                    msg = await asyncio.wait_for(ws.recv(), timeout=2.0)
                    data = json.loads(msg)
                    events.append(data)
                    print("event:", data.get("type"), data.get("agent"), data.get("payload",{}).get("summary","")[:60])
                except asyncio.TimeoutError:
                    pass
                if any(e.get("type") == "status" and e.get("payload",{}).get("status") == "done" for e in events):
                    done = True
                    break
                if any(e.get("type") == "status" and e.get("payload",{}).get("status") == "error" for e in events):
                    break
    except Exception as e:
        print("WS error:", e, file=sys.stderr)
        sys.exit(1)

    print(f"\n共收到 {len(events)} 个事件")
    types = {e.get("type") for e in events}
    print("事件类型:", sorted(types))

    required = {"tool_call", "tool_result", "terminal"}
    missing = required - types
    if missing:
        print("FAIL: 缺少事件类型:", missing, file=sys.stderr)
        sys.exit(2)
    if not done:
        print("FAIL: 未收到完成状态", file=sys.stderr)
        sys.exit(3)
    print("PASS: B2 WS 事件流验收通过")

asyncio.run(main())
PY

echo "[B2] 在沙盒内验证文件与 pytest ..."
docker exec flipped-oh-canvas sh -c '
set -e
cd /workspace
test -f b2_hello.py && echo "b2_hello.py exists"
test -f b2_hello_test.py && echo "b2_hello_test.py exists"
python -m pytest -q /workspace/b2_hello_test.py
'

echo "[B2] 查询会话最终状态 ..."
curl -fs "${API_URL}/api/v1/sessions/${SESSION_ID}" | python -m json.tool
