# flipped — 本地模型驱动的 AI 自主开发工厂

> 给一个目标，它自己**拆解 → 写码 → 跑测 → 修错 → 循环直到验收通过 → 提交成果**。
> 全程本地运行、数据不出机器、单模型同源驱动、多 Agent 监督驾驭。

---

## 核心特色

### 单模型同源驱动，多 Agent 分工驾驭
- **GLM-5.2-fp8（mlx-community/GLM-5.2-fp8）** — 编排与执行同源：需求拆解、全局调度、沙盒内改代码跑测皆由它承担（Kimi-K2.7-Code 已下线）
- 经 **LiteLLM Proxy（:4000）** 统一路由，architect/coder 别名抽象，换回双模型只需改 env
- 推理经 **exo 集群**（4× Mac Studio M3 Ultra 512GB，MLX RDMA，共 2TB 统一内存）
- 关键参数：`temperature=0` + `reasoning_effort="none"`（EXO 1.0.71+ 唯一真正关闭 thinking 的开关，防 reasoning_content 抢占 content）
- 视觉能力暂不可用（exo 无视觉模型），带图对话自动降级纯文本

### 真正的自主开发循环（F1–F10）
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

### 多 Agent 驾驭层（60+ 模块，工程化而非"靠模型自觉"）
- **强制验证节点** — Agent 说"完成"不算数，必须跑通验收脚本
- **循环检测 / 死循环熔断** — 同一动作重复 ≥3 次自动中断重新规划
- **Worker 命令纪律 + 重复错误早停** — 单 tool call、&& 链式写验、同形错误 ≥3 次远程 pause 早停（M202）
- **人工审批断点** — 高风险动作前暂停等确认（沙箱内自由跑，沙箱外要审批）
- **上下文压缩** — 接近窗口上限自动总结落盘
- **崩溃恢复 / Checkpoint** — 进程崩溃从断点续跑
- **质量分级 / 失败知识库 / RCA 根因分析** — 越用越聪明

### Codex 级 UI/UX（React + Tauri 桌面壳）
- **三栏布局** — 侧栏（项目/对话/并行看板）· 中间（对话+计划卡）· 右侧（文件树 / 审查 / 终端 / 浏览器）
- **命令面板**（⌘K）— 搜聊天、切会话、开面板、切主题
- **真终端**（xterm.js ↔ WebSocket pty）、**真浏览器**（Playwright/Chromium）、**审查视图**（真实 git diff）
- **图标系统** — 全项目统一 lucide-react 单一线性风格（M203）
- **插件 / MCP 生态** — 标准 MCP 协议，SearXNG / RAG / Git 开箱即用
- **移动端适配** + **可访问性**（axe WCAG 2 A/AA 零违规）

### 质量保证（用数字说话）
- **后端**：2769+ pytest 全绿（15 skipped），覆盖率 86.68%
- **前端**：955 vitest 全绿，行覆盖 91.64%（tsc 0 错）
- **E2E**：79 Playwright 用例（布局 / 面板 / 移动端 / a11y / 工厂 / 控制台错误）
- **a11y**：axe 扫描 8 场景全部零违规
- **构建**：Vite build + Tauri + Windows 发布流水线 + GitHub Actions CI

### 视觉与视频资产管线（M204）
- 空态插图生成与集成（去水印 + 径向渐隐融入背景）
- **Remotion 产品演示片**：agent-browser 抓真实 UI 帧 → 6 场景 TransitionSeries，25.5s 1080p30（`promo/out/promo.mp4`）

---

## 架构

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
         LiteLLM Proxy (:4000) ──→ exo 集群 :52415 (MLX RDMA)
                      │
                      ▼
    GLM-5.2-fp8（单模型，architect/coder 同源）
    编排者 / 监督 / 执行者 / 码农
```

**项目模型**：flipped 是工具本体；用户项目导入 `~/projects/<名>`（host）↔ `/projects/<名>`（沙盒 bind mount），Agent 在沙盒对应目录干活。

---

## 快速开始

```bash
# 1) 克隆
git clone https://github.com/zhwangsir/flipped.git
cd flipped

# 2) 后端 orchestration-api (:8011)
cp .env.example .env   # 填 EXO_API_KEY / LITELLM_MASTER_KEY 等
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
PYTHONPATH=src uvicorn api.main:app --host 127.0.0.1 --port 8011

# 3) LiteLLM 代理 (:4000)
./scripts/start_proxy.sh

# 4) Console (:5273)
cd console && npm install && npm run dev

# 5) 桌面壳（可选）
cd console && cargo tauri dev

# 可选：OpenHands agent-server 沙盒(:8000) + SearXNG(:8888)
./scripts/dev_up.sh
```

### 测试

```bash
# 后端
PYTHONPATH=src .venv/bin/python -m pytest -q     # 2769+ passed, 15 skipped

# 前端
cd console
npx tsc --noEmit     # 类型检查
npx vitest run       # 955 passed
npx playwright test  # 79 passed (E2E)
```

> ⚠️ 访问 exo 的 Python 进程须设 `NO_PROXY` 包含 LAN 网段与集群主机名（本机代理会劫持成 502）。`scripts/start_proxy.sh` 已内置。

---

## 当前状态（2026-08-10）

**里程碑 M0 → M204 共 207 条**（其中 M201 failed：GLM 长程行为缺陷阻断 10-task E2E；M202 已落地缓解三件套）。

| 近期里程碑 | 内容 |
|---|---|
| M198 | registry 清仓收官（82 条 open 归零：resolved 47 / wontfix 35），exo VL 数据面修复 |
| M199/M200 | 单模型配置同步（脚本层 Kimi/旧主机名残留清仓）+ 真机 tool-calling 验证闭环 |
| M201 ❌ | 工厂 10-task E2E FAIL：GLM worker 写后追加验证命令被沙盒拒绝、温度 0 永不自愈 |
| M202 | GLM worker 命令纪律硬约束（单 tool call/&& 链式/过检即 finish）+ 迭代预算 5→8 + 重复错误早停（同形错误 ≥3 次远程 pause），契约测试 12/12 |
| M203 | Console 图标系统统一迁移 lucide-react（唯一图标源硬性规则） |
| M204 | 视觉+视频资产管线：empty-hero 空态插图 + Remotion 25.5s 产品演示片 |

| 模块 | 状态 |
|---|---|
| 驾驭层六件套（验证/循环/审批/压缩/恢复/多Agent） | ✅ 完成 |
| 自主开发循环 F1–F10 | ✅ 完成 |
| Console UI（三栏 + 命令面板 + 终端 + 浏览器 + 审查） | ✅ 完成 |
| MCP Server + RAG 知识库 | ✅ 完成 |
| Tauri 桌面壳基础版 / Windows 发布流水线 | ✅ 完成 |
| 测试体系（pytest / vitest / Playwright / axe a11y） | ✅ 完成 |
| Self-Improving / Skill 进化 / Gold Memory | ✅ 完成 |
| 端到端真机全循环验证（单模型 GLM-5.2-fp8） | ✅ 完成（F8 / PomodoroEdge / M156 / M198，证据见 TEST_LOG.md） |
| 工厂 10-task E2E（M202 实效复验） | ⏳ 进行中（M201 FAIL 缓解后重跑） |
| Tauri 嵌入式可交互浏览器 / Rust sidecar 拉起后端 | ⏳ 规划中 |

---

## 文档地图

| 文件 | 用途 |
|---|---|
| [AGENTS.md](AGENTS.md) | **集群操作记忆与决策记录**（17 台设备清单 / GPU 分配 / 凭据 / 易错点 / EXO 重启 playbook）——每次会话必读 |
| [STATE.json](STATE.json) | 里程碑状态机（M0→M204 全量记录、当前状态、known limitations） |
| [DECISIONS.md](DECISIONS.md) | 关键技术决策记录（D1–D16+） |
| [TEST_LOG.md](TEST_LOG.md) | 测试证据流水（按里程碑时序） |
| [设备说明.md](设备说明.md) | 集群设备详细说明 |
| [shell/BUILD.md](shell/BUILD.md) | 构建与发布指南 |

> 自主开发：本仓库由 AI Agent 按 AGENTS.md 流程推进（先计划 → 验证靠运行 → 小步提交 → 状态外置）。

---

## License

MIT
