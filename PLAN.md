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

---

# M7 · UI 诚实化:全部接成真功能 ✅

> 背景:用户发现"很多功能都用不了"——大量 UI 控件是纯装饰(无 onClick / mock 数据 / 硬编码谎报)。
> 用户明确选择"**全部接成真功能**"(而非删除),优先级:模型切换 / 真实编辑器 / MCP 真列表+开关 / 模式切换。

- **M7.1 模型切换** ✅ — 输入区下拉真切执行模型;`model_router.resolve_worker_model_config(alias)` 按 coder=Kimi/architect=GLM 返回不同模型;`create_task` 透传 `context.model` → 沙盒用对应模型。真实验证:architect(GLM) 在沙盒执行建 g.py。
- **M7.2 真实编辑器** ✅ — 编辑器 Tab 显示沙盒真实文件内容;worker 从 `file_editor` ActionEvent 抓 `file_text` 随 `file_change` 发出;store 合并保内容;多文件 chips + 行号 + 语法高亮。验证:calc.py 内容真实。
- **M7.3 MCP 真列表 + 开关** ✅ — `api/mcp_registry.py` 配置文件持久化;flipped 5 工具内省自 `mcp_server.tools.TOOLS`;`GET /mcp/servers` + `POST /toggle`;启用项经 `enabled_mcp_config()` 注入 Agent `mcp_config`(默认全关不改变已验证路径)。
- **M7.4 模式切换** ✅ — `create_task` 按 `context.mode` 路由;`_run_chat`+`_llm_chat`:对话=直连本地模型问答、规划=LLM 出【要做什么/如何验证】分步计划、智能体=沙盒执行不变。验证:Kimi 秒回 / GLM 出计划。
- **M7.5 侧栏·顶栏·输入区控件全部接真** ✅ — 共享导航状态入 store(activeView/contextTab/sidebarTab/showContext/sessionQuery);ActivityBar 真导航;TopBar 修正硬编码谎报(随 selectedModel/sessionStatus/会话/变更数)+ 布局切换面板;会话搜索过滤;composer @插入/工具→MCP/沙盒→终端;移除无后端支撑的假按钮(运行/main/附件)。

**验收**:全量 **107 passed**;`console build` 绿;Puppeteer 浏览器实测 6 类控件全部生效(搜索过滤 m74→2 / 模型 pill→GLM-5.2 / rail 导航→浏览器·MCP tab / MCP 开关→持久化后端 / 布局→隐藏面板 / 模式→规划+placeholder 变)。

---

# M8 · Tauri 桌面壳硬化

> 背景：UI/功能已全面诚实化，下一步是把外壳从浏览器升级为 Tauri 桌面壳，以支持原生文件夹选择、嵌入式可交互浏览器、一等终端、自动打包/签名。
> M8 先完成后端自启动，让 `flipped.app` 不依赖外部脚本即可运行。

## 任务

1. **T1 · Tauri 自动拉起后端** ✅ 已完成
   - 新增 `console/src-tauri/src/backend.rs`：项目根查找、HTTP 健康探测、子进程启动、应用退出时 kill 子进程。
   - `console/src-tauri/src/lib.rs`：在 `setup` 中启动后台线程自动拉起后端（若未运行），`CloseRequested` 时清理子进程。
   - 环境变量：`FLIPPED_BACKEND_PORT` / `FLIPPED_BACKEND_AUTO_START` / `FLIPPED_ROOT`。
   - Rust 单元测试 2 个通过：`find_project_root_from_nested_dir`、`is_backend_healthy_false_when_nothing_listens`。
   - Rust 模块 `backend.rs`：查找项目根、健康检查、启动 Python backend (`uvicorn api.main:app`)、应用退出时关闭。
   - `lib.rs` 在 `setup` 中启动后台线程，监听 `CloseRequested` 清理子进程。
   - 环境变量：`FLIPPED_BACKEND_PORT` / `FLIPPED_BACKEND_AUTO_START` / `FLIPPED_ROOT`。
   - Rust 单元测试 + `cargo build` 通过。
2. **T2 · 嵌入式可交互浏览器** ✅ 已完成
   - 新增 `console/src-tauri/src/browser.rs`：子 webview create/update/close。
   - `Cargo.toml` 启用 `tauri/unstable` feature 以使用 `Window::add_child`。
   - `console/src/components/ContextPanel.tsx` 在 Tauri 模式使用 host div + ResizeObserver 同步位置。
   - 验证：`cargo build` + `cargo test`（4 passed）+ `console npm run build` + Python 全量 221 passed。
3. **T3 · 终端统一到面板** ⏳ 待做
   - 用 Tauri portable-pty / 子进程把终端接到右侧面板终端 tab。
4. **T4 · 打包/签名/自动更新** ⏳ 待做
   - Rust sidecar 自动拉起后端、原生菜单/托盘、`cargo tauri build`、签名。

## 验收

- `cargo build` 通过；单元测试通过。
- Tauri 应用启动时，若后端未运行则自动拉起；退出时关闭。
- 不破坏现有 `predev.sh` 与 Python 测试。
