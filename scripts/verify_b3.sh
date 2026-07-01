#!/bin/bash
# B3 验收：Console 接入真实 WS 数据流
# - 构建 Console
# - 启动 orchestration-api（mock worker，避免依赖模型）
# - 创建会话 + 派发任务
# - 通过 WS 收集真实事件并断言事件类型
# - 静态托管 console/dist 并验证首页可访问
set -euo pipefail

cd "$(dirname "$0")/.."
ROOT=$(pwd)
API_PORT=${API_PORT:-8001}
CONSOLE_PORT=${CONSOLE_PORT:-5274}
API_URL="http://127.0.0.1:${API_PORT}"
CONSOLE_URL="http://127.0.0.1:${CONSOLE_PORT}"

source .venv/bin/activate
export FLIPPED_MOCK_WORKER=1
export PYTHONPATH="${ROOT}/src"

echo "[B3] 构建 Console ..."
cd console
npm run build > "${ROOT}/logs/console-build.log" 2>&1
cd "${ROOT}"

echo "[B3] 启动 orchestration-api @ :${API_PORT} ..."
python -m uvicorn src.api.main:app --host 127.0.0.1 --port "${API_PORT}" > logs/orchestration-api.log 2>&1 &
API_PID=$!

echo "[B3] 静态托管 console/dist @ :${CONSOLE_PORT} ..."
python -m http.server "${CONSOLE_PORT}" --directory console/dist > logs/console-server.log 2>&1 &
HTTP_PID=$!

cleanup() {
    echo "[B3] 清理进程 (api=${API_PID}, http=${HTTP_PID})"
    kill "${API_PID}" "${HTTP_PID}" 2>/dev/null || true
    wait "${API_PID}" 2>/dev/null || true
    wait "${HTTP_PID}" 2>/dev/null || true
}
trap cleanup EXIT

echo "[B3] 等待服务就绪 ..."
for i in $(seq 1 30); do
    if curl -fs "${API_URL}/api/v1/health" >/dev/null 2>&1 && curl -fs "${CONSOLE_URL}" >/dev/null 2>&1; then
        break
    fi
    sleep 1
done

curl -fs "${API_URL}/api/v1/health" >/dev/null || { cat logs/orchestration-api.log; exit 1; }
curl -fs "${CONSOLE_URL}" >/dev/null || { cat logs/console-server.log; exit 1; }

echo "[B3] 创建会话 → 派发任务 → WS 收集真实事件 ..."
python3 - <<PY
import asyncio, json, os, sys, time
import httpx
import websockets

API = "${API_URL}"
WS = API.replace("http://", "ws://")

def http(path, method="GET", json=None):
    r = httpx.request(method, f"{API}{path}", json=json, timeout=10)
    r.raise_for_status()
    return r.json()

async def main():
    # 创建会话
    sess = http("/api/v1/sessions?title=B3%20Console%20WS", "POST")
    sid = sess["id"]
    print(f"[B3] session_id={sid}")

    # 派发任务（触发 mock worker 产生事件流）
    http(f"/api/v1/sessions/{sid}/tasks", "POST", {
        "description": "用 FastAPI 建一个 Todo API，写 pytest 跑通，并在内置浏览器打开 /docs 确认。"
    })

    # 连 WS 收集事件
    uri = f"{WS}/api/v1/sessions/{sid}/events"
    events = []
    done = False
    async with websockets.connect(uri, open_timeout=5, close_timeout=5, proxy=None) as ws:
        await ws.send(json.dumps({"type": "ping"}))
        for _ in range(120):  # 最多 2 分钟
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=1.0)
                data = json.loads(msg)
                events.append(data)
                print("event:", data.get("type"), data.get("agent"))
            except asyncio.TimeoutError:
                pass
            if any(e.get("type") == "status" and e.get("payload", {}).get("status") == "done" for e in events):
                done = True
                break

    print(f"\n共收到 {len(events)} 个事件")
    types = {e.get("type") for e in events}
    print("事件类型:", sorted(types))

    required = {"message", "tool_call", "tool_result", "file_change", "terminal", "browser", "status"}
    missing = required - types
    if missing:
        print("FAIL: 缺少事件类型:", missing, file=sys.stderr)
        sys.exit(2)
    if not done:
        print("FAIL: 未收到完成状态", file=sys.stderr)
        sys.exit(3)

    # 验证首页包含 WebSocket/事件相关脚本产物引用
    home = httpx.get("${CONSOLE_URL}").text
    if "index-" not in home:
        print("FAIL: Console 首页未引用构建产物", file=sys.stderr)
        sys.exit(4)

    print("PASS: B3 Console 真实 WS 数据流验收通过")

asyncio.run(main())
PY
export NO_PROXY="127.0.0.1,localhost,::1"
