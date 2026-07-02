 # flipped · 会话承接指南
 
 > 本文件供下一个 Agent / 人类开发者继续项目时快速恢复上下文。
 > 最后更新：2026-07-02
 
 ## 1. 项目快照
 
 - **项目名**：flipped
 - **工作目录**：`/Users/wangzhenyu/Desktop/flipped`
 - **当前分支**：`codex/m5-hardening`
 - **当前里程碑**：M5 · 硬化与产线化（性能/稳定性/安全/崩溃恢复）—— **已完成**
 - **最近提交**：
   - `64c2e92` M5.6: 长任务 checkpoint 崩溃恢复验收
   - `40a7cf2` M5.5: 安全加固
   - `f78573d` M5.4: crash recovery & resume checkpoint
 
 ## 2. 必读状态文件
 
 每轮接手必须按顺序读：
 
 1. `AGENTS.md` — 核心工作原则、审批/熔断规则、路线图。
 2. `STATE.json` — 当前里程碑状态、已知问题、后台服务。
 3. `PLAN.md` — 当前/下一步计划。
 4. `TEST_LOG.md` — 近期测试证据与结论。
 
 ## 3. 快速恢复环境
 
 ```bash
 cd /Users/wangzhenyu/Desktop/flipped
 git status
 git branch --show-current   # 应为 codex/m5-hardening
 source .venv/bin/activate
 export PYTHONPATH=src
 ```
 
 ## 4. 关键环境变量
 
 ```
 EXO_API_KEY=dummy
 OPENHANDS_AGENT_HOST=http://localhost:8000
 OPENHANDS_MODEL=openai/mlx-community/Kimi-K2.7-Code-4bit
 OPENHANDS_BASE_URL=http://100.64.201.37:52415/v1
 NO_PROXY=100.64.201.37,localhost,127.0.0.1,::1
 ```
 
 - 可选绕过 LiteLLM proxy：`FLIPPED_MODEL_BASE_URL`、`FLIPPED_ARCHITECT_MODEL`、`FLIPPED_CODER_MODEL`。
 - 测试时 `FLIPPED_MOCK_WORKER=1`、`FLIPPED_MOCK_ORCHESTRATOR=1` 用于注入 mock。
 
 ## 5. 后台服务状态
 
 | 服务 | 状态 | 启动命令 |
 |------|------|----------|
 | SearXNG (docker :8080) | running | `docker compose -f infra/searxng/docker-compose.yml --project-directory infra/searxng up -d` |
 | LiteLLM proxy :4000 | stopped | `bash scripts/start_proxy.sh`（当前因 Postgres/prisma 初始化阻塞） |
 | exo 集群 | 外置 | 由用户手动 LAUNCH 模型 |
 
 ## 6. 验证命令
 
 ```bash
 # 全量 Python 单测
 PYTHONPATH=src .venv/bin/python -m pytest tests/ -q
 
 # M5 里程碑验收
 bash scripts/verify_m5.sh
 
 # Console 构建
 cd console && npm run build
 ```
 
 最新证据：全量 92 passed，2 warnings；`verify_m5.sh` 退出码 0；console build 通过。
 
 ## 7. 代码地图
 
 - `src/api/` — FastAPI + WebSocket orchestration-api。
 - `src/driving/` — LangGraph 多 Agent 监督编排（`orchestrator.py`）、审批（`approval.py`）、安全（`safety.py`）、上下文压缩（`context_manager.py`）、模型路由（`model_router.py`）。
 - `src/executor/openhands_worker.py` — OpenHands SDK Worker。
 - `src/mcp_server/` — MCP stdio server。
 - `src/rag/` — Chroma 向量库。
 - `src/metrics/` — 性能指标收集与 `/api/v1/metrics`。
 - `console/src/` — React/Vite 控制台前端。
 
 ## 8. 已知阻塞与限制
 
 - **ISSUE-6**：当前 Codex 沙箱禁止 Python/Node bind TCP 与 outbound 网络，真实浏览器/WS E2E 被跳过，由 TestClient 集成测试兜底。
 - **LiteLLM proxy :4000**：因本地 Postgres/prisma 初始化阻塞，未运行。Worker 直连 exo，Supervisor/Overseer 可通过 `FLIPPED_MODEL_BASE_URL` 直连。
 - **HTTP_PROXY 劫持**：访问 exo 必须 `NO_PROXY` 含 `100.64.201.37`，否则被 Clash 代理成 502。
 
 ## 9. 如何继续
 
 1. 读 `AGENTS.md` → `STATE.json` → `PLAN.md` → `TEST_LOG.md`。
 2. 确认当前分支干净；如需要修复/新功能，先更新 `PLAN.md` 写明任务与验收标准。
 3. 写测试 → 实现 → 运行 `pytest` 与 `verify_m5.sh` → 记录证据到 `TEST_LOG.md`。
 4. 每个小里程碑完成后 `git commit` 并更新 `STATE.json`。
 
 ## 10. 建议下一步
 
 M5 已按 `AGENTS.md` 路线图完成。接下来可选：
 
 - 在非沙箱环境复跑真实 LLM + OpenHands 的长任务验收。
 - 修复 LiteLLM proxy 的 Postgres/prisma 启动阻塞，恢复 :4000 统一路由。
 - 产品化收尾：打包、Electron 桌面壳、CI 构建、签名分发。
 - 根据实际使用场景定义新 milestone（M6），并在 `STATE.json`/`PLAN.md` 中显式记录。
 
 ---
 
 任何问题先查 `TEST_LOG.md` 和 `STATE.json` 的已知问题，再动手。
