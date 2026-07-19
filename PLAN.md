# M142 · 三轨并行：Phase 2 devcontainer 实跑 + supervisor IDE 接线 + factory 任务级并行

> ✅ 验收通过（2026-07-19）：W1 verify_m142_devcontainer.sh CORE 全绿 + KNOWN-ISSUE 清零（postCreateCommand 模板 bug 已修）；W2 9 用例绿含真实 GLM e2e（全量中实跑非 skip）；W3 15 用例绿（墙钟/恰好一次/依赖/预算/崩溃恢复）。全量 pytest 1586 passed / 0 failed（净增 24）。证据见 TEST_LOG.md M142 节、STATE.json M142 条目。

> 来源：用户一次选定三个方向，按惯例 Agent 团队并行（W1/W2/W3 子代理），主代理汇总回归 + 留痕。
> 侦察结论：W1 模板仅静态校验（verify_phase2.sh 只查文件），运行时未验；W2 :4000 在跑（401=需 key，走 LITELLM_MASTER_KEY/EXO_API_KEY），supervisor Plan schema 无 IDE 通道；W3 factory `_next_task` 单任务串行，task_dag/parallel_executor 闲置。

## W1 = M142-A · Phase 2 devcontainer 运行时验收
- 装 @devcontainers/cli（若缺）；`devcontainer build`（--config 指 infra/env-templates/devcontainer.json）→ `up` → 容器内 `exec` 验证 python3.12 / node20 / rustc / java21 / mise 真实可用且版本对。
- 网络按 D7：registry 走 daocloud 镜像（mcr.m.daocloud.io / ghcr.m.daocloud.io）；拉不动则如实降级记录（docker run 基础镜像手动验核心工具版本），禁止谎报。
- 产出 `scripts/verify_m142_devcontainer.sh` 一键复跑；证据进 TEST_LOG.md。

## W2 = M142-B · supervisor IDE 工具面接线（M141 续）
- orchestrator.py：Plan schema 加可选 `ide_action: {name, args}`；`_build_supervisor_prompt` 注入 IDE_TOOL_REGISTRY 工具清单（名称+描述+必填参）；believe_done/subtask/ide_action 三态互斥（ide_action 优先于子任务派发？——设计：supervisor 每轮三选一：派子任务 / 调 IDE 工具 / believe_done）。
- 新增 governed 执行路径：ide_action → governed_ide_call（M141）→ deny/ask 不执行、结果写 feedback 回灌 supervisor；allow 执行结果同样回灌。审计接 factory_events（session 级 factory_id 约定复用 sess-* 或 orch-*，勿新造）。
- 单测全 mock（schema 解析/prompt 含工具清单/deny 回灌/allow 执行回灌）；真实 GLM e2e 1 场景（goal 需读 IDE 设置 → supervisor 输出 ide_action，caller mock 记录即算通——真实 LLM + 注入 caller）。
- 高风险：改 orchestrator.py 核心，必须小步、全量回归零失败才算完。

## W3 = M142-C · factory 任务级并行（并行执行、串行落账）
- `_ready_tasks(state)`：返回所有依赖满足的 pending 任务（现有 _next_task 的单任务版推广）。
- `FLIPPED_MAX_PARALLEL`（默认 1 = 现状零回归）：>1 时用 ThreadPoolExecutor 并行跑 orchestrator（LLM 耗时部分），主循环**串行**应用 task_done 副作用（completed 追加/事件/quality/memory），幂等键语义不变。
- 共享 state 隔离：并行 worker 只读 state 快照，不直接改；落账只在主循环。DB 单行 JSON 写不并发。
- 测试：mock orchestrator（慢任务+屏障）断言 N=3 并行时墙钟 < 串行；completed 无重复、事件幂等键各 1 条、depends_on 语义不破。

## 汇总（主代理）
- 三轨全量 pytest + 相关 verify 脚本；STATE.json M142 条目（3 子任务）+ TEST_LOG.md + PLAN.md 验收标记。

## 约束
- 各轨独立分支式小步，互不触碰对方文件（W1=infra+scripts；W2=orchestrator+其测试；W3=factory_loop+其测试）。
- 网络/宿主受限处如实降级记录，禁止谎报（AGENTS.md §5）。
- 不引新 Python 依赖。

---

# M141 · IDE 控制面工具面接入驾驭层（M3 遗留首项）

> 来源：用户选定「转向 M141，推进 M3 驾驭层剩余模块」。核查结论：循环检测(M3.4)/上下文压缩(M3.7+M5.2)/子Agent派发(M3.6)/M4 MCP+RAG 均已 done；M3 note 记录的真实遗留首项 = IDE 控制面 agent 桥接入。
> 现状缺口：ide-extension TS 桥(127.0.0.1:39217 POST /tool, 9 工具)与 Python ide_client 均已建且各有单测，但 **orchestrator 编排层拿不到这套工具**——ide_client 全项目零调用方；工具未纳入 M136-E 五级权限管线；调用无 factory_events 审计。
> 定位：纯本地确定性改动，TDD，不依赖模型。主代理直接做（M138/M140 小步模式）。真实 VS Code 宿主端到端验证受限（需扩展宿主），记为已知限制，由注入式单测兜底。
> **验收结果（done）**：ide_tools.py（注册表9工具/render/governed_ide_call/审计）落地；test_ide_tools.py 24 用例 + ide_client 3 定向全绿；全量 pytest 1562 passed/0 failed（48.51s）。

## 子任务

### M141.1 · src/driving/ide_tools.py 工具注册表 + 动作渲染
- `IDE_TOOL_REGISTRY`：9 工具（与 extension.ts 对齐）——ide.runTask/openTerminal/getSetting/updateSetting/installExtension/runCommand + env.addDevcontainerFeature/miseUse/rebuildDevcontainer；每项含 description/必填参数。
- `render_ide_action(name, args) -> str`：把工具调用渲染成可评估动作串。关键：openTerminal 有 command 时渲染为命令本体（`rm -rf /` 直接进管线被判 deny）；rebuildDevcontainer 渲染 `devcontainer rebuild`；installExtension 渲染 `installExtension <id>`。
- `IDE_RULES`：ide 专属规则叠加（getSetting/runTask/openTerminal 无命令/env 两个声明文件编辑 = allow；updateSetting/runCommand/installExtension = ask），与 DEFAULT_RULES 合并（deny>ask>allow 优先级不变）。
- 未知工具名 → KeyError（注册表守门）。

### M141.2 · governed_ide_call：五级管线 + 审计
- `governed_ide_call(name, args, *, cwd=None, mode="default", caller=call_ide_tool, audit_conn=None, factory_id=None)`：
  1. render → 2. evaluate_permission（IDE_RULES+DEFAULT_RULES 合并）→ 3. allow 才执行 caller；deny/ask 不执行。
- 返回 `IdeCallResult{decision, level, reason, result, error}`（dataclass）；执行异常捕获进 error 不抛出（fail-open 桥不可用时调用方可判）。
- 审计：audit_conn+factory_id 给定时 append_event(kind="ide_tool_call", payload={name,args,decision,level,reason})，天然 fail-open；deny/ask 也留痕（谁拦的、为什么）。

### M141.3 · tests/test_ide_tools.py
- 注册表与 extension.ts 工具名漂移守门（硬编码 9 名对照 + 必填参校验）。
- render 映射全表；openTerminal 命令本体渲染（安全关键）。
- 权限矩阵：deny（openTerminal `rm -rf /` / `sudo x`）、ask（installExtension / runCommand / updateSetting / rebuild）、allow（getSetting / runTask / 只读命令如 `git status` / env 声明编辑）。
- governed 执行：注入 fake caller——allow 路径执行并回 result；deny/ask 路径 caller 零调用；caller 抛异常进 error。
- 审计：tmp DB 断言 ide_tool_call 事件写入 + payload 含 decision/reason；无 audit_conn 不炸。

### M141.4 · 全量回归 + 状态留痕
- pytest 全量 + 定向 + STATE.json（M141 条目，含「VS Code 宿主运行时验证受限」已知限制）+ TEST_LOG.md + PLAN.md 验收标记。

## 约束
- 不动 extension.ts / ide_client.py 现有契约（POST /tool {name,args} ↔ {ok,result|error}）。
- 不引新依赖；权限判定复用 approval.evaluate_permission，不另起炉灶。
- 编排层 prompt 接线（supervisor 自主选用 IDE 工具）属模型侧验证，留待宿主环境，不在本里程碑。

---

# M140 · TUI 监控台体验深化（打磨）

> 来源：用户指示「继续进行打磨」。M139-B TUI 已落地但体验朴素（无着色分层/无进度可视化/无过滤聚焦），做体验深化。
> 定位：纯本地确定性改动，TDD（Textual run_test pilot），不依赖模型。主代理直接做，参考 M138 小步模式。
> **验收结果（done）**：TUI 用例 8→15 全绿；全量 pytest 1538 passed/0 failed（53.93s）；真实库冒烟 sub_title「15 工厂 · done 11 · paused 4」+ 进度条渲染正确。

## 子任务

### M140.1 · 状态着色 + 任务进度条列
- DataTable status 列用 `Text` 着色：done=green / running=blue / failed=red / paused=yellow，未知不着色。
- 新增 progress 列：10 格块字符条，done=绿块 / failed=红块 / pending=暗块 + 完成百分比；total=0 时占位。
- 列序：factory_id / status / progress / tasks(done/failed/total) / updated_at。
- 同步更新既有断言（row[2]→row[3]），新增 _progress_bar 纯函数单测。

### M140.2 · 工厂聚焦过滤
- DataTable 开 row cursor（zebra_stripes）；Enter 聚焦 cursor 行工厂，事件流只显示该厂；再按 Enter 或 Esc 取消。
- 聚焦切换时清空事件区并按当前过滤重拉最近 50 条（app 内只读 SQL，fail-open，不动 event_log.py）。
- 过滤期间其他工厂新事件仍推进 `_last_seq`（取消聚焦后不爆历史），只是不显示。
- App.sub_title 显示「聚焦: <factory_id>」。
- 测试：双工厂聚焦后 log 只有该厂事件 + 重拉历史可见 + 取消后他厂新事件恢复显示。

### M140.3 · Header 聚合统计
- 轮询刷新 App.sub_title（未聚焦时）：`N 工厂 · running X · done Y · failed Z · paused W`（零计数项省略）。
- 测试：3 工厂不同状态 → sub_title 含计数。

### M140.4 · 全量回归 + 状态留痕
- pytest 全量 + TUI 定向 + STATE.json（M140 条目）+ TEST_LOG.md（实跑证据）。

## 约束
- 只读纪律不破：TUI 仍只 SELECT（聚焦重拉也只读），不 connect 不存在的 DB。
- fail-open：着色/聚焦/聚合任何异常不得崩 TUI。
- 不引新依赖（rich/textual 已有）。

---

# M139 · 产线化双轨：崩溃恢复 E2E 硬化 + 全屏 TUI 监控台

> 来源：用户选定「两者并行」。W1 = AGENTS.md M5 旗舰验收（长任务中途 kill -9 → resume → 副作用不重放）；W2 = Kimi/Grok 调研唯一判定「值得做未落地」的项。
> 执行：两子代理并行（W1/W2），主代理汇总全量回归 + STATE/TEST_LOG + commit。
> **验收结果（done）**：pytest 1531 passed 0 failed（主代理独立复验）；`verify_m139_crash_resume.sh` 一键复跑 PASS（kill -9 后 resume，幂等键各 1 条、marker 各 1 个、状态收敛 done）；TUI 8 headless 用例绿 + 真实库实跑 12 工厂多轮轮询无 traceback。

## M139-A · 崩溃恢复 E2E（W1）

现状地基（M136-A 已落地）：`factory_events` append-only 表 + 幂等键；`factory_start`/`task_start`/`task_done` 均有幂等键；task 完成副作用（completed 追加/worktree 合并/quality 打分/memory）由 `{factory_id}:{task_id}:done` 查重跳过（factory_loop.py L1317-1383）。

子任务：
1. **调查补漏**：resume（`run_factory_loop(factory_id=X)` → `load_factory_state`）后，崩溃时处于 running 的 task 如何被重置/重跑。预期行为：task 体重跑可接受，副作用必须幂等查重。用测试固化该行为。
2. **进程内崩溃集成测试**：orchestrator_fn 在第 N 个 task 抛异常模拟崩溃 → 同 factory_id resume → 断言：factory done、completed 无重复、factory_events 中每 task 的 task_done 仅 1 条、context_summary/memory 副作用不重复追加。
3. **真实 kill -9 E2E**：`scripts/e2e_crash_resume.py`——子进程跑 factory loop（文件标记型慢 orchestrator：每 task 写 marker 文件 + sleep，无 LLM 依赖）→ 父进程 kill -9 → resume 子进程（快速 orchestrator）→ 断言 marker 文件每 task 恰好 1 个、task_done 事件无重复、退出码 0。配 `scripts/verify_m139_crash_resume.sh` 一键复跑。
4. 验收：新测试全绿 + 脚本实跑输出留存；全量 pytest 零回归。

## M139-B · 全屏 TUI 监控台（W2）

数据源：`data/flipped.db`（env `FLIPPED_DB` 可覆盖）的 `factory_states` + `factory_events`（`event_log.list_events(after_seq=...)` 增量轮询）。只读观察者，不侵入运行中 loop，跨进程可用。

子任务：
1. `pip install textual`（venv）；新增 `src/tui/` 包（`__init__.py` / `app.py` / `__main__.py`）。
2. 面板：Header（factory 状态/进度）、事件流（kind 着色滚动）、roadmap 任务进度、Footer 快捷键（q 退出 / p 暂停轮询）。轮询 ~1s；DB 不存在/为空显示空态不崩溃。
3. 入口：`PYTHONPATH=src python -m tui`。
4. 测试：Textual `App.run_test()` pilot API 确定性测试——空库空态 / 写入事件后渲染 / after_seq 增量不重复 / 畸形 payload 不崩 / 暂停恢复。
5. 验收：新测试全绿 + 全量零回归；实跑导出文本快照佐证（`textual` headless 导出）。

---

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
