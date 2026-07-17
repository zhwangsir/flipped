# flipped — 本地模型驱动的 AI 自主开发工厂

> 给一个目标，它自己**拆解 → 写码 → 跑测 → 修错 → 循环直到验收通过 → 提交成果**。
> 全程本地运行、数据不出机器、双模型协作、多 Agent 监督驾驭。

---

## ✨ 核心特色

### 🧠 双模型原生协作，而非"一个模型打天下"
- **GLM-5.2（编排者 / 架构师）** — 1M 长上下文，负责需求拆解、全局调度、方向把控
- **Kimi K2.7-Code（执行者 / 码农）** — MCP 工具调用能力拉满，负责沙盒内改代码跑测
- 经 **LiteLLM Proxy** 统一路由，支持降级、换载、负载均衡
- Apple Silicon **MLX 原生加速**，2TB 内存双模型常驻零换载

### 🔁 真正的自主开发循环（F1–F10）
不是"生成一段代码"——是**端到端把活干完**：

| | 能力 | 说明 |
|---|---|---|
| **F1** | 真实自我验证 | 自动探测项目怎么测（pytest/npm test/cargo…），沙盒内跑真测判定 |
| **F2** | 透明实时循环 | Supervisor/Worker/Overseer/Verify 每步 WebSocket 推送上屏 |
| **F3** | 一等自主模式 | `mode=auto` 一键启动，自动探测验证命令，零手配 |
| **F4** | 实时计划清单 | 子任务聚成带状态清单钉对话流顶（✓/⟳/↻/✗） |
| **F5** | 仓库记忆 | 项目结构地图（技术栈/目录布局）喂给 Supervisor |
| **F6** | 项目规则 | 自动读取 AGENTS.md/.cursorrules/CLAUDE.md 并遵守 |
| **F7** | 交付步 | 验收通过后沙盒内自动 git commit（注入安全约束） |
| **F9** | 并行看板 | 多自主线程运行状态实时总览 |
| **F10** | 用量/预算感知 | 顶栏本地模型 token 用量芯片 |

### 🛡️ 多 Agent 驾驭层（60+ 模块，工程化而非"靠模型自觉"）
- **强制验证节点** — Agent 说"完成"不算数，必须跑通验收脚本
- **循环检测 / 死循环熔断** — 同一动作重复 ≥3 次自动中断重新规划
- **人工审批断点** — 高风险动作前暂停等确认（沙箱内自由跑，沙箱外要审批）
- **上下文压缩** — 接近窗口上限自动总结落盘，1M 上下文也不崩
- **崩溃恢复 / Checkpoint** — 断了电、崩了进程，从断点续跑
- **质量分级 / 失败知识库 / RCA 根因分析** — 越用越聪明

### 🎨 Codex 级 UI/UX（React + Tauri 桌面壳）
- **三栏布局** — 侧栏（项目/对话/并行看板）· 中间（对话+计划卡）· 右侧（文件树 / 审查 / 终端 / 浏览器）
- **命令面板**（⌘K）— 搜聊天、切会话、开面板、切主题，一键直达
- **真终端**（xterm.js ↔ WebSocket pty）— 沙盒内真实 shell，主题随全局切换
- **真浏览器**（Playwright / Chromium）— 实时预览 + 选中页面元素追踪给 Agent
- **审查视图** — 工作区真实 git diff，Codex 配色
- **插件 / MCP 生态** — 标准 MCP 协议，SearXNG / RAG / Git 开箱即用
- **移动端适配** — 底部 tabbar + 抽屉式侧栏/面板，手机也能用
- **可访问性** — axe WCAG 2 A/AA 零违规，全键盘操作，ARIA 语义完整

### ✅ 质量保证（用数字说话）
- **后端**：1019 个 pytest 单测 / 集成测
- **前端**：45 个 vitest 单测
- **E2E**：79 个 Playwright 用例（布局 / 面板 / 移动端 / a11y / 工厂 / 控制台错误）
- **a11y**：axe 扫描 8 场景全部零违规（浅/深色主题 · 主壳/设置/命令面板/工厂/移动端）
- **构建**：Vite build + Tauri + Windows 发布流水线 + GitHub Actions CI

### 🔌 开放架构
- **MCP Server** — 标准 Model Context Protocol，外部工具即插即用
- **RAG 知识库** — Chroma 向量检索本地文档
- **IDE 扩展** — VS Code 桥接层（ide-extension/）
- **自主进化** — Self-Improving Loop / Skill 进化系统 / Gold Memory 黄金记忆

---

## 🏗️ 架构

```
┌─────────────────────────────────────────────────────────────┐
│  Tauri 桌面壳 (Rust)    原生选文件夹 / 窗口 / 系统集成       │
│  ┌───────────────────────────────────────────────────────┐  │
│  │  Console (Vite + React + TS)                         │  │
│  │  对话 · 计划卡 · 文件树 · 审查 · 终端 · 浏览器 · 用量  │  │
│  └──────────────┬────────────────────────────────────────┘  │
└─────────────────┼───────────────────────────────────────────┘
                  │ WebSocket / REST
┌─────────────────▼───────────────────────────────────────────┐
│  orchestration-api (FastAPI :8011)                          │
│  会话 · 任务 · 事件流 · 项目模型 (~/projects)               │
│  ┌───────────────────────────────────────────────────────┐  │
│  │  驾驭层 src/driving/ (60+ 模块)                        │  │
│  │  Supervisor · Worker · Overseer · Verify · 循环检测    │  │
│  │  审批 · 压缩 · 崩溃恢复 · 质量分级 · 技能进化 · RAG    │  │
│  └───────────────────┬───────────────────────────────────┘  │
│                      │                                      │
│  ┌──────────────────▼────────────────┐  ┌───────────────┐  │
│  │  OpenHands 沙盒 Worker (:8000)    │  │  MCP Server   │  │
│  │  sandbox_verify · sandbox_deliver │  │  web_search   │  │
│  └──────────────────┬────────────────┘  │  RAG / Git    │  │
└─────────────────────┼───────────────────┴───────────────┴──┘
                      │
         LiteLLM Proxy (:4000) ──→ exo 集群 (MLX)
                      │
         ┌────────────┴────────────┐
         ▼                         ▼
    GLM-5.2 (architect)       Kimi-K2.7-Code (coder)
    编排者 / 监督              执行者 / 码农
```

**项目模型**：flipped 是工具本体；用户把自己的项目导入 `~/projects/<名>`（host）↔ `/projects/<名>`（沙盒 bind mount），Agent 在沙盒对应目录干活。

---

## 🚀 快速开始

```bash
# 1) 克隆
git clone https://github.com/zhwangsir/flipped.git
cd flipped

# 2) 后端 orchestration-api (:8011)
cp .env.example .env   # 填 EXO_API_KEY 等
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
PYTHONPATH=src uvicorn api.main:app --host 127.0.0.1 --port 8011

# 3) Console (:5273)
cd console && npm install && npm run dev

# 4) 桌面壳（原生选文件夹等，可选）
cd console && cargo tauri dev

# 可选：OpenHands agent-server 沙盒(:8000) + SearXNG(:8080)
./scripts/dev_up.sh
```

### 测试

```bash
# 后端
PYTHONPATH=src .venv/bin/python -m pytest -q     # 1019 passed

# 前端
cd console
npx tsc --noEmit     # 类型检查
npx vitest run       # 45 passed
npx playwright test  # 79 passed (E2E)
```

> ⚠️ 访问 exo 的 Python 进程须 `export NO_PROXY=100.64.201.37,...`（本机代理会劫持成 502）。

---

## 📋 当前状态

| 模块 | 状态 |
|---|---|
| 驾驭层六件套（验证/循环/审批/压缩/恢复/多Agent） | ✅ 完成 |
| 自主开发循环 F1–F10 | ✅ 完成 |
| Console UI（Codex 级三栏 + 命令面板 + 终端 + 浏览器 + 审查） | ✅ 完成 |
| MCP Server + RAG 知识库 | ✅ 完成 |
| Tauri 桌面壳基础版 | ✅ 完成 |
| 测试体系（pytest / vitest / Playwright / axe a11y） | ✅ 完成 |
| Self-Improving / Skill 进化 / Gold Memory | ✅ 完成 |
| Windows 发布流水线 | ✅ 完成 |
| 端到端真机全循环验证（需双模型同时加载） | ⏳ 待跑 |
| Tauri 嵌入式可交互浏览器 / Rust sidecar 拉起后端 | ⏳ 规划中 |

> 自主开发：本仓库由 AI Agent 按 [AGENTS.md](AGENTS.md) 流程推进（先计划 → 验证靠运行 → 小步提交 → 状态外置）。
> 进度见 [STATE.json](STATE.json)，决策记录见 [DECISIONS.md](DECISIONS.md)。

---

## 📚 更多文档

- [AGENTS.md](AGENTS.md) — 自主开发 Agent 总控提示词 / 工作循环 / 安全护栏
- [docs/autonomy-factory-plan.md](docs/autonomy-factory-plan.md) — 自主工厂路线图
- [docs/product-architecture.md](docs/product-architecture.md) — 产品架构详解
- [DECISIONS.md](DECISIONS.md) — 关键技术决策记录
- [TEST_LOG.md](TEST_LOG.md) — 测试证据流水
- [shell/BUILD.md](shell/BUILD.md) — 构建与发布指南

---

## 📄 License

MIT
