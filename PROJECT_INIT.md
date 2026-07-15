# flipped · 项目初始化文档

> 由项目管理中枢自动生成 | 更新日期: 2026-07-12 | 负责人: zhwangsir

## 一、项目基本信息

| 字段 | 值 |
|------|----|
| 项目名称 | flipped |
| 当前版本 | 0.2.0（orchestration API）；console 0.1.0 |
| 创建日期 | 2026 年 6 月（D18 转向：本地模型驱动的 AI 开发工厂） |
| 负责人 | zhwangsir |
| 项目路径 | /Users/wangzhenyu/Desktop/ALLProject/flipped |
| 远程仓库 | https://github.com/zhwangsir/flipped |
| 仓库可见性 | 公开（Public） |
| 线上地址 | （本地运行：API http://127.0.0.1:8011，Console http://127.0.0.1:5273，桌面壳 Tauri）|

## 二、项目概述与核心功能

### 2.1 项目定位
本地模型驱动的 AI 自主开发工厂（D18）——像 Claude Code / Codex 一样，给一个目标，系统自己**拆解 → 写码 → 跑测 → 修错 → 循环直到验收通过 → 提交成果**，全程可见、可控、可续跑。基于 OpenHands 沙盒执行 + 自研多 Agent 监督驾驭层，接入本地 exo 集群两个 MLX 模型。可自行无限迭代的 AI 自动化开发工厂。

### 2.2 核心功能列表
- **自主开发循环 F1–F10**（全部完成并验证）：
  - F1 真实自我验证（探测项目怎么验证并在沙盒内跑真测判定）
  - F2 透明实时循环（Supervisor/Worker/Overseer/Verify 每步推 WS 事件，去黑盒）
  - F3 一等自主模式（`mode=auto` 一键启动，自动探测验证命令）
  - F4 实时计划清单（子任务聚成带状态清单 ✓/⟳/↻/✗ 钉对话流顶）
  - F5 仓库记忆（项目结构地图喂 Supervisor）
  - F6 项目规则（读 AGENTS.md/.cursorrules/CLAUDE.md 遵守项目约定）
  - F7 交付步（验收通过后沙盒内自动 git commit，注入安全）
  - F9 并行线程状态板（多自主线程运行状态实时总览）
  - F10 用量/预算感知（顶栏本地模型 token 用量芯片）
- **多 Agent 监督编排**（D15 核心）：Supervisor（GLM-5.2）拆任务 → Worker（Kimi-K2.7-Code）沙盒执行 → Overseer（GLM-5.2）监督效率/方向
- **双模型并行验证**（D19）：Worker 产出后，GLM 与确定性 verifier 经 ThreadPoolExecutor 并行验证（设计/结构/a11y/bug），合并 det_ok AND glm_severity!=blocker
- **无限迭代外层循环**：factory_loop + infinite_loop + task_proposer（GLM 不可用时三层确定性 fallback：task_proposer → design_fix_fallback → feature_fallback）
- **设计质量系统**：37 维 lint + 35 组 auto-fix + design_score 9 维评分 + WCAG 颜色对比度 + axe-core a11y 检测 + 视觉回归快照对比
- **RCA 失败根因自动归因**：11 类根因分类 + fix_suggestion 注入下一轮 feedback
- **崩溃恢复 / 断点续跑**：checkpoint + resume_orchestrated + infra_failure 优雅暂停/恢复
- **驾驭层六件套**：强制验证 / 循环检测 / 上下文压缩 / 人工审批 / 子 Agent / 可观测性
- **MCP Server + RAG**：DeepAgents 包成 MCP Server + Chroma 向量库
- **Console 桌面壳**：Tauri(Rust) + Vite+React+TS，对话/计划卡/文件树/审查 git diff/浏览器真 Chromium/终端真 pty/命令面板/工厂面板

### 2.3 目标用户
需要 AI 自主完成开发任务（给方向 → 自行产出 → 自行修复 → 达标）的开发者；希望自己跑 24h 自治 AI 代码工厂的团队。用户把自己的项目导入 `~/projects/<名>`，agent 在沙盒对应目录干活。

## 三、技术架构

### 3.1 技术栈
- **后端 orchestration-api**：Python 3.12+ / FastAPI 0.124 / uvicorn / httpx / websockets
- **驾驭层**：LangGraph 1.2.6（原生 checkpoint 支撑崩溃恢复 + 审批中断）+ langchain-openai 1.3.3 + langchain-core 1.4.8 + langgraph-checkpoint-sqlite
- **执行层**：OpenHands SDK 1.8.0（Docker 沙盒 Worker :8000）+ sandbox_verify/sandbox_deliver
- **模型代理**：LiteLLM[proxy] 1.84.1（:4000，architect/coder 路由 + 降级）
- **模型**：exo 集群（http://100.64.201.37:52415，OpenAI 兼容）→ GLM-5.2（编排者/架构师，主 Agent）+ Kimi-K2.7-Code（执行者/码农，子 Agent），各 4 分片张量并行
- **RAG**：ChromaDB ≥1.5 + sentence-transformers（all-MiniLM-L6-v2，fallback MockEmbedding）
- **搜索**：自托管 SearXNG（Docker :8080，经宿主 Clash 出站）
- **Console 前端**：Vite 5 + React 18 + TypeScript 5.6 + @tauri-apps/api 2 + xterm
- **桌面壳**：Tauri v2（Rust，console/src-tauri，portable-pty 终端 + 子 webview 浏览器）
- **IDE 扩展**：TypeScript（ide-extension/，IDE 控制面工具 + 环境即代码）

### 3.2 架构说明
```
Tauri 桌面壳(console/src-tauri, Rust)  ┐  原生选文件夹/窗口/嵌入式浏览器/终端
  Console(Vite+React+TS :5273) ────────┤  对话/计划卡/文件树/审查/终端/浏览器/用量
  orchestration-api(FastAPI :8011) ─────┘  会话/任务/WS 事件流/项目模型(~/projects)
    驾驭层 src/driving/(LangGraph): 多Agent监督编排 + 强制验证/循环检测/审批/压缩/崩溃恢复
    执行 src/executor/: OpenHands 沙盒 Worker(:8000) + 沙盒 verify/deliver
      → LiteLLM(:4000) 或直连 → exo 集群 → GLM-5.2 / Kimi-K2.7-Code
      内建工具: web_search(SearXNG) · MCP 注册表 · RAG
```
**项目模型**：flipped 是工具本体；用户把自己的项目导入 `~/projects/<名>`(host)↔ `/projects/<名>`(沙盒,bind mount)，agent 在沙盒对应目录干活。默认无活动项目。访问 exo 的 Python 进程须 `export NO_PROXY=100.64.201.37,...`（本机 Clash 代理会劫持成 502，D5）。

### 3.3 核心依赖
- litellm[proxy]==1.84.1、langgraph==1.2.6、langgraph-checkpoint-sqlite==3.1.0、langchain-openai==1.3.3、langchain-core==1.4.8
- fastapi==0.124.4、uvicorn[standard]>=0.30.0、httpx==0.28.1、websockets==15.0.1
- openhands-ai==1.8.0、mcp、chromadb>=1.5
- 前端：react 18、vite 5、@tauri-apps/api 2、@xterm/xterm 5、vitest 2、@playwright/test 1.45

## 四、目录结构

```
flipped/
├── src/
│   ├── agent/loop.py              最小 agent loop（LangGraph ReAct，GLM via :4000）
│   ├── api/                       orchestration API（FastAPI :8011）
│   │   ├── main.py                API 装配（会话/任务/WS/MCP/项目上下文/终端/浏览器）
│   │   ├── factory.py             工厂 REST 端点（POST /factories 创建+后台运行）
│   │   ├── orchestrator_stream.py 透明实时 WS 事件流
│   │   ├── session.py / events.py / schemas.py / terminal.py / browser.py
│   │   ├── project_state.py / mcp_registry.py
│   ├── driving/                   驾驭层（LangGraph 多 Agent 监督）
│   │   ├── orchestrator.py        Supervisor GLM + Worker Kimi + Overseer GLM 监督
│   │   ├── factory_loop.py        工厂状态/任务调度/失败重试/崩溃恢复
│   │   ├── infinite_loop.py       无限迭代外层循环 + 演进
│   │   ├── task_proposer.py       自主任务生成器（GLM 不可用时确定性 fallback）
│   │   ├── parallel_verifier.py   双模型并行验证（D19）
│   │   ├── design_context.py / design_lint.py / a11y_lint.py / visual_regression.py
│   │   ├── rca.py                 失败根因自动归因（11 类）
│   │   ├── gold_memory.py         金记忆（语义检索复用 rag 向量）
│   │   ├── safety.py              命令白名单/黑名单/密钥扫描
│   │   ├── context_manager.py / model_router.py / observe.py / sidecar.py
│   │   ├── approval.py / ide_client.py / project_rules.py / repo_map.py
│   │   ├── stuck_detector.py / progress_notes.py / verify_detect.py
│   ├── executor/                  OpenHands 沙盒执行
│   │   ├── openhands_worker.py    RemoteWorkspace + 直连 exo
│   │   ├── sandbox_deliver.py     验收通过后沙盒内 git commit
│   │   └── sandbox_verify.py
│   ├── mcp_server/                MCP Server（5 tools）
│   ├── rag/                       向量库（embeddings/ingest/vector_store）
│   ├── tools/web_search.py        SearXNG 联网搜索
│   └── metrics/collector.py       性能可观测
├── console/                       Console 前端 + Tauri 桌面壳
│   ├── src/                       Vite+React+TS（Conversation/PlanCard/FactoryPanel/PtyTerminal...）
│   ├── src-tauri/                 Rust（backend.rs/browser.rs/terminal.rs/lib.rs/main.rs）
│   ├── e2e/                       Playwright E2E（console-smoke/console/factory-api/factory）
│   ├── package.json / vite.config.ts / playwright.config.ts / vitest.config.ts
├── ide-extension/                 IDE 控制面扩展（bridge/env/extension/risk，TS）
├── tests/                         50+ 测试文件（pytest，自主开发循环全覆盖）
├── data/                          SQLite 数据库（checkpoints/factory/gold_memory/orch_e2e...）+ axe.min.js
├── infra/
│   ├── litellm/config.yaml        LiteLLM 路由配置（architect→GLM / coder→Kimi + 降级）
│   ├── searxng/                   SearXNG Docker 编排
│   └── env-templates/             devcontainer.json + .mise.toml（环境即代码）
├── scripts/                       dev_up.sh/dev_down.sh/start_proxy.sh + verify_milestone_*.sh + e2e_*.py
├── shell/                         Windows 打包（build-windows.sh/apply_branding.py）
├── docs/                          autonomy-factory-plan / product-architecture / research-*
├── AGENTS.md                      自主开发总控提示词（System Prompt）
├── DECISIONS.md                   架构决策记录（D1-D19）
├── HANDOFF.md / PLAN.md / TEST_LOG.md / STATE.json
├── README.md / AI-Design-System-Prompt.md
├── .env.example / requirements.txt / pytest.ini
```

### 关键文件功能说明

| 路径 | 功能 |
|------|------|
| src/api/main.py | orchestration API 装配（:8011），会话/任务/WS/MCP/项目上下文/终端/浏览器 |
| src/api/factory.py | 工厂 REST 端点（创建/列表/恢复/暂停） |
| src/driving/orchestrator.py | 多 Agent 监督编排核心（Supervisor/Worker/Overseer，D15） |
| src/driving/factory_loop.py | 工厂任务调度 + 失败重试 + 崩溃恢复 |
| src/driving/infinite_loop.py | 无限迭代外层循环 + 目标演进 |
| src/driving/task_proposer.py | 自主任务生成（GLM + 三层确定性 fallback） |
| src/driving/parallel_verifier.py | 双模型并行验证（D19） |
| src/driving/safety.py | 命令白名单/黑名单/密钥扫描/审计 |
| src/driving/rca.py | 失败根因自动归因（11 类） |
| src/executor/openhands_worker.py | OpenHands 沙盒 Worker（RemoteWorkspace + 直连 exo） |
| src/agent/loop.py | 最小 LangGraph ReAct agent loop（web_search 工具） |
| src/mcp_server/server.py | MCP Server（5 tools，DeepAgents 长链路） |
| src/rag/vector_store.py | Chroma 向量库 |
| console/src-tauri/src/lib.rs | Tauri 桌面壳入口（自动拉起后端/菜单/托盘） |
| AGENTS.md | 自主开发总控提示词（先计划→验证靠运行→小步提交→状态外置） |
| STATE.json | 里程碑状态跟踪（M0-M88，D1-D19 决策，已知问题） |
| infra/litellm/config.yaml | LiteLLM 路由（architect→GLM / coder→Kimi + 降级） |
| pytest.ini | 测试配置（禁用 anyio 插件保持 asyncio.run 稳定） |

## 五、环境搭建

### 5.1 前置环境要求
- Python 3.12+ + uv（推荐）或 pip
- Node.js v24 + npm/pnpm
- Rust 工具链（Tauri 桌面壳）
- Docker（OpenHands 沙盒 + SearXNG）
- exo 集群在线（http://100.64.201.37:52415，需先在其 Web UI LAUNCH GLM-5.2 + Kimi-K2.7-Code 两个模型）
- git（已装）

### 5.2 依赖安装步骤
后端：
```bash
# 中国网络加 --index-url https://pypi.tuna.tsinghua.edu.cn/simple（D7）
uv pip install -r requirements.txt   # 或 pip install -r requirements.txt
```
Console 前端：
```bash
cd console && npm i
```
桌面壳：
```bash
cd console && cargo build   # Tauri Rust 依赖
```

### 5.3 环境变量配置
变量名（详见 .env.example，`.env` 已在 .gitignore，绝不入库 — AGENTS.md §7）：
- EXO_API_KEY
- LITELLM_MASTER_KEY
- LITELLM_BASE_URL
- LITELLM_URL
- OPENHANDS_AGENT_HOST
- OPENHANDS_MODEL
- OPENHANDS_BASE_URL
- FLIPPED_MODEL_BASE_URL
- FLIPPED_ARCHITECT_MODEL
- FLIPPED_CODER_MODEL
- FLIPPED_MOCK_WORKER
- FLIPPED_CHECKPOINT_DB
- FLIPPED_SESSION_STORE_PATH
- FLIPPED_USE_PARALLEL_VERIFIER
- FLIPPED_AUTO_PROPOSER
- FLIPPED_DESIGN_SCORE_THRESHOLD
- FLIPPED_MAX_CONTINUATIONS
- VITE_API_BASE_URL（前端构建时注入）
- RAG_DB_DIR
- RAG_EMBEDDING_MODEL
- NO_PROXY（必须含 100.64.201.37,localhost,127.0.0.1,::1，防 Clash 劫持，D5）

## 六、启动与运行

### 6.1 开发模式启动
后端 orchestration-api（:8011）—— exo 集群需先 LAUNCH 两模型：
```bash
cp .env.example .env   # 填 EXO_API_KEY 等
PYTHONPATH=src .venv/bin/python -m uvicorn api.main:app --host 127.0.0.1 --port 8011
# (可选) OpenHands agent-server 沙盒(:8000) + SearXNG(:8080)
# (可选) LiteLLM 代理(:4000)：bash scripts/start_proxy.sh
```
Console（:5273）：
```bash
cd console && npm i && npm run dev
```
桌面壳（原生选文件夹等，后端+Console 起后）：
```bash
cd console && cargo tauri dev
```
一键脚本：`bash scripts/dev_up.sh`（起后端）/ `bash scripts/dev_down.sh`（停）。

### 6.2 生产构建
- 后端：Python 服务（可 python-build-standalone + uv 打包）
- Console 前端：`cd console && npm run build`（tsc -b && vite build）
- 桌面壳：`cd console && cargo tauri build`（产出 flipped.app + .dmg，M8.T4 已验证）
- Windows release：GitHub Actions windows-latest 云构建（D17，shell/build-windows.sh）

### 6.3 部署方式
桌面应用分发：Tauri 打包三平台（macOS .app/.dmg、Windows、Linux）。CI 通过 `.github/workflows/build.yml` + `release-windows.yml` 构建。SearXNG 走 Docker：`docker compose -f infra/searxng/docker-compose.yml up -d`。项目本身作为工具本体运行，用户项目导入 `~/projects/`。

## 七、主要接口说明
所有 API 前缀 `/api/v1`：
- **健康检查**：`GET /api/v1/health`（探测 LiteLLM proxy /models 可达性）
- **性能指标**：`GET /api/v1/metrics`（token 用量/性能快照）
- **会话/任务**：会话管理 + 任务派发（Supervisor→Worker→Overseer 循环）
- **WS 事件流**：`/api/v1/...` 实时推送 Supervisor/Worker/Overseer/Verify 每步事件（F2 去黑盒）
- **WS 终端**：`/api/v1/terminal`（真实 pty，作用域=活动项目根）
- **MCP 服务器**：`GET /api/v1/mcp/servers`、`POST /api/v1/mcp/servers/{name}/toggle`
- **项目上下文**：`GET /api/v1/project/context`（活动项目 + git 分支）
- **工厂**（factory_router）：`POST /factories` 创建+后台运行、`GET /factories` 列表、`GET /factories/{id}` 摘要、`GET /factories/{id}/detail` 完整状态、`POST /factories/{id}/resume` 恢复、`POST /factories/{id}/pause` 暂停
- **自主模式**：`mode=auto` 一键启动完整循环（F3，自动探测验证命令）

## 八、已知问题与注意事项
- **exo 集群访问**：Python/httpx 客户端必须 `export NO_PROXY` 含 100.64.201.37，否则被本机 Clash(:7890) 劫持成 502（D5）；curl/Node fetch 不受影响
- **LiteLLM proxy :4000**：曾因 Postgres/prisma 初始化阻塞（ISSUE-5），已通过 `FLIPPED_MODEL_BASE_URL` 直连 exo 绕过；proxy 修复后作可选前置
- **Roo Code 已停服**（ISSUE-2）：M2 基座改用 Cline（D4）
- **exo 4 台 RDMA 起不来**（ISSUE-3）：退回 2 台，用配法 B(2+2) 规避（GLM=studio04+02，Kimi=studio03+01）
- **F8 端到端真机**：需在 exo 集群 LAUNCH 两模型后跑真实项目全循环验证（基础设施侧，非代码；当前以注入测试兜底）
- **桌面原生化余项**：Tauri 嵌入式可交互浏览器 / 终端接面板 / Rust sidecar 拉起后端 / 签名打包（M8.T1-T4 已完成主体）
- **测试**：后端 `PYTHONPATH=src .venv/bin/python -m pytest -q`（README 基线 205 passed，STATE.json 跟踪至 M88，测试数持续增长至 900+）；前端 `cd console && npx tsc --noEmit && npm run build`；E2E `npx playwright test`（console-smoke 9 passed）
- **自主开发原则**（AGENTS.md）：先计划后动手 / 验证靠运行不靠看起来对 / 小步快跑 / 状态外置 / 诚实报告 / 遇错即工程化
- **安全**：沙箱内自由跑，沙箱外要审批（git push/合并主干/花钱 API/密钥操作需人工审批）；密钥一律走环境变量，绝不写进代码/日志/提交

## 九、与其他项目的关系
- **与 ToIV / BIM**：flipped 是 AI 自动化开发工厂，可作为 ToIV / BIM 这类项目的自主开发工具链——给一个开发方向，系统自行拆解写码跑测修错循环直到验收通过并提交。flipped 是"造工具的工具"，ToIV/BIM 是被开发的业务平台。
- **与 AICG-DownLoader**：flipped 可作为 AICG-DownLoader 这类 Rust 项目的自主开发工具链；反之 AICG-DownLoader 下载的模型（GLM/Kimi 经 exo）是 flipped 运行所依赖的本地模型来源之一。
- **模型关系**：flipped 编排者 GLM-5.2 + 执行者 Kimi-K2.7-Code 经 exo 集群 + LiteLLM 提供；与 ToIV 的 LM Studio(qwen) 是不同模型栈。
