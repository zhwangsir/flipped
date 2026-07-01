# flipped · 本地模型驱动的 AI 开发工厂 — 总体方案与计划

> 产品定义、架构、现状(已完成/未完成)、分阶段路线。接管先读本文件 + `STATE.json` + `DECISIONS.md`。
> 方向依据 **D18**(重大转向,2026-07-01)。取代早期"VSCodium 桌面编辑器"方向(D10/D14/D17,已搁置)。
> 早期 Phase 1 脑(M0–M3 驾驭层)成果全部复用为下方"编排层"。

---

## 1. 产品定义

**flipped = 像 Claude Code / Codex 的、本地模型驱动的自主编码 agent 平台("AI 开发工厂")。**

- **默认接本地模型**:GLM-5.2(调度/架构)+ Kimi-K2.7-Code(执行),经 LiteLLM `:4000`。
- **AI 自主用工具在沙盒里干活**:Docker 隔离、可控、可回滚,不污染宿主。
- **内置浏览器**:AI 能导航/点击/填表/截图验证 web。
- **工具齐全 + MCP**:终端/文件/git/搜索 + MCP 生态扩展。
- **差异化(核心)= 多 Agent 监督**:不是单 agent,而是 Supervisor 调度 + 多 Worker 执行 + 专属 Overseer 监督效率与方向 —— 目标是做出**超过单 agent**的效果。
- **交互**:自研 flipped Console(Web,后续 Electron 桌面壳)。

---

## 2. 架构(五层)

```
┌───────────────────────────────────────────────────────────────┐
│  接口层  flipped Console(自研 Web UI → 后续 Electron 桌面壳)     │  ← 我们做
├───────────────────────────────────────────────────────────────┤
│  编排层(脑) LangGraph 多 Agent 监督                              │  ← 我们做(已有核心)
│    Supervisor(GLM 调度)· Worker(执行)· Overseer(GLM 监督)     │
│    + 强制验证 / 循环检测 / 人工审批 / 可观测 / checkpoint         │
├───────────────────────────────────────────────────────────────┤
│  执行层(身体) OpenHands V1(MIT)                                │  ← 复用开源
│    Docker 沙盒 · browser-use 浏览器 · 终端/文件/MCP 工具          │
│    agent-server(REST/WS)· Python SDK(Conversation/AgentBase)  │
├───────────────────────────────────────────────────────────────┤
│  能力层  MCP 生态(filesystem/git/fetch/playwright)+ SearXNG 搜索 │  ← 配置/复用
├───────────────────────────────────────────────────────────────┤
│  模型层  exo 集群(GLM-5.2 + Kimi-K2.7)→ LiteLLM :4000(OpenAI 兼容)│  ← 已就绪
└───────────────────────────────────────────────────────────────┘
```

**关键集成点**:编排层把每个子任务经 OpenHands SDK `Conversation(agent, workspace=DockerWorkspace, callbacks=…)` 派进独立沙盒执行,经 `conversation.state.events` / callbacks 让 Overseer 实时监督;Console 经后端 orchestration API(WS 事件流)实时呈现。

---

## 3. 现状总览

### ✅ 已完成

| 层 | 内容 | 证据 |
|---|---|---|
| 模型层 | exo(GLM-5.2-fp8 + Kimi-K2.7-Code)→ LiteLLM `:4000`,工具调用实测全通 | M0 · 活体探针 |
| 基座选型 | OpenHands 选定(7 候选一手横评:Cline/Goose/Continue/Tabby/SWE-agent/bolt.diy/Devika) | D18 · 调研 |
| 执行层 PoC | Kimi 经 :4000 驱动 OpenHands V1 SDK(FileEditor+Terminal)在工作区**真写文件+跑通** | `oh_poc.py` |
| 执行层 运行 | OpenHands Agent Canvas Web 控制台本地跑通(修复 Docker VM 磁盘满 → agent-server) | 容器 18000/8000 就绪 |
| 编排层(脑) | `orchestrator.py`(Supervisor/Worker/Overseer,`function_calling`)+ 强制验证/循环检测/熔断 `sidecar.py` + 人工审批 `approval.py` + 可观测 `observe.py`,单测+e2e 全绿 | verify_milestone_3 |
| 接口层 外壳 | flipped Console v2(Vite+React+TS):活动栏/顶栏/会话+资源/多 Agent 对话流/语法高亮编辑器/6 Tab 上下文/三模式输入/状态栏 | `console/`,构建绿 |
| 能力层 | SearXNG 联网搜索(Docker,JSON,经宿主 Clash 出站) | M1 |
| 环境模板 | devcontainer + mise 多语言模板 | infra/env-templates |

### ⏳ 未完成

| 优先级 | 任务 | 说明 |
|---|---|---|
| P0 | **UI 打磨(去 AI 感)** | 减渐变/发光/圆角堆砌 → 更克制、编辑器化、精致排版;对齐真产品级(Linear/Zed/Codex 的"克制的高级") |
| P0 | **Console 接后端** | 建 orchestration API(FastAPI + WS),把真实 会话/工具调用/沙盒/编辑器/终端/浏览器/diff 事件流进 UI,替换 mock |
| P0 | **Worker 迁移** | orchestrator 的 Worker 从 "cline CLI" 切到 "OpenHands SDK `Conversation(DockerWorkspace)`";Overseer 读 `state.events` 监督 |
| P0 | **本地模型 tool-calling 加固** | LiteLLM 注册 GLM/Kimi 能力(`supports_function_calling`)、修 cost warning,确保 OpenHands 多轮 tool-use 稳 |
| P1 | **内置浏览器打通** | OpenHands BrowserToolSet(playwright)在沙盒真跑;UI 浏览器 Tab 显示真实截图/DOM |
| P1 | **MCP 生态接入** | filesystem/git/fetch/searxng 等配到 OpenHands;UI MCP Tab 管理开关 |
| P1 | **沙盒管理** | 每会话独立 DockerWorkspace 生命周期/资源/回滚;Docker Desktop 磁盘扩容(当前 20G 偏小) |
| P1 | **多 Worker 并行 + 监督面板** | Overseer 实时监督多个并行 Worker 的效率/方向,UI 呈现 |
| P2 | **桌面打包** | Electron 壳包 Console + 本地起 OpenHands + sidecar(python-build-standalone);三平台(D17 云构建思路可复用) |
| P2 | **硬化** | 崩溃恢复(LangGraph checkpoint)、安全(审批/沙盒逃逸防护)、审计观测、性能 |

---

## 4. 分阶段路线

### Phase A · 地基(≈90% 完成)
模型层 + OpenHands 基座验证 + 编排核心 + Console 外壳。→ **基本完成**,余:UI 打磨、tool-calling 加固。
- verify:PoC 已证本地模型驱动 OpenHands 沙盒工具闭环 ✓

### Phase B · 打通 MVP(下一步重点)
让 Console 从"好看的壳"变成"真能干活的平台"。
1. `orchestration-api`(FastAPI):会话 CRUD、派单给 OpenHands、WS 广播事件 → verify:curl 建会话 + WS 收到事件
2. Worker 迁移到 OpenHands SDK(DockerWorkspace)→ verify:一个真任务在沙盒跑通并回传轨迹
3. Console 接 WS:对话流/工具卡/编辑器/终端/浏览器/diff 实时更新 → verify:UI 里看到真实任务执行
4. UI 打磨去 AI 感 → verify:截图对齐克制高级基调
5. tool-calling 加固 + cost 修复 → verify:多轮 tool-use 稳定不 fallback
- **里程碑**:在 Console 里给一个真实编码任务,GLM 调度→Kimi 在沙盒执行→Overseer 监督→验证,全程 UI 实时可见。

### Phase C · 差异化
6. Overseer 实时监督面板(效率/方向/干预)。
7. 多 Worker 并行编排。
8. MCP 生态接入 + UI 管理。
9. 内置浏览器端到端(真截图回 UI)。
10. 沙盒生命周期管理 + 磁盘策略。
- **里程碑**:多 Agent 协作 + 监督在真实多文件任务上跑出"超过单 agent"的可观测优势。

### Phase D · 产品化
11. Electron 桌面壳(Win/mac/Linux)。
12. 硬化:恢复/安全/审计/性能。
13. 品牌 + 分发。
- **里程碑**:可分发的 flipped 桌面 App。

---

## 5. Phase B 详细实施计划(当前执行)

**目标**:在 Console 内完成一次真实任务:Supervisor(GLM)调度 → Worker(Kimi 经 OpenHands SDK 在 Docker 沙盒执行) → Overseer(GLM)读 events 监督 → 强制验证通过 → Console WS 实时可见。

### B1 · orchestration-api 骨架

**输入**:现有 `src/agent/orchestrator.py`、`src/driving/sidecar.py`、Console v2 前端事件 mock。
**输出**:`src/api/main.py`(FastAPI) + `src/api/session.py` + `src/api/events.py`。

步骤:
1. 新建 `src/api/` 包;FastAPI 应用挂载于 `/api/v1`。
2. 定义统一事件模型 `src/api/schemas.py`:
   - `EventType`: `message`, `tool_call`, `tool_result`, `file_change`, `terminal`, `browser`, `status`, `checkpoint`, `approval_request`, `approval_result`, `error`。
   - `Event`: id, session_id, type, agent, payload, parent_id, created_at。
3. 内存会话仓库 `src/api/session.py`:
   - `POST /api/v1/sessions` 创建会话;返回 `{id, status, created_at}`。
   - `GET /api/v1/sessions/{session_id}` 查状态。
   - `POST /api/v1/sessions/{session_id}/tasks` 接收 `{description, context?}` 创建任务。
4. WebSocket `WS /api/v1/sessions/{session_id}/events`:
   - 连接后加入该会话的广播通道;后端产生事件时主动 push。
   - 断线重连:客户端可带 `last_event_id` query, 服务端回放最近 N 条(内存即可,后续切 Redis)。
5. 路由健康检查 `/api/v1/health`, 返回模型层可达状态(调 `/v1/models`)。
6. 错误处理中间件,统一 JSON error schema。
7. 验收脚本 `scripts/verify_b1.sh`:
   - curl 建会话拿到 session_id;
   - curl 派任务;
   - 用 `websocat`(或 Python)连 WS, 30 秒内收到至少 `status` 与 `message` 事件;
   - 退出码 0。

### B2 · Worker 迁移到 OpenHands SDK

**输入**:现有 `orchestrator.py` 里 Worker 调用 cline CLI 的占位/旧实现;PoC `oh_poc.py`。
**输出**:新执行器 `src/executor/openhands_worker.py`, orchestrator 集成它。

步骤:
1. 确认 `.venv` 已安装锁定的 `openhands-ai==1.0.0rcN`;没有则安装并写入 `requirements.txt`。
2. 封装 `OpenHandsWorker` 类:
   - 初始化参数: `task_id`, `workspace_name`, `llm_config` 指向 `coder`(:4000, model=coder)。
   - 使用 `DockerWorkspace` 作为 workspace, 镜像用 OpenHands 默认 runtime(arm64 适配)。
   - 用 `Conversation(agent=CodeActAgent, workspace=workspace, initial_user_action=…)` 启动。
   - 注册 callbacks: 把 agent message / tool call / tool result / file edit / terminal output 转成 B1 的 `Event` push 到会话事件总线。
   - 暴露 `run()` 返回最终 `state` 与事件列表;`stop()` 用于中断。
3. 在 `orchestrator.py` 中把 `WorkerNode` 的执行动作改为:
   - 接收 Supervisor 的 `TaskAssignment`;
   - 实例化 `OpenHandsWorker`;
   - 在独立线程/进程跑 `worker.run()`,避免阻塞 LangGraph 主循环;
   - 通过 queue 把 events 喂给 Orchestrator 继续流转。
4. Overseer Node 改造:
   - 读 Worker 产生的 events(而不是旧 cline 输出);
   - 对方向/效率打分;触发干预或审批。
5. 强制验证节点复用 `sidecar.py`, 改为检查 Worker 返回的 `state` 中文件/命令输出是否符合预期。
6. 配置 LiteLLM 中的 `coder`/`architect` 模型,补充 `supports_function_calling: true` 与 pricing,消除 cost warning。
7. 验收脚本 `scripts/verify_b2.sh`:
   - 启动 orchestration-api;
   - 派任务:"在沙盒 `/workspace` 下创建 `hello.py` 含 `def add(a,b): return a+b`, 并运行 `python -m pytest hello_test.py`";
   - 断言 WS 收到 `file_change` + `terminal` 事件;
   - 断言验证节点返回 PASS;
   - 退出码 0。

### B3 · Console 接后端真实数据流

**输入**:Console v2 前端 mock 数据与组件。
**输出**:真实 WS 数据驱动的 UI。

步骤:
1. 新建 `console/src/hooks/useSession.ts`: 管理 session 创建、任务派发、WS 连接、断线重连、事件回放。
2. 新建 `console/src/hooks/useEvents.ts`: 按类型分发事件到各 Tab 状态:
   - `message` → AgentMessage 流;
   - `tool_call`/`tool_result` → 工具卡;
   - `file_change` → 编辑器文件树 + diff;
   - `terminal` → Terminal Tab 滚动输出;
   - `browser` → Browser Tab 截图/DOM(占位,先显示 base64 图);
   - `status` → 状态栏与顶部进度;
   - `approval_request` → 审批弹窗。
3. 保留当前 v2 布局,将 mock 数据源替换为 hooks。
4. 简单错误/加载状态: 连接失败提示、重连 spinner。
5. 验收: 在 Console 内触发 B2 任务,肉眼可见真实事件按序进入 UI;录屏或截图写进 `TEST_LOG.md`。

### B4 · tool-calling 加固 + cost warning 修复

步骤:
1. `infra/litellm/config.yaml` 显式注册:
   ```yaml
   model_list:
     - model_name: architect
       litellm_params:
         model: openai/GLM-5.2-xxx
         api_base: http://100.64.201.37:52415/v1
         supports_function_calling: true
       model_info:
         max_tokens: 8192
         input_cost_per_token: 0
         output_cost_per_token: 0
   ```
2. 相同方式注册 `coder`。
3. 运行 3 个多轮 tool-use 任务(文件/终端/搜索), 确认无 `cost warning`, 无 `model doesn't support function calling` fallback。
4. 验收脚本 `scripts/verify_b4.sh` 跑断言。

### B5 · UI 去 AI 感打磨

步骤:
1. 设计 token 调整(在 `console/src/index.css`):
   - 主色 `#4F46E5` 降饱和;发光 shadow 移除或仅 focus 用 1px ring;
   - 卡片圆角统一 `6px`(`rounded-md`);
   - 背景用 `zinc` 灰阶, 强调色仅用于 agent 角色/状态语义;
   - 字号层级: 标题 16/14/13/12, 行高紧凑 1.35。
2. 逐个组件审查: Sidebar/Header/Chat/Editor/Tabs/StatusBar, 移除装饰性渐变、过度阴影、无意义图标。
3. 参考基调: Linear/Zed/Codex 截图(可做一次 web 搜索找最新)。
4. 验收: 截图前后对比, 写进 `TEST_LOG.md`;主观评审由用户最终确认。

---

## 6. UI 设计方向修正(去 AI 感)

当前 v2 反馈:「AI 感太重」。打磨方向:
- **减少发光/渐变**:brand mark 与主按钮去 glow,改扁平或极弱阴影;强调色只在真正的交互焦点用。
- **收敛圆角**:统一更小圆角(6–8px),少用大圆角卡片堆叠。
- **克制配色**:靛蓝主色降饱和、少铺面积;多用中性灰阶做层次,颜色只承载语义(角色/状态/diff)。
- **编辑器化排版**:更紧的行高与密度、更强的字号层级对比、tabular 数字;向 Zed/Linear/Codex 的"工具感克制"靠。
- **去装饰**:移除非功能性视觉噪声;每个视觉元素都要有信息职责。
- 参考基调:Linear(克制)、Zed(工具感)、Codex(留白)。目标是「像成熟产品截图」,而非「AI 生成的 demo」。

---

## 7. 风险与开放项

- **OpenHands V1 仍 `1.0.0-rc`**:API 可能变;锁版本、封装适配层隔离。
- **本地模型 tool-calling 摩擦**:GLM-5.2-fp8 已验证缓解;需在 LiteLLM 注册能力并实测多轮稳定。
- **macOS ARM 沙盒**:agent-server 需 Docker Desktop 足够磁盘(已踩磁盘满坑);arm64 镜像/socket 性能需持续实测。
- **`host.docker.internal` 端点**:容器内访问宿主 `:4000` 必须用它,不能 localhost。
- **Docker 磁盘**:当前 VM 20G 偏小,建议扩到 80–120G。
- **需用户提供**:桌面签名证书(Apple / Windows Authenticode)——产品化阶段。
