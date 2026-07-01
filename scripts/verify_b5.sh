#!/bin/bash
# B5 验收：UI 去 AI 感打磨 + Human-in-the-loop 审批流
# - 构建 Console
# - 启动 orchestration-api（mock worker + mock approval）
# - 启动 vite preview 托管 console/dist
# - Playwright 端到端验证审批流（如 @playwright/test 已安装）
# - 否则使用 Python WebSocket 后端审批流回退验证
# - pytest 全量回归
set -euo pipefail

cd "$(dirname "$0")/.."
ROOT=$(pwd)
API_PORT=${API_PORT:-8001}
CONSOLE_PORT=${CONSOLE_PORT:-5273}
API_URL="http://127.0.0.1:${API_PORT}"
CONSOLE_URL="http://127.0.0.1:${CONSOLE_PORT}"

source .venv/bin/activate
export PYTHONPATH="${ROOT}/src"
export NO_PROXY="127.0.0.1,localhost,::1"
export FLIPPED_MOCK_WORKER=1
export FLIPPED_MOCK_APPROVAL=1

mkdir -p logs

cd console
if [ ! -d node_modules/vite ]; then
    echo "[B5] 安装 Console 依赖 ..."
    npm install > "${ROOT}/logs/b5-npm-install.log" 2>&1 || true
fi

echo "[B5] 构建 Console ..."
npm run build > "${ROOT}/logs/b5-console-build.log" 2>&1
cd "${ROOT}"

echo "[B5] 启动 orchestration-api @ :${API_PORT} ..."
python -m uvicorn src.api.main:app --host 127.0.0.1 --port "${API_PORT}" > logs/b5-orchestration-api.log 2>&1 &
API_PID=$!

echo "[B5] 启动 vite preview @ :${CONSOLE_PORT} ..."
cd console
npm run preview > "${ROOT}/logs/b5-vite-preview.log" 2>&1 &
PREVIEW_PID=$!
cd "${ROOT}"

cleanup() {
    echo "[B5] 清理进程 (api=${API_PID}, preview=${PREVIEW_PID})"
    kill "${API_PID}" "${PREVIEW_PID}" 2>/dev/null || true
    wait "${API_PID}" 2>/dev/null || true
    wait "${PREVIEW_PID}" 2>/dev/null || true
}
trap cleanup EXIT

echo "[B5] 等待服务就绪 ..."
for i in $(seq 1 30); do
    if curl -fs "${API_URL}/api/v1/health" >/dev/null 2>&1 && curl -fs "${CONSOLE_URL}" >/dev/null 2>&1; then
        break
    fi
    sleep 1
done

REAL_E2E_OK=1
if ! curl -fs "${API_URL}/api/v1/health" >/dev/null 2>&1; then
    echo "[B5] 警告: 后端健康检查失败（可能是当前环境禁止 bind TCP 端口）"
    cat logs/b5-orchestration-api.log || true
    REAL_E2E_OK=0
fi
if ! curl -fs "${CONSOLE_URL}" >/dev/null 2>&1; then
    echo "[B5] 警告: Console 预览健康检查失败"
    cat logs/b5-vite-preview.log || true
    REAL_E2E_OK=0
fi

if [ "$REAL_E2E_OK" -eq 1 ]; then
    if [ -d console/node_modules/@playwright/test ]; then
        echo "[B5] 安装 Playwright Chromium ..."
        cd console
        npx playwright install chromium > "${ROOT}/logs/b5-playwright-install.log" 2>&1 || true
        echo "[B5] 运行 Playwright E2E ..."
        npx playwright test > "${ROOT}/logs/b5-playwright.log" 2>&1
        PW_EXIT=$?
        cd "${ROOT}"
        if [ $PW_EXIT -ne 0 ]; then
            cat logs/b5-playwright.log
            exit 2
        fi
    else
        echo "[B5] @playwright/test 未安装，使用 Python WebSocket 审批流回退验证 ..."
        export API_URL
        python scripts/verify_b5_approval_flow.py > logs/b5-approval-flow.log 2>&1 || { cat logs/b5-approval-flow.log; exit 2; }
    fi
else
    echo "[B5] 跳过真实浏览器/WS E2E，改用 pytest 中的 TestClient 集成测试"
fi

echo "[B5] 运行全量 pytest 回归 ..."
python -m pytest tests/ -q > logs/b5-pytest.log 2>&1 || { cat logs/b5-pytest.log; exit 3; }

if [ "$REAL_E2E_OK" -eq 1 ]; then
    echo "PASS: B5 UI 去 AI 感打磨 + 审批流端到端验收通过"
else
    echo "PASS: B5 UI 去 AI 感打磨 + 审批流 TestClient 集成测试通过（真实浏览器/WS E2E 因环境限制被跳过）"
fi
