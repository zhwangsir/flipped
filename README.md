# flipped

**AI 驱动的多平台桌面 IDE**（目标形态，D10）——类似 VSCode / IDEA / HBuilder，但整个 IDE 由 AI 底层驱动：每个任务都由**多 Agent 协作 + 专属监督 Agent**完成（D15），随项目内置多语言开发环境（D12）。接入本地 exo 集群的两个 MLX 模型：

| 角色 | 模型 | 经 |
|---|---|---|
| 编排者 / 监督（Supervisor + Overseer） | GLM-5.2（别名 `architect`） | LiteLLM(:4000) → exo 集群 |
| 执行者（Worker） | Kimi-K2.7-Code（别名 `coder`） | 同上 |

> 自主开发：本仓库由 AI agent 按 [AGENTS.md](AGENTS.md) 流程推进（先计划 → 验证靠运行 → 小步提交 → 状态外置）。决策见 [DECISIONS.md](DECISIONS.md)(D1–D16)，进度见 [STATE.json](STATE.json)，证据见 [TEST_LOG.md](TEST_LOG.md)，架构见 [docs/product-architecture.md](docs/product-architecture.md)。

## 架构（三层，D11–D14）

```
┌ 外壳 Shell（Phase 3）: Code-OSS fork 多平台桌面 IDE + Open VSX + 内建 Cline ┐
│  ┌ 脑 Brain（Phase 1 ✅）─────────────────────────────────────────────┐  │
│  │ 内建 Cline 派生 agent + IDE 控制面扩展(ide-extension/)              │  │
│  │ 驾驭层 sidecar(src/driving/, LangGraph): 多Agent监督编排           │  │
│  │   Supervisor(GLM) + Worker(Kimi via cline) + Overseer(GLM)         │  │
│  │   + 强制验证/循环检测/人工审批/上下文压缩, 全在 SqliteSaver         │  │
│  └────────────────────────────────────────────────────────────────────┘  │
│  随项目内置环境（Phase 2）: Dev Containers + mise (infra/env-templates/)   │
└────────────────────────────────────────────────────────────────────────────┘
        → LiteLLM(:4000) → exo 集群 → GLM-5.2 / Kimi-K2.7-Code        [M0]
        内建工具: web_search(SearXNG)                                  [M1]
```

## 已建成（自主验证，全部单测/e2e 通过）

- **M0 服务层**：LiteLLM 代理(:4000) 路由 architect/coder → exo；工具调用实测通过。
- **M1 工具链**：SearXNG 自托管 + `web_search` 工具 + LangGraph agent loop。
- **M2 编辑器接入**：Cline（CLI + VS Code 扩展）接 :4000，多文件改动端到端。
- **Phase 1 脑（驾驭层六件套 ✅）** `src/driving/`：
  - `observe.py` 可观测 · `sidecar.py` 强制验证+循环检测 · `approval.py` 人工审批 ·
    `orchestrator.py` **多Agent监督编排（Supervisor+Worker+Overseer，D15）** · 上下文压缩(Cline 原生)。
- **IDE 控制面扩展** `ide-extension/`(TS)：让 AI 驱动 IDE（任务/终端/设置/扩展/命令）+ 环境即代码工具（devcontainer/mise），高风险走审批。
- **Phase 2 环境模板** `infra/env-templates/`：多语言 Dev Container + mise。

## 如何运行

```bash
# 1) 起服务（exo 集群需先在其 Web UI LAUNCH 两个模型）
uv venv --python 3.11 .venv && uv pip install 'litellm[proxy]' 'langgraph' 'langchain-openai' 'langgraph-checkpoint-sqlite'
cp .env.example .env   # 填 EXO_API_KEY / LITELLM_MASTER_KEY
bash scripts/start_proxy.sh &                       # LiteLLM :4000
docker compose -f infra/searxng/docker-compose.yml --project-directory infra/searxng up -d   # SearXNG :8080
npm i -g cline && cline auth openai-compatible -b http://localhost:4000/v1 -m coder --data-dir .cline-data

# 2) 验收（每个里程碑一键复跑）
bash scripts/verify_milestone_0.sh   # 服务层
bash scripts/verify_milestone_1.sh   # 工具链
bash scripts/verify_milestone_2.sh   # 编辑器
bash scripts/verify_milestone_3.sh   # 驾驭层(六件套)
bash scripts/verify_phase2.sh        # 环境模板

# 3) 跑多Agent监督编排(GLM 调度 / Kimi 执行 / GLM 监督)
.venv/bin/python -m driving.orchestrator <cwd> "<目标>" python3 test.py
```

> ⚠️ 访问 exo 的 Python 进程须 `export NO_PROXY=100.64.201.37,...`（本机 Clash 代理会劫持成 502，D5）。

## 当前状态与剩余（诚实边界）

- ✅ **Phase 1 脑完整可用**（最难的 AI 核心），IDE 控制面 + Phase 2 模板就绪。
- ⏳ **需宿主/Docker/账号才能继续验证的部分**：IDE 控制面 agent↔扩展桥 + 运行时（需 VS Code 扩展宿主）；devcontainer 重建运行时（需 Docker Desktop）；**Phase 3 外壳 fork/签名/公证/分发（需用户 Apple 开发者证书与账号）**。
