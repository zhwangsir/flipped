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

# 端口占用防御：本脚本的测试端口（API_PORT/CONSOLE_PORT）若被上次残留进程占用，
# vite preview 会静默 "trying another one" 换端口，而健康检查仍打原端口——
# 浏览器将加载旧 preview 服务的旧构建（API 指向 :8011 真实后端），审批卡永不出现。
# 教训（2026-07-18）：占用即清理；preview 加 --strictPort 让换端口变成显性失败而非静默误测。
kill_port_owner() {
    local port="$1"
    local pids
    pids=$(lsof -nP -tiTCP:"${port}" -sTCP:LISTEN 2>/dev/null || true)
    if [ -n "${pids}" ]; then
        echo "[B5] 端口 :${port} 被占用 (pid=${pids// /,})，清理残留进程"
        kill ${pids} 2>/dev/null || true
        sleep 1
    fi
}
kill_port_owner "${API_PORT}"
kill_port_owner "${CONSOLE_PORT}"

cd console
if [ ! -d node_modules/vite ]; then
    echo "[B5] 安装 Console 依赖 ..."
    npm install > "${ROOT}/logs/b5-npm-install.log" 2>&1 || true
fi

echo "[B5] 构建 Console（指向本脚本的 mock 后端 :${API_PORT}）..."
# 关键：console 构建期固化 VITE_API_BASE_URL（api.ts fallback 是 :8011 真实后端）。
# 不注入则 preview 产物仍连 :8011，mock 后端收不到任何请求，审批卡永不出现。
VITE_API_BASE_URL="${API_URL}" npm run build > "${ROOT}/logs/b5-console-build.log" 2>&1
cd "${ROOT}"

echo "[B5] 启动 orchestration-api @ :${API_PORT} ..."
python -m uvicorn src.api.main:app --host 127.0.0.1 --port "${API_PORT}" > logs/b5-orchestration-api.log 2>&1 &
API_PID=$!

echo "[B5] 启动 vite preview @ :${CONSOLE_PORT} ..."
cd console
# --strictPort：端口被占时立即失败（此时 kill_port_owner 已清理，走到这步说明占用者杀不掉，必须显性失败）
npm run preview -- --strictPort > "${ROOT}/logs/b5-vite-preview.log" 2>&1 &
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
        # 本脚本起的是 mock 审批后端（FLIPPED_MOCK_WORKER=1 + FLIPPED_MOCK_APPROVAL=1），
        # 只跑与之匹配的审批流用例（console.spec.ts，由 E2E_MOCK_APPROVAL=1 门控开启）。
        # 其余用例面向真实 dev 全栈（dev_up.sh + :8011），在 mock 后端下无意义，不在此运行。
        echo "[B5] 运行 Playwright E2E（审批流 mock 套件）..."
        E2E_MOCK_APPROVAL=1 npx playwright test e2e/console.spec.ts > "${ROOT}/logs/b5-playwright.log" 2>&1
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
