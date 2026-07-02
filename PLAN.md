# M6 · 从骨架到可用产品：真实端到端 + Console 功能补全 + 产品化

> M0–M5 已完成(骨架 + 多 Agent 编排 + backend/WS + Console 外壳 + 硬化,92 单测绿),但**全是 mock 验证**,`ISSUE-6`(Codex 沙箱禁 TCP/网络)使真实端到端从未跑通,Console 多数面板仍是 mock,未产品化。
> 本机(macOS 真机)无 ISSUE-6 限制,可做真实 E2E。M6 目标:**让它真正跑起来、Console 真正可用、能打包分发**。

## 优先级与顺序
自主可验的先做(Console 补全 + 后端端点 + 产品化脚手架),模型在线才可跑的真实 LLM E2E 靠后(需用户 LAUNCH exo 模型)。

## 阶段与任务(每个任务:TDD/构建 → verify → commit)

### M6.0 UI 打磨落盘 ✅(本次)
- Console 设计系统改造(去 AI 感 → Codex 简约):tokens.css + app.css。verify:构建绿 + 真实 mock 后端 WS 截图。

### Phase 1 · Console 功能补全(自主,mock 后端可验)
- **M6.1 ContextPanel 接真实事件流** — editor/diff/终端/浏览器 Tab 从会话事件(file_change/terminal/browser)渲染,替换 `mock.ts` 静态数据;新增 store 派生的工作区文件/diff/终端/浏览器状态。verify:发任务后右侧面板显真实数据 + 构建 + headless 截图。
- **M6.2 会话操作补全** — 停止/取消任务、删除会话、切换会话清空正确;后端补 `DELETE /sessions/{id}`、`POST /tasks/{id}/cancel`、`GET /sessions/{id}/events`(REST 历史)。verify:pytest + curl + 截图。
- **M6.3 指标接入 UI** — `GET /api/v1/metrics` 真实值进状态栏/指标面板(token/延迟/调用数),替换硬编码占位。verify:pytest(指标端点)+ 截图。
- **M6.4 资源管理器接真实工作区** — 侧栏文件树显示会话沙箱真实文件(经后端 `GET /sessions/{id}/workspace`)。verify:pytest + 截图。

### Phase 2 · 真实端到端(本机真机,部分需 exo 模型在线)
- **M6.5 真实 backend + OpenHands 沙箱 E2E** — 非 mock:Console 派一个真实编码任务 → openhands_worker 在 Docker 沙箱执行 → 真生成文件 + 事件回流 Console。修复 E2E 暴露的问题。verify:沙箱内真文件 + Console 实时可见 + 验收通过(需 exo 模型 + Docker)。
- **M6.6 模型路由落实** — 确认直连 exo(FLIPPED_MODEL_BASE_URL)或恢复 LiteLLM:4000 统一路由(ISSUE-5);Supervisor/Overseer/Worker 全部走通。verify:真实调用返回 + verify_m5.sh。

### Phase 3 · 产品化
- **M6.7 一键启动 + 编排** — `scripts/dev_up.sh` 一键起 backend + console(+ 探活 OpenHands);进程管理与健康检查。verify:脚本起全栈 + 截图。
- **M6.8 Electron 桌面壳** — 壳内嵌 Console(生产构建)+ 主进程 spawn backend sidecar + 连 OpenHands;`npm run app`。verify:Electron 起窗截图。
- **M6.9 CI** — GitHub Actions:pytest + console build(在非受限 runner)。verify:workflow 文件 + 本地 act/干跑说明。

## 验收标准(M6 DoD)
- 全量 `pytest tests/ -q` 保持全绿(每个后端任务新增测试)。
- `cd console && npm run build` 保持通过(每个前端任务后)。
- Console 每个面板都由**真实后端数据**驱动(mock.ts 仅保留为离线兜底/演示)。
- 至少一次**真实(非 mock)**任务在沙箱跑通并在 Console 全程可见(M6.5,模型在线时)。
- 一键脚本可拉起全栈;Electron 可出窗;CI workflow 就绪。

## 循环开发约定(AGENTS.md)
- 每任务:先写测试/明确 verify → 实现 → 跑测试/构建/截图 → 通过即 `git commit` + 更新 STATE.json/TEST_LOG.md → 下一个。
- 非 mock 需外部依赖(exo 模型 / Docker)时,若不可用则记录为"待模型在线复跑",不阻塞其余任务。
- 诚实报告:mock 验证与真实验证分开陈述。

## 回滚
- 分支 `codex/m6-product`;每任务独立 commit,可逐个回退。不破坏已绿的 M0–M5 代码与测试。
