# M136 · 地基工程：契约与边界（Kimi/Grok 调研反哺）

> 来源：Kimi Code × Grok Build × flipped 三方对比调研（2026-07-18）。
> 主题：把调研判定「他们更强」的项落地——崩溃恢复、契约治理、终端测试、权限管线、结构化错误。
> SQLite 八库合并风险高，与事件表工作互相干扰，**拆到 M137**；本里程碑只做 pragma 加固。

## 工作流划分（三个并行子代理，文件所有权隔离）

| 流 | 子任务 | 独占文件 |
|---|---|---|
| W1 | M136-A 崩溃恢复 + M136-D ToolResult 结构化错误 | `driving/factory_loop.py` `driving/orchestrator.py` 新 `driving/event_log.py` |
| W2 | M136-E 权限管线五级 | `driving/approval.py` |
| W3 | M136-B 契约治理 + M136-C 终端数据通路测试 | `api/` `console/` `scripts/` |

文档（STATE.json/TEST_LOG.md）由主代理收尾统一写，子代理禁止触碰。

---

## M136-A · 崩溃恢复补全（Temporal 范式：事件日志 + 幂等键）

### 现状缺口
- 有快照：LangGraph SqliteSaver + factory SQLite resume。
- **缺事件日志**：工具调用/LLM 响应未在副作用前落盘。
- **缺幂等键**：resume 重放时 write/verify 类副作用可能重复执行（真实缺陷）。

### 实现
1. 新 `driving/event_log.py`：
   - `append_event(conn, factory_id, kind, payload, idempotency_key)` — append-only `factory_events` 表（factory_id, seq AUTOINCREMENT, ts, kind, payload_json, idempotency_key UNIQUE 允许 NULL）
   - `seen_idempotency_key(conn, key) -> bool`
   - `_ensure_event_table` 迁移（旧表兼容）
2. `factory_loop.py` 写入点（task 开始/verify 结果/task 完成），副作用前落盘。
3. resume 路径：重放前查幂等键，已执行过的副作用跳过重复执行。
4. SQLite pragma 加固：`synchronous=NORMAL`、`mmap_size`、`temp_store=MEMORY`（顺带 M136 范围内）。
5. 恢复演练测试：模拟 task 中途崩溃 → resume → 断言副作用不重复、事件连续。

### 验收
- [ ] factory_events 表存在且 append-only
- [ ] 崩溃演练测试通过（无重复副作用）
- [ ] 全量 pytest 零回归

## M136-D · ToolResult 结构化错误（抄 Grok proto 设计）

### 实现
1. `orchestrator.py`：工具/verify 失败结果携带 `retryable: bool` + `suggestion: str`（供 LLM 消费，模型看到 retryable 知道可重试、看到 suggestion 知道怎么修）。
2. 输出裁剪：长输出截断策略（带 `truncated` 标记），省 token。
3. fail-open：不影响现有文本 content 消费路径。

### 验收
- [ ] 失败结果含 retryable/suggestion
- [ ] 超长输出截断带标记
- [ ] 全量 pytest 零回归

## M136-E · 权限管线五级（Grok 管线 + Kimi engine 决策原则）

### 现状
`approval.py` 只有 `classify_risk`（正则分类 high/low）+ interrupt 门控。无规则、无记忆、无只读放行。

### 实现（五级，顺序执行，短路返回）
1. **L1 hooks**：PreToolUse 钩子可否决（预留接口，默认空）。
2. **L2 规则表**：deny/ask/allow 三级规则 + glob pattern，跨来源合并时 **deny > ask > allow**。
3. **L3 项目级记忆授权**：approved 的 pattern 记到 `.flipped/approvals.json`（按 cwd），下次自动放行。
4. **L4 只读自动批准**：只读命令白名单（ls/cat/git status/grep/find 等）免提示。
5. **L5 模式策略**：`default`（高危问）/ `dontAsk`（全自动）/ `plan`（只读+计划）。
6. **bash 链式拆分**：`&&`/`||`/`;`/管道逐段评估，任一 deny 则整体 deny，任一 ask 则整体 ask。
7. 保持 `build_approval_graph` 向后兼容（现有 interrupt 门控行为不变，走新管线的 verdict）。

### 验收
- [ ] 五级短路语义正确（deny 优先、记忆命中放行、只读免问、dontAsk 全放）
- [ ] bash 链式拆分：`ls && rm -rf /` → deny；`git status && ls` → allow
- [ ] 记忆授权持久化 roundtrip
- [ ] 全量 pytest 零回归

## M136-B · 契约治理（Kimi 式 drift test）

### 实现
1. **OpenAPI 快照测试**：`tests/test_api_contract.py`——导出 FastAPI `app.openapi()` → 归一化（去描述性噪声）→ snapshot 比对，API 面变更必须显式更新快照。
2. **WS ack 语义**：events WS 支持客户端 `{type:"ack", last_event_id}` 帧，server 收到后记录（轻量，不改现有 replay 逻辑）；terminal WS 协议文档化。
3. **openapi-typescript codegen**：`console/scripts/gen-api-types.mjs`（或 npm script）从 `/api/v1/openapi.json` 生成 `console/src/api-types.d.ts`；build 前可选刷新。

### 验收
- [ ] 快照测试存在且实跑通过
- [ ] ack 帧单测通过
- [ ] codegen 脚本实跑生成类型文件
- [ ] 全量 pytest + vitest 零回归

## M136-C · 终端数据通路测试（Grok ptyctl 模式移植）

### 现状缺口
`pty → WS → xterm.js` 链路只有 Playwright 截图级覆盖；字节丢帧/UTF-8 截断/resize 竞态不可诊断。

### 实现
1. `console/` 装 `@xterm/headless`（与前端 `@xterm/xterm` 同源）。
2. `console/src/terminal/waitFor.ts`：事件驱动 wait——`{text, regex, gone, stableMs}` 四条件，帧到达即重查零轮询，超时带诊断（屏幕文本 + 最近 N 字节原始流）。
3. vitest 数据通路测试（不起浏览器）：
   - WS client → `/api/v1/terminal` → 真实 shell；帧流喂 `@xterm/headless` Terminal，断言 buffer 文本
   - marker 夹具：`printf 'MARKER-%03d\n' {1..400}` 断言滚动/换行收敛
   - resize：`{r}` 帧后断言重排
   - UTF-8：中文/emoji 输出断言无截断乱码
   - 需起后端：用 pytest 同款 test server 或在 vitest globalSetup 起 uvicorn

### 验收
- [ ] waitFor 四条件单测
- [ ] 数据通路 vitest 实跑通过（marker/resize/UTF-8）
- [ ] 全量 vitest 零回归

---

## 技术约束

1. **fail-open**：事件表/幂等键/ack 异常不阻塞主流程
2. **向后兼容**：approval graph 行为不变；WS 协议只加不改；旧 SQLite 表自动迁移
3. **子代理纪律**：只跑自己的定向测试（新测试文件），全量回归由主代理收尾跑
4. **不引重型依赖**：@xterm/headless 是唯一新增 npm 依赖；Python 侧零新增

## 验收标准（M136 总）

- [ ] A/D/E/B/C 五项子验收全绿
- [ ] 全量 pytest（基线 1463+）+ vitest（基线 45+）零回归
- [ ] `npx tsc --noEmit` + `npm run build` 通过
- [ ] TEST_LOG.md 记录实跑证据，STATE.json 更新
