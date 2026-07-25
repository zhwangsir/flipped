# flipped · 系统性循环测试计划（TEST_PLAN.md）

> 目标：建立可持续运行的「测试→采集→分析→修复→复测」循环，用质量门禁卡住回归，
> 用覆盖率趋势驱动补测，用缺陷日志留痕所有问题与修复。每轮循环都产出可复跑的证据。
>
> 范围：flipped 全栈——Python 后端（src/：api/driving/executor/metrics/tools/tui）+
> 前端 console（React/Vite/TS）+ TUI（Textual）+ 集成（FastAPI + WS + 真实 uvicorn）。
>
> 更新节奏：每轮循环结束后追加「Round N」小节到 TEST_LOG.md，并更新本文件的「当前指标」表。

---

## 1. 测试阶段分层

四层从快到慢、从确定性到真实环境。每层有明确入口、退出条件与证据留痕。

### L1 · 单元测试（Unit）
- **目标**：单个函数/类的确定性逻辑，无外部依赖（无网络/无磁盘 IO/无真实 LLM）。
- **入口**：
  - Python：`PYTHONPATH=src .venv/bin/python -m pytest tests/test_*.py -q`（排除集成标记）
  - 前端：`cd console && npx vitest run`（jsdom）
- **覆盖对象**：`driving/orchestrator`、`driving/approval`、`driving/safety`、`driving/model_router`、
  `api/schemas`、`api/assistant`（纯函数段）、`metrics`、`tools/*` 纯逻辑、前端 `lib/*`、`store`、`router`。
- **退出条件**：100% 通过（skip 仅限外网环境性，需带 `_reachable` 门控）。
- **证据**：终端输出贴 TEST_LOG.md。

### L2 · 集成测试（Integration）
- **目标**：多模块协作 + 真实 FastAPI/WS/SqliteSaver，但 LLM/Worker 可 mock。
- **入口**：
  - `tests/test_api_*.py`（TestClient + 真实 app + mock orchestrator）
  - `tests/test_assistant_approval_resume.py`（LangGraph checkpoint + interrupt/resume）
  - `tests/test_orchestrator_stream.py`（streaming 节点 + 事件总线）
  - `console/src/terminal/terminal.ws.test.ts`（真实 uvicorn + pty + headless xterm）
- **退出条件**：100% 通过。
- **证据**：终端输出 + 关键断言行号。

### L3 · 系统测试（System / End-to-End）
- **目标**：真实后端 + 真实前端 + 真实 WS，完成一个用户任务全链路。
- **入口**：
  - `scripts/verify_assistant.sh`（起 :8151 → 创建 session → 发消息 → WS 收事件）
  - `scripts/verify_milestone_*.sh`（既有里程碑验收脚本）
  - `scripts/e2e_m147_10tasks.py`（10 任务工厂 E2E，需集群，标记 hardware-gated）
- **退出条件**：mock 模式全绿；集群 E2E 标 blocked-by-hardware 不计入硬门禁。
- **证据**：脚本 stdout + /tmp 日志路径。

### L4 · 回归测试（Regression）
- **目标**：新改动不破坏既有功能。全量跑，不做选择性筛选。
- **入口**：
  - `PYTHONPATH=src .venv/bin/python -m pytest tests/ -q`（全量 1600+）
  - `cd console && npx vitest run`（全量 78）
  - `cd console && npx tsc --noEmit && npm run build`（类型 + 产物）
- **退出条件**：Python passed 数 ≥ 上一轮（不允许下降）；前端 78/78；tsc 0 错；build 成功。
- **证据**：passed/skipped/failed 计数 + 与上轮 diff。

---

## 2. 测试用例矩阵

按「功能点 × 测试类型 × 边界/异常」组织。每行一个用例簇，标注当前覆盖状态。

### 2.1 后端核心（src/driving + src/api）

| 功能点 | 正常路径 | 边界条件 | 异常场景 | 状态 |
|---|---|---|---|---|
| Supervisor 调度 | 拆子任务→worker→overseer→verify | iteration 上限/loop_threshold 触发 | worker_error 快速失败 + relay 接力 | ✅ test_orchestrator |
| 审批门禁 | 高风险→interrupt→approve→resume | reject→回 supervisor 重规划 | 无 checkpoint resume / 已完成 resume | ✅ test_assistant_approval_resume |
| 循环检测 | 同签名 ≥3 次→中断 | 跨迭代新签名重置计数 | OpenHands 事件序列签名 | ✅ test_orchestrator_loop |
| 上下文压缩 | 超 max_context_tokens→压缩 | keep_recent 保留最近 N 条 | 压缩后 checkpoint 续跑 | ✅ test_context_manager |
| 崩溃恢复 | SqliteSaver checkpoint 续跑 | 半跑态(crash 后 stream+break) | interrupt vs crash 精确判定 | ✅ test_api_recovery |
| 模型路由 | proxy 健康→走 proxy | proxy 不可达→直连 exo | 全不可达→best-effort | ✅ test_model_router |
| 单模型 fallback | 全角色默认 GLM-5.2-fp8 | env 覆盖单角色 | 未知 alias 透传 | ✅ test_assistant_single_model |
| 安全护栏 | 安全命令放行 | is_safe_command 边界 | 密钥泄漏检测 | ✅ test_safety |
| assistant API | 创建/发消息/审批/历史 | 404 守卫 / 409 重复派发 | mode 非法 / approval 无 pending | ✅ test_assistant_api |
| 工厂循环 | planner→task 派发→verify | RCA 失败计数 / 质量趋势 | factory_loop 异常隔离 | ✅ test_factory_* |

### 2.2 前端 console

| 功能点 | 正常路径 | 边界条件 | 异常场景 | 状态 |
|---|---|---|---|---|
| hash 路由 | #/→Assistant / #/factory→工厂 shell | hash 空 / 未知 hash | hashchange→store 同步 | ✅ App.test |
| Assistant 视图 | user/assistant 气泡 + 工具卡 | 空态 hero / 审批内联 | slash 命令未接线（静默忽略，不假装成功） | ✅ Assistant.test |
| Composer | Enter 发送 / Shift+Enter 换行 | 空输入不发 / busy 禁用 | slash 补全 5 项 | ✅ composer.test |
| ToolCard | running spinner / ok 折叠 / error 展开 | 点击展开切换 | error 自动展开 | ✅ tool-card.test |
| 会话列表 | 创建/选择/删除 | 多项目分组 | 删除后选中回退 | ✅ FactoryPanel/Conversation.test |
| 终端 WS | 数据通路 + UTF-8 + resize | 400 行洪泛 | marker 回归 | ✅ terminal.ws.test |

### 2.3 缺口（P1 待补，循环测试逐轮消化）

| 缺口 | 影响 | 计划 |
|---|---|---|
| browser.py / terminal.py 0% 覆盖 | 真实浏览器/pty 桥无单测 | Round 2+ 补 stub 单测 |
| 前端整体 29% lines | 多数 panel 未测 | Round 2+ 补 FailurePanel/ContextPanel |
| /compact /mode /help /files slash | Assistant 仅 /clear 落地 | 待功能实现后补 |
| "Always" 持久化审批 | 仅单次决策 | 待后端 rules 端点 |
| token 级流式 | 仅 step 级事件 | M152 |

---

## 3. 质量门禁标准（Quality Gates）

`scripts/quality_gate.sh` 强制执行。任一不满足 → 退出码 1，阻断「循环通过」。

### 3.1 测试通过率门禁
| 指标 | 阈值 | 说明 |
|---|---|---|
| Python pytest 通过率 | = 100%（passed/(passed+failed)） | skip 需带 `_reachable` 门控，不计失败 |
| Python passed 数 | ≥ 上一轮基准 | 不允许回归下降 |
| 前端 vitest 通过率 | = 100% | 78/78 |
| tsc --noEmit | 0 错误 | 类型安全 |
| vite build | 成功 | 产物可生成 |

### 3.2 覆盖率门禁（floor，硬强制）
| 指标 | floor | 当前基线 | 目标（追踪，非硬门禁） |
|---|---|---|---|
| Python TOTAL coverage | ≥ 80% | 82% | 85% |
| 前端 lines | ≥ 28% | 29.36% | 50% |
| 前端 statements | ≥ 28% | 29.36% | 50% |
| 前端 branches | ≥ 35% | 74.95% | 80% |
| 前端 functions | ≥ 40% | 43.52% | 60% |

> floor = 当前基线 - 小余量，防回归；目标 = 逐轮抬升的 aspirational 值。
> 每轮循环结束后，若实际值持续高于 floor，可把 floor 上调 1-2% 收紧门禁。

### 3.3 缺陷门禁
| 指标 | 阈值 |
|---|---|
| P0 严重缺陷（阻断核心功能） | 0 个 open |
| P1 高优缺陷（功能受损但有 workaround） | ≤ 2 个 open |
| 缺陷修复率（本轮发现本轮修） | ≥ 80% |
| 同一缺陷复发 | 0（复发 = 门禁失败，需根因分析） |

### 3.4 退出码语义
- `0` = 全部门禁通过，可进入下一轮 / 可发布
- `1` = 有门禁未通过，必须修复后重跑

---

## 4. 循环测试协议

`scripts/loop_test.sh` 驱动。每轮独立、可复跑、留痕。

### 4.1 单轮流程
```
Round N:
  1. 跑 quality_gate.sh → 采集 passed/coverage/缺陷
  2. 若门禁全绿 → 记录指标，Round N 通过，进入 Round N+1（或收尾）
  3. 若有失败 → 分析根因 → 记 DEFECT_LOG.md → 修复 → 重跑 quality_gate.sh
     └─ 同一缺陷修 ≥3 次仍失败 → 触发循环熔断（AGENTS.md §6），停止上报
  4. 每轮结束追加 TEST_LOG.md「Round N」小节 + 更新本文件「当前指标」表
```

### 4.2 轮次预算
- 默认 3 轮（可 `loop_test.sh 5` 指定）。
- 连续 2 轮全绿 + 无新缺陷 → 提前收尾，标记「循环测试通过」。
- 单轮超时 30 分钟 → 强制停止，记录卡点。

### 4.3 熔断条件（AGENTS.md §6 对齐）
- 同一 bug 修复 ≥3 次仍失败 → 停止，上报。
- 连续 2 轮无 measurable 进展（passed 数不升、coverage 不升） → 停止，上报。
- 缺少必要凭据/集群 → 标 blocked-by-hardware，不计入硬门禁。

---

## 5. 缺陷跟踪格式（DEFECT_LOG.md）

每条缺陷结构化记录，便于趋势分析与复发检测。

```markdown
### D-NNNN · <标题>
- **发现轮次**：Round N
- **严重级别**：P0 / P1 / P2 / P3
- **类型**：功能 / 边界 / 异常 / 性能 / 安全 / 回归
- **现象**：<预期 vs 实际>
- **复现**：<命令/用例>
- **根因**：<分析>
- **修复**：<commit/文件>
- **验证**：<重跑结果>
- **状态**：fixed / open / wontfix
- **复发次数**：0
```

字段说明：
- `严重级别`：P0 阻断核心 / P1 功能受损 / P2 体验问题 / P3 优化建议
- `复发次数`：同一根因再次出现 → +1，触发熔断检查
- `状态`：fixed（已修+验证）/ open（待修）/ wontfix（显式记录不修的原因）

---

## 6. 当前指标（每轮更新）

| 指标 | Round 0 基线 | Round 1 | Round 2 | verify-post-fix |
|---|---|---|---|---|
| Python passed | 1639 | 1639 | 1639 | 1639 |
| Python skipped | 7 | 7 | 7 | 7 |
| Python coverage | 82% | 82.89% | 82.84% | 82.86% |
| 前端 passed（用例数） | 78 | 78* | 78* | 78 |
| 前端 lines cov | 29.36% | 29.36% | 29.36% | 29.36% |
| tsc | 0 错 | 0 错 | 0 错 | 0 错 |
| build | 成功 | 成功 | 成功 | 成功 |
| P0 open | 0 | 0 | 0 | 0 |
| P1 open | 0 | 0 | 0 | 0 |

> Round 0 = M151 验收后基线（2026-07-25）。R1/R2/verify 实跑数据。
> \* R1/R2 当时 fe_passed 记 12（vitest "Test Files" 行文件数，解析 bug），实际用例数 78；verify 轮修复后准确（剥离 ANSI + 取 Tests 行）。
> 循环测试结论：连续 2 轮全绿 + 无新缺陷 → R2 后提前收尾，循环测试通过。D-0001 缺陷已 fixed + 加 G0 守卫根治。

---

## 7. 工具清单

| 工具 | 路径 | 作用 |
|---|---|---|
| quality_gate.sh | scripts/quality_gate.sh | 跑全量测试 + 覆盖率 + 门禁判定 |
| loop_test.sh | scripts/loop_test.sh | 多轮循环驱动 + 缺陷记录 |
| verify_assistant.sh | scripts/verify_assistant.sh | M151 端到端验收 |
| .coveragerc | .coveragerc | Python 覆盖率配置（fail_under=80） |
| vitest.config.ts | console/vitest.config.ts | 前端覆盖率配置（thresholds） |
| DEFECT_LOG.md | DEFECT_LOG.md | 缺陷流水 |
| TEST_LOG.md | TEST_LOG.md | 每轮测试证据流水 |
