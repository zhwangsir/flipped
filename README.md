# flipped

**本地模型驱动的 AI 自主开发工厂**(D18)——像 Claude Code / Codex 一样,给一个目标,系统自己**拆解 → 写码 → 跑测 → 修错 → 循环直到验收通过 → 提交成果**,全程可见、可控、可续跑。基于 OpenHands 沙盒执行 + 自研多 Agent 监督驾驭层,接入本地 exo 集群两个 MLX 模型。桌面壳为 Tauri(Rust)。

| 角色 | 模型 | 经 |
|---|---|---|
| 编排者 / 监督（Supervisor + Overseer） | GLM-5.2（别名 `architect`） | LiteLLM(:4000) 或直连 → exo 集群 |
| 执行者（Worker） | Kimi-K2.7-Code（别名 `coder`） | OpenHands 沙盒 → 同上 |

> 自主开发：本仓库由 AI agent 按 [AGENTS.md](AGENTS.md) 流程推进（先计划 → 验证靠运行 → 小步提交 → 状态外置）。进度见 [STATE.json](STATE.json)，自主循环路线图见 [docs/autonomy-factory-plan.md](docs/autonomy-factory-plan.md)，决策见 [DECISIONS.md](DECISIONS.md)。

## 自主开发循环（F1–F10，核心能力）

在 Console 选「**自主**」模式 + 给一个目标即启动完整循环。构成:

| | 能力 | 实现 |
|---|---|---|
| **F1** | 真实自我验证——探测项目怎么验证（pytest/npm test/cargo…）并在沙盒内跑真测判定 | `driving/verify_detect.py` · `executor/sandbox_verify.py` |
| **F2** | 透明实时循环——Supervisor/Worker/Overseer/Verify 每步实时推 WS 事件（去黑盒） | `api/orchestrator_stream.py` |
| **F3** | 一等自主模式——`mode=auto` 一键启动，自动探测验证命令，无需手配 | `api/main.py` `_select_runner` |
| **F4** | 实时计划清单——子任务聚成带状态清单（✓/⟳/↻/✗）钉对话流顶 | `PlanTracker` + `PlanCard.tsx` |
| **F5** | 仓库记忆——项目结构地图（技术栈/目录布局）喂 Supervisor | `driving/repo_map.py` |
| **F6** | 项目规则——读 AGENTS.md/.cursorrules/CLAUDE.md 等遵守项目约定 | `driving/project_rules.py` |
| **F7** | 交付步——验收通过后在沙盒内自动 `git commit`（注入安全） | `executor/sandbox_deliver.py` |
| **F9** | 并行线程状态板——多自主线程运行状态实时总览 | `Sidebar.tsx` |
| **F10** | 用量/预算感知——顶栏本地模型 token 用量芯片 | `TopBar.tsx` |

> **完整流程**:选自主模式+给目标 → 探测怎么验证 → 读项目规则+结构 → Supervisor 拆子任务(实时上屏) → Worker 沙盒执行(轨迹上屏) → Overseer 监督方向/效率 → 沙盒跑真测判定 → 循环直到验收 → 自动提交。带 checkpoint 崩溃恢复 / 死循环检测 / 熔断 / 高风险审批。

## 架构

```
Tauri 桌面壳(console/src-tauri, Rust)  ┐  原生选文件夹/窗口/(规划中)嵌入浏览器
  Console(Vite+React+TS :5273) ────────┤  对话/计划卡/文件树/审查/终端/浏览器/用量
  orchestration-api(FastAPI :8011) ─────┘  会话/任务/WS 事件流/项目模型(~/projects)
    驾驭层 src/driving/(LangGraph): 多Agent监督编排 + 强制验证/循环检测/审批/压缩/崩溃恢复
    执行 src/executor/: OpenHands 沙盒 Worker(:8000) + 沙盒 verify/deliver
      → LiteLLM(:4000) 或直连 → exo 集群 → GLM-5.2 / Kimi-K2.7-Code
      内建工具: web_search(SearXNG) · MCP 注册表 · RAG
```

**项目模型**:flipped 是工具本体;用户把自己的项目导入 `~/projects/<名>`(host)↔ `/projects/<名>`(沙盒,bind mount),agent 在沙盒对应目录干活。默认无活动项目。

## 已建成历史（自主验证，全部单测/e2e 通过）

- **M0 服务层** LiteLLM 路由 architect/coder → exo · **M1 工具链** SearXNG + web_search + agent loop · **M2 编辑器接入** Cline 多文件端到端。
- **Phase 1 脑（驾驭层六件套）** `src/driving/`:observe/sidecar(强制验证+循环检测)/approval(人工审批)/orchestrator(多Agent监督,D15)/上下文压缩/崩溃恢复。
- **Phase B MVP** OpenHands 执行 + orchestration-api + Console 真实数据流。**M4** MCP Server + RAG。**M5** 硬化(性能/路由降级/崩溃恢复/安全)。
- **Codex UI 对齐** Console 外壳/右侧功能(文件树/审查 git diff/浏览器真 Chromium/终端真 pty)/命令面板/设置/插件,均以真实能力为底。
- **自主开发循环 F1–F10**(见上)+ 独立 code-review 质量硬化。

## 如何运行

```bash
# 1) 后端 orchestration-api(:8011) —— exo 集群需先在其 Web UI LAUNCH 两个模型
cp .env.example .env   # 填 EXO_API_KEY 等
PYTHONPATH=src .venv/bin/python -m uvicorn api.main:app --host 127.0.0.1 --port 8011
# (可选)OpenHands agent-server 沙盒(:8000) + SearXNG(:8080)

# 2) Console(:5273，见 console/vite.config.ts)
cd console && npm i && npm run dev

# 3) 桌面壳(原生选文件夹等) —— 后端+Console 起后
cd console && cargo tauri dev

# 测试
PYTHONPATH=src .venv/bin/python -m pytest -q     # 后端(205 passed)
cd console && npx tsc --noEmit && npm run build   # 前端
```

> ⚠️ 访问 exo 的 Python 进程须 `export NO_PROXY=100.64.201.37,...`（本机 Clash 代理会劫持成 502，D5）。

## 当前状态与剩余（诚实边界）

- ✅ **自主开发循环 F1–F10 全部完成并验证**（后端 205 tests / 前端 tsc+build / 关键 UI 隔离 Playwright）。
- ⏳ **F8 端到端真机**:需在 exo 集群 LAUNCH GLM-5.2 + Kimi-K2.7-Code 两个模型后,跑一个真实项目全循环验证(基础设施侧,非代码;当前以注入测试兜底,已由 `~/projects/verify-cwd` 的 `.git` bind-mount 铁证 agent 工作目录正确)。
- ⏳ **桌面原生化余项**:Tauri 嵌入式可交互浏览器 / 终端接面板 / Rust sidecar 拉起后端 / 签名打包。
