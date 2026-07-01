#!/bin/bash
# B1 验收：orchestration-api 会话 CRUD + WebSocket 事件流
set -euo pipefail

cd "$(dirname "$0")/.."
ROOT=$(pwd)
API_PORT=${API_PORT:-8001}
API_URL="http://127.0.0.1:${API_PORT}"
WS_URL="ws://127.0.0.1:${API_PORT}/api/v1/sessions"

source .venv/bin/activate
export FLIPPED_MOCK_WORKER=1

echo "[B1] 启动 orchestration-api @ :${API_PORT} ..."
PYTHONPATH="${ROOT}/src" python -m uvicorn src.api.main:app --host 127.0.0.1 --port "${API_PORT}" > logs/orchestration-api.log 2>&1 &
SERVER_PID=$!

cleanup() {
    echo "[B1] 清理服务器 (pid ${SERVER_PID})"
    kill "${SERVER_PID}" 2>/dev/null || true
    wait "${SERVER_PID}" 2>/dev/null || true
}
trap cleanup EXIT

# 等健康检查通过
echo "[B1] 等待服务就绪 ..."
for i in $(seq 1 30); do
    if curl -fs "${API_URL}/api/v1/health" > /tmp/b1_health.json 2>/dev/null; then
        echo "[B1] health ok:"
        cat /tmp/b1_health.json
        break
    fi
    sleep 1
done

if ! curl -fs "${API_URL}/api/v1/health" > /tmp/b1_health.json 2>/dev/null; then
    echo "[B1] 服务未就绪"
    cat logs/orchestration-api.log
    exit 1
fi

echo "[B1] 创建会话 ..."
SESSION_JSON=$(curl -fs -X POST "${API_URL}/api/v1/sessions?title=FastAPI%20Todo%20API" -H "Content-Type: application/json")
SESSION_ID=$(echo "${SESSION_JSON}" | python -c "import sys,json; print(json.load(sys.stdin)['id'])")
echo "[B1] session_id=${SESSION_ID}"

echo "[B1] 派发任务 ..."
curl -fs -X POST "${API_URL}/api/v1/sessions/${SESSION_ID}/tasks" \
    -H "Content-Type: application/json" \
    -d '{"description":"用 FastAPI 建一个 Todo API，写 pytest 跑通，并在内置浏览器打开 /docs 确认。"}'

echo "[B1] 连接 WebSocket 收集事件 ..."
python - <<PY
import asyncio, json, sys, websockets

async def main():
    uri = "${WS_URL}/${SESSION_ID}/events"
    events = []
    try:
        async with websockets.connect(uri, open_timeout=5, close_timeout=5) as ws:
            await ws.send(json.dumps({"type":"ping"}))
            for _ in range(60):
                try:
                    msg = await asyncio.wait_for(ws.recv(), timeout=1.0)
                    data = json.loads(msg)
                    events.append(data)
                    print("event:", data.get("type"), data.get("agent"), data.get("payload",{}).get("summary",""))
                except asyncio.TimeoutError:
                    continue
                if any(e.get("type") == "status" and e.get("payload",{}).get("status") == "done" for e in events):
                    break
    except Exception as e:
        print("WS error:", e, file=sys.stderr)
        sys.exit(1)

    types = [e.get("type") for e in events]
    agents = {e.get("agent") for e in events}
    print(f"\n共收到 {len(events)} 个事件")
    print("事件类型:", sorted(set(types)))
    print("出现角色:", sorted(agents))

    required_types = {"message", "tool_call", "tool_result", "file_change", "terminal", "browser", "status"}
    missing = required_types - set(types)
    if missing:
        print("FAIL: 缺少事件类型:", missing, file=sys.stderr)
        sys.exit(2)

    required_agents = {"user", "supervisor", "worker", "overseer", "verify", "system"}
    missing_agents = required_agents - agents
    if missing_agents:
        print("FAIL: 缺少角色:", missing_agents, file=sys.stderr)
        sys.exit(3)

    if not any(e.get("type") == "status" and e.get("payload",{}).get("status") == "done" for e in events):
        print("FAIL: 未收到完成状态", file=sys.stderr)
        sys.exit(4)

    print("PASS: B1 验收通过")

asyncio.run(main())
PY

echo "[B1] 查询会话最终状态 ..."
curl -fs "${API_URL}/api/v1/sessions/${SESSION_ID}" | python -m json.tool
