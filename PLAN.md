# Phase B · B3 计划：Console 接入真实 WS 数据流 ✅

## 目标
让 flipped Console 不再使用 mock 数据，而是：
1. 从 `orchestration-api` 拉取会话列表；
2. 选中会话后通过 WebSocket 订阅实时事件；
3. 在会话流中展示真实 Supervisor / Worker / Overseer / Verify 事件；
4. 支持在输入框发送任务（创建会话 + 派发任务）。

## 涉及文件
- `console/src/types.ts` — 共享类型 + 后端事件 → StreamItem 转换。
- `console/src/api.ts` — HTTP + WebSocket 客户端。
- `console/src/store.tsx` — React Context：会话、当前会话、事件流、连接状态、API 动作。
- `console/src/mock.ts` — 仅保留静态演示数据（diff/终端/MCP 等）。
- `console/src/App.tsx` — 挂载 Provider。
- `console/src/components/Sidebar.tsx` — 真实会话列表，支持新建/切换。
- `console/src/components/Conversation.tsx` — 真实事件流；composer 支持发送任务。
- `console/src/components/StatusBar.tsx` — 显示 WS 连接状态。
- `console/src/styles/app.css` — 连接状态指示点样式。
- `scripts/verify_b3.sh` — 构建 Console + 起 mock 后端 + WS 端到端验证。

## 验收结果 ✅
- `npm run build` 通过，TypeScript 无错。
- `scripts/verify_b3.sh` 退出码 0：
  - 启动 orchestration-api（`FLIPPED_MOCK_WORKER=1`）；
  - 创建会话并派发任务；
  - Console 通过 WS 收到 24 个事件，包含 message / tool_call / tool_result / file_change / terminal / browser / status；
  - 静态托管的 console/dist 首页可访问。
- `python -m pytest tests/` ✅ 29 passed。

## 下一步：B4
- `tool-calling 加固`：给 OpenHands Worker 加结构化输出约束 / 重试 / tool 失败处理，确保 tool_call 解析稳定。
- `cost warning 修复`：解决 OpenHands / litellm 拉取远端 cost map 超时/警告；稳定本地模型调用。
