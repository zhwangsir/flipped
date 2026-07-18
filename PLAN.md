# M138 · 全量回归真正绿 + M137 遗留清扫

> 主题：修掉 test_factory_visual_regression 3 个长期失败的 mock 泄漏（a11y_lint 真实启动 Playwright 未被 mock），让全量 pytest 首次真正零失败；顺带清 M137 两处遗留。
> 定位：小步快跑，三个独立子任务，均主代理直接做（不派子代理）。

## 根因诊断（已实跑定位）

`test_factory_visual_regression.py` 只 mock 了 `driving.visual_regression.make_visual_verifier`，但 verifier 装配链在 `factory_loop.py` L804-809：`combined_verifier_with_a11y(_base)` → `a11y_lint` 内部真实启动 **Playwright headless Chromium + 本地 HTTP 服务** 做 axe-core WCAG 扫描。测试环境无浏览器 → `ConnectError: [Errno 61]` → `_stub_drive_capture_verifier` 里 `verifier(...)` 抛异常 → `captured["verifier_result"]` 未赋值 → 断言失败。

M134.2 验收时 Playwright 浏览器可用故 5/5；现在不可用故 3 失败。**不是该 skip 的环境依赖，是 mock 不完整**——test 4 已正确 mock 了 a11y/design_lint 两层，test 1/2/3 漏了。

## 子任务

### M138.1 · visual_regression 测试 mock 补全
- test 1/2/3 补 mock `driving.a11y_lint.combined_verifier_with_a11y` + `driving.design_lint.combined_verifier`（照抄 test 4 的 mock 模式），让 verifier 链完全离线。
- 顺带给 `_stub_drive_capture_verifier` 的 verifier 调用加 try/except，异常记入 captured（断言更鲁棒，失败信息更清晰）。
- 验收：`pytest tests/test_factory_visual_regression.py` 5/5 绿（无浏览器环境）。

### M138.2 · m10_integration 硬编码路径 tmp 化
- `tests/test_m10_integration.py` 显式硬编码 `"data/gold_memory.db"`（M137 W1 报告：每次运行真实写该文件，在 data/ 留碎片）。改 tmp_path 注入。
- 验收：该测试绿，且运行后 data/ 无新增 gold_memory.db。

### M138.3 · checkpoint_db_path 死参处理
- `run_factory_loop(checkpoint_db_path=...)`（factory_loop.py L976/1005）赋值后下游从未使用——真正写 checkpoint 的是 `default_orchestrator_fn` 内部（M137 W2 报告确认死参）。infinite_loop.py 仍传它。
- 处理：**接线**而非删除（保留签名兼容）——把 `checkpoint_db_path` 透传进 orchestrator_fn 的 checkpoint 路径（若 orchestrator_fn 接受该参数）；若接线牵扯面大，则删除参数并同步清理 infinite_loop 调用方 + 测试。**先做最小调查再定**。
- 验收：死参消除（要么真正生效、要么签名移除且调用方同步），全量零回归。
- **实际决策（已落地）：删除**。调查结果：①`default_orchestrator_fn` L909 硬编码 `db_path=default_db_path()`，`OrchestratorFn` 协议为 `(task, state)` 不接受路径，接线需改协议+全部 mock orchestrator，牵扯面大；②M137 已决策 checkpoint 收敛统一库、thread_id 命名空间隔离，接线会复活 per-file 库违背该决策。故删除 `run_factory_loop.checkpoint_db_path` + `run_infinite_loop.factory_checkpoint_db_path`，同步清理 infinite_loop 调用方 + 8 个测试/脚本调用点（共 17 处 kwarg）。`api/schemas.py` 的 `session.checkpoint_db_path` 是 API 会话字段（另一套），不动。

## 验收标准（M138 总）

- [x] `pytest tests/` 全量**零失败**：1521 passed（首次真正绿，原 1518+3 环境依赖失败已修）
- [x] data/ 运行测试后无碎片新增（仅 flipped.db + axe.min.js 缓存 + M137 .bak 备份）
- [x] vitest 57 零回归 + console build ✓
- [x] STATE.json / TEST_LOG.md 更新

---

# M137 · SQLite 八库合并（M136 拆出项）

> 来源：M136 计划「SQLite 八库合并风险高，与事件表工作互相干扰，拆到 M137」。
> 主题：8 个默认 db 路径收敛为单一 `data/flipped.db`（env `FLIPPED_DB` 可覆盖），消除连接碎片，统一 pragma/WAL/迁移治理。

## 现状盘点（8 默认路径 → 表）

| db | 表 | 使用方 |
|---|---|---|
| factory.db | factory_states, factory_events | factory_loop.py, api/factory.py |
| factory_checkpoints.db | checkpoints, writes | factory_loop.py (SqliteSaver) |
| checkpoints.db | checkpoints, writes | orchestrator.py, api/main.py |
| delegate_checkpoints.db | checkpoints, writes | stuck_detector.py |
| failures.db | failures | failure_kb.py, repair_kb.py |
| gold_memory.db | gold_memory | gold_memory.py, rca.py |
| skills.db | skills | skill_registry/evolution/recommender.py |
| infinite_loop.db | infinite_loops | infinite_loop.py |

磁盘现存 5 个（factory/factory_checkpoints/failures/gold_memory/skills），其余 3 个为运行时默认、尚未落盘。

## 关键冲突与对策

1. **三个 LangGraph saver 库表名相同**（checkpoints/writes）→ 合并后共享表，**thread_id 命名空间区分**（orch-* / factory_id / deleg-*），这是 LangGraph 官方支持的多 graph 共库用法。
2. **写并发** → 单文件 + WAL + busy_timeout=5000，统一 `connect()` 入口施加。
3. **表名冲突** → 八库表名互不相同（已核实），零改名合并。

## 工作流划分

| 流 | 子任务 | 独占文件 |
|---|---|---|
| 主代理先行 | M137.0 统一存储入口 `driving/db.py`（很小） | 新 `src/driving/db.py` |
| W1 | M137.1 知识库类四模块默认值收敛 | failure_kb.py repair_kb.py gold_memory.py rca.py skill_registry.py skill_evolution.py skill_recommender.py |
| W2 | M137.2 saver/factory/api 收敛 + thread_id 命名空间 | factory_loop.py orchestrator.py stuck_detector.py infinite_loop.py api/main.py api/factory.py |
| W3 | M137.3 迁移脚本 + roundtrip 测试 | 新 scripts/migrate_db_merge.py 新 tests/test_db_merge.py |

文档（STATE.json/TEST_LOG.md）主代理收尾统一写。

## M137.0 · 统一存储入口

`driving/db.py`：
- `default_db_path() -> str`：`os.environ.get("FLIPPED_DB", "data/flipped.db")`
- `connect(path=None)`：sqlite3.connect + `PRAGMA journal_mode=WAL`(内存库跳过) + `busy_timeout=5000` + synchronous=NORMAL + temp_store=MEMORY + mmap_size=256MB，fail-open。
- 各模块 `db_path: str = "data/xxx.db"` 默认值改为 `db_path: str | None = None`，函数体内 `db_path = db_path or default_db_path()`。**测试注入 tmp 路径行为不变**。

## M137.1 · 知识库类收敛（W1）

- 上述 7 文件默认值收敛；`sqlite3.connect(...)` 换 `db.connect(db_path)`。
- env 兼容：`FLIPPED_FAILURES_DB` 等既有专用 env 若存在则优先（先查代码里是否有，无则不加）。

## M137.2 · saver/factory/api 收敛（W2）

- factory_loop / orchestrator / stuck_detector 的 SqliteSaver.from_conn_string 默认路径收敛。
- thread_id 命名空间约束落为常量：orchestrator resume 入口给 thread_id 加 `orch-` 前缀（仅默认路径，显式传入不破）；stuck_detector 子 agent 用 `deleg-{factory_id}`；factory 用 factory_id 本身。写入 DECISIONS 候选。
- api/main.py `FLIPPED_CHECKPOINT_DB`、api/factory.py `FLIPPED_FACTORY_DB` env 保留但默认值指向 `FLIPPED_DB`（向后兼容优先读专用 env）。
- infinite_loop.db → infinite_loops 表迁入。

## M137.3 · 迁移脚本 + 验收（W3）

`scripts/migrate_db_merge.py`：
- 对现存旧库逐个 ATTACH → 逐表 `INSERT OR IGNORE`(含 factory_events 保留 seq) → 行数校验 → 旧库改名 `*.db.bak-YYYYMMDD`。
- `--dry-run` 只打印计划；幂等可重跑。
`tests/test_db_merge.py`：
- 造 3 个含数据的临时旧库 → 迁移 → 断言目标库行数/关键内容一致、重复迁移不翻倍。
- 三 saver 共库隔离性：同一 flipped.db 两个 thread_id 各写 checkpoint 互不可见。

## 技术约束

1. **向后兼容**：所有公开函数签名保留 `db_path` 参数；测试用 tmp 库不受影响；专用 env 优先于统一 env。
2. **fail-open**：迁移/pragma 失败不崩主流程。
3. **不引新依赖**。
4. 红线：不准在迁移脚本里 DROP/DELETE 旧库数据，只改名备份。

## 验收标准（M137 总）

- [ ] 8 默认路径全部指向 data/flipped.db（grep 审计为零残留）
- [ ] 迁移脚本 dry-run + 实跑 roundtrip 测试通过
- [ ] 三 saver 共库 thread_id 隔离测试通过
- [ ] 全量 pytest + vitest 零回归
- [ ] STATE.json / TEST_LOG.md 更新

---

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
