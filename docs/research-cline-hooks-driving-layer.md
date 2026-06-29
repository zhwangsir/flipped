# 调研：驾驭层落点（M3.1）+ Cline hooks 协议

> 日期 2026-06-29 ｜ docs.cline.bot + 仓库源码 ｜ 置信：高（hook schema 以本机实测为准——文档站 JS 渲染、有命名双轨坑）

## M3.1 决策：三层分工，不 fork（D9）

| 件套 | 落点 | 理由 | 验收 |
|---|---|---|---|
| (1) 强制验证 | **C** LangGraph | hooks 只能"提示"不能"强制下一步"；验证是完成后的确定性节点 | 留一失败用例，agent 自报完成仍强制跑验收、失败回灌不放行 |
| (2) 循环检测 | **C** LangGraph | 需跨多次 Cline 调用记忆 same-file/action 计数；hooks 无跨步记忆 | 同文件改 3 次 → 第3次中断进重规划（state 有计数器）|
| (3) 上下文压缩 | **A** Cline 原生 Auto Compact | 已内建（近上限自动总结落盘续跑）+ Focus Chain todo 锚点；零代码 | 超长任务自动 compact，技术决策/改动不丢 |
| (4) 人工审批 | **A 兜底 + C 硬断点** | 日常用 Plan/Act + 关危险类 auto-approve；不可绕过的暂停用 LangGraph interrupt() | 高风险动作前 graph 暂停，resume 放行/否决，reject 无副作用 |
| (5) 子Agent主从 | **C** supervisor + Cline 执行器 | GLM supervisor 路由；子任务自定义 handoff(裁剪历史)给干净上下文，Kimi headless 执行，结构化交回 | 子上下文不含主线无关历史；交接是结构化对象 |
| (6) 可观测性 | **A 采集 + C 归档** | PostToolUse hook 吐每步结构化 JSON；LangGraph checkpoint 跨步可回放 | 任一步可还原 输入→工具→输出；崩溃后 thread_id 精确恢复 |

**B（fork Cline 源码）6 件套全不需要。** 落地顺序：先 A 侧（Auto Compact/Focus Chain、.clinerules 验收约束、PostToolUse 日志 hook）→ 搭 C 的 supervisor 骨架（**换 SqliteSaver/PostgresSaver**，InMemory 进程重启即丢）→ 接 (1)(2)(4硬断点)(5)。

## Cline Hooks 协议（A 侧实现依据）

- 系统：v3.36（2025-09）引入，Claude-Code 风格。**仅 macOS/Linux**。
- 加载：CLI `--hooks-dir <dir>`（默认 `~/.cline/hooks`，env `CLINE_HOOKS_DIR`）+ 工作区 `.cline/hooks/`。
- File hook = **可执行脚本**，文件名严格 = 事件 PascalCase 名，`chmod +x`，支持 .sh/.py/.ts。
- 事件（文件名 → stdin `hookName` snake_case → runtime 回调）：
  - `PreToolUse`→`tool_call`（每个工具前，**可 cancel/overrideInput**）
  - `PostToolUse`→`tool_result`（每个工具后，带 output/durationMs）
  - `TaskStart`/`TaskResume`/`UserPromptSubmit`/`TaskComplete`(coming soon)/`TaskError`/`TaskCancel`/`SessionShutdown`/`PreCompact`(暂仅 runtime)
- **stdin 载荷**（JSON）base：`clineVersion/hookName/timestamp/taskId/workspaceRoots/workspaceInfo?/userId/agent_id/parent_agent_id`。
  - `tool_call`：`iteration` + `tool_call:{id,name,input}`
  - `tool_result`：`iteration` + `tool_result:{id,name,input,output,error,durationMs,...}`
- **stdout 决策**（JSON）：`cancel?`(true=软中断当前 tool/turn)、`contextModification?`(注入文字，**只影响下一次 API 请求**，~50000 字符)、`errorMessage?`、`review?`、`overrideInput?`(PreToolUse 改写入参)。无控制键=NoOp。
- 协议坑：stdout 必须合法 JSON（解析失败按 NoOp，不崩）；**退出码非 0 仅 warn，不等于阻断**（阻断必须 `cancel:true`）；子进程超时 ~30s SIGKILL。

## 关键坑（建前必读）
1. **命名双轨**：文件名 PascalCase(`PreToolUse`)，但 stdin `hookName` 是 snake_case(`tool_call`)，工具信息在 `.tool_call.{name,input}` 而非 `.toolName`。**按实际 stdin 解析，别照搬 blog**。
2. `cancel` 是软中断当前动作；`contextModification` 只对下一轮生效 → "打回重做" = cancel + 注入指示，agent 下一轮才看到。
3. hooks 无内置历史 → 循环检测须脚本自管状态文件（按 taskId 隔离）。这也是为何 (1)(2) 上移到 C。
4. interrupt() node 重跑陷阱：有副作用的 Cline 调用必须放 interrupt 之后或幂等。
5. supervisor 默认 handoff 传全量历史 → 必须自定义裁剪，否则子上下文被污染。

> 全量来源/源码路径见会话记录 task wuw3zewas（sdk/packages/shared/src/hooks/events.ts 等）。sdk-builtins 子调研失败，内建能力以 mapping 路结论为准，接线前实测 @cline/sdk 事件 schema。
