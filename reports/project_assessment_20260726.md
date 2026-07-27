# flipped 项目能力综合评估报告

**评估时间**：2026-07-26 19:10 CST
**评估方法**：基于实际运行数据、代码静态分析、测试基线、git 历史的多维度评估
**评估范围**：功能完整性 / 性能表现 / 用户体验 / 代码质量 / 可扩展性 / 安全性

---

## 0. 项目定位（一句话）

flipped 是一个**基于双本地 MLX 模型（GLM-5.2 编排 + Kimi-K2.7 执行）的 agentic 自主开发平台**，
fork 自 Roo Code 思路并叠加自定义驾驭层（强制验证、循环检测、上下文压缩、人工审批、子 Agent、
可观测性），通过 MCP 接入联网搜索与 RAG，目标是让 Agent 自主完成多文件编码任务。

---

## 1. 总体评分

| 维度 | 评分 | 量化依据 |
|---|---|---|
| 功能完整性 | **B+** (85/100) | 159 里程碑完成 158（99.4%），M147-A E2E 最后一公里受阻 |
| 性能表现 | **C+** (72/100) | 模型延迟尚可（GLM 1.1s/Kimi 3.1s），但 E2E 长跑 0/8 完成 |
| 用户体验 | **B** (80/100) | 前端 591 测试 + axe-core a11y，但仅 2 路由偏极简 |
| 代码质量 | **B+** (87/100) | py cov 83.67% / fe cov 85.26% / tsc 0 errors，但有 599 LOC 巨函数 |
| 可扩展性 | **B-** (78/100) | 模块化清晰，但缺 Docker/CI，megafile 偏多 |
| 安全性 | **A-** (88/100) | 沙箱分层 + 白名单 + 审批流，无硬编码密钥 |
| **综合** | **B+** (82/100) | 接近产线化但 E2E 端到端打通是最后瓶颈 |

---

## 2. 功能完整性

### 2.1 里程碑完成度（来自 STATE.json）

```
里程碑总数: 159
  done:   158  (99.4%)
  doing:    1  (M147-A 真实工厂 10-task E2E 重跑)
  blocked:  0
  todo:     0
```

**仅剩的 1 个 doing 里程碑**：
- M147-A · 真实工厂 10-task E2E 重跑（M156 双模型恢复：coder=Kimi-K2.7-Code-4bit）
- 已解除的阻碍：M156.14（verify_cmd 引号内 assert 误拦修复，今日 09:00 完成）

### 2.2 已实现的核心能力模块

| 模块 | 路径 | LOC | 状态 |
|---|---|---|---|
| FastAPI 编排 API | [src/api/](file:///Users/wangzhenyu/Desktop/ALLProject/flipped/src/api) | 2,719 | 24+ 路由（factory/assistant/session/terminal/mcp/projects） |
| 驾驭层（orchestrator + factory_loop + safety） | [src/driving/](file:///Users/wangzhenyu/Desktop/ALLProject/flipped/src/driving) | 23,498 | 61 模块，最核心 |
| OpenHands Worker 封装 | [src/executor/openhands_worker.py](file:///Users/wangzhenyu/Desktop/ALLProject/flipped/src/executor/openhands_worker.py) | 549 | 容器路径翻译 + thinking 开关 + 精简 SP |
| MCP Server | [src/mcp_server/](file:///Users/wangzhenyu/Desktop/ALLProject/flipped/src/mcp_server) | 241 | 自身作为 MCP 服务端暴露能力 |
| RAG 知识库 | [src/rag/](file:///Users/wangzhenyu/Desktop/ALLProject/flipped/src/rag) | 265 | ChromaDB 向量库 + ingest |
| 联网工具 | [src/tools/](file:///Users/wangzhenyu/Desktop/ALLProject/flipped/src/tools) | 575 | unified_browser + web_search |
| 指标采集 | [src/metrics/](file:///Users/wangzhenyu/Desktop/ALLProject/flipped/src/metrics) | 167 | collector 模块 |
| TUI 终端 UI | [src/tui/](file:///Users/wangzhenyu/Desktop/ALLProject/flipped/src/tui) | 1,087 | 命令行交互 |
| 前端 Console | [console/src/](file:///Users/wangzhenyu/Desktop/ALLProject/flipped/console/src) | 14,736 | React 18 + Vite 5 + Tauri 2 |

### 2.3 数据持久化（[data/flipped.db](file:///Users/wangzhenyu/Desktop/ALLProject/flipped/data/flipped.db)）

8 张表，已有真实数据积累：
| 表 | 行数 | 用途 |
|---|---|---|
| skills | 43 | 已注册技能 |
| gold_memory | 3,565 | 成功模式复用记忆 |
| writes | 4,978 | 文件写入记录 |
| checkpoints | 939 | 长跑断点 |
| failures | 1,244 | 失败知识库 |
| factory_states | 20 | 工厂运行状态 |
| factory_events | 167 | 事件流 |

### 2.4 不足

1. **E2E 端到端 0/8 完成**：M147-A 最近一轮跑 31 分钟，8 个任务全 `circuit_breaker`
   （根因已定位修复，第三轮可重跑验证）
2. **M147-A 之后的产线化里程碑（M5 硬化）未见进展**：性能调优、崩溃恢复、断点续跑、
   密钥管理、命令白名单收紧等产线级要求未系统化覆盖

---

## 3. 性能表现

### 3.1 模型延迟（heartbeat 实测）

| 模型 | 角色 | 延迟 | 状态 |
|---|---|---|---|
| GLM-5.2-fp8 | 编排者/架构师 | 1.1s | ✅ |
| Kimi-K2.7-Code-4bit | 执行者/码农 | 3.1s | ✅ |

### 3.2 Worker 任务耗时（M156.13 smoke 实测）

| 任务类型 | 耗时 | 备注 |
|---|---|---|
| 创建 `__init__.py` | 45.7s | OpenHands SDK 完整一轮 |
| 创建 `cli.py` + argparse + 自测 | 54.6s | 含 worker 自带 self-test |
| 创建 `config.py` | ~30s | 简单模块 |

### 3.3 已知性能瓶颈

1. **GLM planner 180s 超时**（KI-20260721-m147a-glm-bottleneck）：
   复杂 default_planner prompt 让 GLM-5.2-fp8 thinking 超时，fail-open 生成 8 个
   确定性任务而非 planner 拆的 2 个
2. **task_timeout 300s 太短**：worker 30s 完成，但 verify 后的 RCA 调 GLM 又花
   180s → 超出 300s task 预算
3. **E2E 整轮 31 分钟，0 任务完成**：实际是 verify_cmd 白名单 bug 导致，不是性能问题

### 3.4 测试执行性能

| 测试套件 | 耗时 | 通过率 |
|---|---|---|
| pytest 全量 | 152.31s（2分32秒） | 1697/1699 = 99.88% |
| vitest 全量 | 7.92s | 591/591 = 100% |
| tsc -b | <1s | 0 errors |
| vite build | 645ms | ok |

### 3.5 不足

- **无性能基准测试**：没有 `tests/perf/` 或 benchmark 套件
- **无压测数据**：API 并发能力未知
- **bundle 544KB**：[console/src/](file:///Users/wangzhenyu/Desktop/ALLProject/flipped/console/src) 主 chunk 超过 500KB 警告阈值，未做 code-splitting

---

## 4. 用户体验

### 4.1 前端架构

- **栈**：React 18.3.1 + Vite 5.4.11 + TypeScript 5.6.3 + Tauri 2.11.1
- **路由**：极简 hash 路由（[console/src/router.ts](file:///Users/wangzhenyu/Desktop/ALLProject/flipped/console/src/router.ts)），不引 react-router
- **状态管理**：自研 store（[console/src/store.tsx](file:///Users/wangzhenyu/Desktop/ALLProject/flipped/console/src/store.tsx)）
- **终端**：xterm.js 5.5.0 + addon-fit
- **依赖数**：dependencies=6（极简）/ devDependencies=16

### 4.2 路由与视图

仅 2 个路由：
- `#/` → Assistant（默认，对话视图）
- `#/factory` → Factory（工厂 shell）

**14 个组件**：CommandPalette / ContextPanel / Conversation / FactoryPanel /
FailurePanel / Launcher / PlanCard / Plugins / PtyTerminal / ResizeHandle 等
（每个都配同名 `.test.tsx`）

### 4.3 可访问性（a11y）

- ✅ `@axe-core/playwright@^4.12.1` 在 devDeps
- ✅ 测试中含 a11y lint 模块（[src/driving/a11y_lint.py](file:///Users/wangzhenyu/Desktop/ALLProject/flipped/src/driving/a11y_lint.py)）
- ✅ 设计系统有 design tokens（[console/src/styles/tokens.css](file:///Users/wangzhenyu/Desktop/ALLProject/flipped/console/src/styles/tokens.css)）

### 4.4 设计系统

来自 STATE.json 的 design_context：
- 暗黑模式 Dark Mode（参考 Linear/GitHub Dark/Vercel/Superhuman）
- 配色：accent #0A84FF / bg #0D0D12 / surface #1E1E2E / text #F5F5F5
- 字体：Inter（标题 48px/700，正文 16px/400）
- 响应式：mobile <768px / tablet 768-1024px / desktop >1024px
- WCAG AA 对比度要求

### 4.5 不足

1. **路由过少**（仅 2 个）：复杂场景下用户导航受限，未来扩展需引入 react-router
2. **无 Storybook**：组件 isolated 开发/文档化不足
3. **无 PWA**：离线能力缺失
4. **bundle 544KB 未拆分**：首屏加载可优化

---

## 5. 代码质量

### 5.1 测试覆盖

| 指标 | 数值 | 阈值 | 状态 |
|---|---|---|---|
| Python 测试通过 | 1697/1699 | - | ✅ 99.88% |
| Python 覆盖率 | 83.67% | ≥80% | ✅ |
| Frontend 测试通过 | 591/591 | - | ✅ 100% |
| Frontend 行覆盖 | 85.26% | - | ✅ |
| TypeScript 错误 | 0 | 0 | ✅ |
| 测试代码 LOC | 31,162（py）+ 7,752（fe） | - | 测试/源码比 1.06x / 0.52x |

### 5.2 复杂度热点（函数级）

```
599 LOC  factory_loop.py:1728 run_factory_loop     ← 巨函数，需拆分
361 LOC  design_context.py:4656 lint_design_quality
356 LOC  orchestrator.py:759 local_worker
268 LOC  orchestrator.py:1273 build_orchestrator
240 LOC  design_context.py:5019 design_score
```

### 5.3 复杂度热点（文件级）

```
5258 LOC  src/driving/design_context.py    ← megafile
2347 LOC  src/driving/factory_loop.py
1663 LOC  src/driving/orchestrator.py
```

[src/driving/design_context.py](file:///Users/wangzhenyu/Desktop/ALLProject/flipped/src/driving/design_context.py)
单文件 5258 LOC 是显著的代码异味，建议按职责拆分（tokens / lint / score / fix）。

### 5.4 Git 提交质量

- **30 天 commits**：215 次（日均 ~7 次，节奏稳定）
- **commit 信息规范**：均带 `feat/fix/chore(mXX)` 前缀，可追溯
- **峰值**：7/11 当天 61 次（M149 大调整）

### 5.5 文档完备度

- ✅ [AGENTS.md](file:///Users/wangzhenyu/Desktop/ALLProject/flipped/AGENTS.md) 总控提示词
- ✅ [STATE.json](file:///Users/wangzhenyu/Desktop/ALLProject/flipped/STATE.json) 状态外置
- ✅ [TEST_LOG.md](file:///Users/wangzhenyu/Desktop/ALLProject/flipped/TEST_LOG.md) 测试证据流水
- ✅ [TEST_PLAN.md](file:///Users/wangzhenyu/Desktop/ALLProject/flipped/TEST_PLAN.md) 测试计划
- ✅ [DEFECT_LOG.md](file:///Users/wangzhenyu/Desktop/ALLProject/flipped/DEFECT_LOG.md) 缺陷日志
- ✅ [.env.example](file:///Users/wangzhenyu/Desktop/ALLProject/flipped/.env.example) 环境变量文档
- ❌ 未见 README.md / ARCHITECTURE.md / CONTRIBUTING.md

### 5.6 不足

1. **megafile**：design_context.py 5258 LOC 应拆分
2. **巨函数**：run_factory_loop 599 LOC 难维护，应提取 helper
3. **缺 README**：项目入口文档缺失，新人上手成本高
4. **测试/源码比偏低（fe）**：前端 0.52x，可提升

---

## 6. 可扩展性

### 6.1 架构边界清晰

```
src/api/           ← FastAPI 路由层（24+ endpoints）
src/driving/       ← 驾驭层（orchestrator + factory_loop + safety + rca + ...）
src/executor/      ← Worker 执行层（OpenHands 封装）
src/mcp_server/    ← MCP 服务端（对外暴露能力）
src/rag/           ← RAG 知识库
src/tools/         ← 联网工具
src/metrics/       ← 指标采集
src/tui/           ← TUI 终端 UI
console/src/       ← React 前端
```

层次清晰，每层职责单一，便于水平扩展。

### 6.2 模型路由可配置

[src/driving/model_router.py](file:///Users/wangzhenyu/Desktop/ALLProject/flipped/src/driving/model_router.py) 支持：
- 多模型分工（architect / coder / supervisor / overseer / monitor）
- 环境变量覆盖（`FLIPPED_ARCHITECT_MODEL` / `FLIPPED_CODER_MODEL` 等）
- LiteLLM proxy 统一路由 + 降级

### 6.3 不足

1. **无 Dockerfile**：仅 [infra/searxng/docker-compose.yml](file:///Users/wangzhenyu/Desktop/ALLProject/flipped/infra/searxng/docker-compose.yml) 一个容器化文件，
   主应用未容器化，部署可移植性差
2. **无 CI/CD**：未见 `.github/workflows/`，质量门禁全靠本地 [scripts/quality_gate.sh](file:///Users/wangzhenyu/Desktop/ALLProject/flipped/scripts/quality_gate.sh)
3. **依赖面大**：venv 421 个包，攻击面与升级成本高
4. **SQLite 单机**：[data/flipped.db](file:///Users/wangzhenyu/Desktop/ALLProject/flipped/data/flipped.db) 单文件，多实例并发受限
5. **无水平扩展设计**：EventBus 是进程内，跨节点广播需引入 Redis adapter

---

## 7. 安全性

### 7.1 沙箱分层（AGENTS.md §7）

- ✅ **沙箱边界明确**：沙箱内自由跑，沙箱外要审批
- ✅ **git 分支隔离**：每里程碑独立分支
- ✅ **审批断点**：高风险动作（push/merge/花钱 API/删数据/密钥）强制人工审批

### 7.2 命令安全（[src/driving/safety.py](file:///Users/wangzhenyu/Desktop/ALLProject/flipped/src/driving/safety.py)）

- ✅ **9 条 DANGEROUS_PATTERNS**：rm -rf / mkfs / dd if=/dev/ / curl|sh / wget|sh /
  nc -e / bash -i / python -c socket / sudo
- ✅ **56 个 SAFE_BASE_COMMANDS** 白名单
- ✅ **M156.14 修复**：shlex 重写切分逻辑，引号内操作符不再误切
- ✅ **退化路径**：shlex 解析失败时保守退化到旧逻辑

### 7.3 密钥管理

- ✅ [.env](file:///Users/wangzhenyu/Desktop/ALLProject/flipped/.env) 在 [.gitignore](file:///Users/wangzhenyu/Desktop/ALLProject/flipped/.gitignore)（`^\.env$` 和 `^\.env.*`）
- ✅ [.env.example](file:///Users/wangzhenyu/Desktop/ALLProject/flipped/.env.example) 文档化所有变量
- ✅ 硬编码密钥扫描：1 处发现（误报，是 model_router.py 注释里的 "dummy" 字样）
- ✅ `git log --all -- .env` 无历史泄漏

### 7.4 会话与审批

- ✅ [src/api/session.py](file:///Users/wangzhenyu/Desktop/ALLProject/flipped/src/api/session.py) 实现 session 管理 + approval flow
- ✅ 终端命令审计：[src/driving/safety.py:audit_openhands_events](file:///Users/wangzhenyu/Desktop/ALLProject/flipped/src/driving/safety.py)

### 7.5 不足

1. **无真实认证**：API 假定 localhost 信任，无 JWT/OAuth
2. **无 rate limiting**：FastAPI 未配限流
3. **无 CSRF/CSP**：前端缺 Content Security Policy
4. **CORS 未审计**：未检查 FastAPI CORS 配置
5. **`SAFETY_ALLOW_UNSAFE_COMMANDS=1` 测试逃生门**：生产环境必须确保未设

---

## 8. 可观测性

### 8.1 已有

- ✅ **心跳监控**（[scripts/heartbeat.py](file:///Users/wangzhenyu/Desktop/ALLProject/flipped/scripts/heartbeat.py)）：每 10 分钟一次，含 STATE/git/模型/测试基线/偏差分析
- ✅ **结构化日志**：[src/driving/structured_logger.py](file:///Users/wangzhenyu/Desktop/ALLProject/flipped/src/driving/structured_logger.py)
- ✅ **指标采集**：[src/metrics/collector.py](file:///Users/wangzhenyu/Desktop/ALLProject/flipped/src/metrics/collector.py)
- ✅ **RCA 系统**：[src/driving/rca.py](file:///Users/wangzhenyu/Desktop/ALLProject/flipped/src/driving/rca.py) 失败根因分类
- ✅ **stuck_detector**：循环检测
- ✅ **质量历史**：quality_metrics_history.jsonl

### 8.2 不足

1. **无分布式追踪**：M3 路线图提到的 LangSmith/OTel 未接入
2. **无 Prometheus/Grafana**：指标未导出到标准监控系统
3. **无 Sentry**：错误追踪仅本地日志
4. **无 ELK/Loki**：日志未集中

---

## 9. 改进建议（按优先级）

### P0（关键阻碍，立即做）

1. **跑通 M147-A E2E 第三轮**：M156.14 修复后，8 条 verify_cmd 全部放行，重跑应能完成 6-8 任务
   ```bash
   nohup .venv/bin/python -u scripts/e2e_m147_10tasks.py \
     > /tmp/e2e_m147_round3.log 2>&1 &
   ```

2. **更新 known_issues 状态**：KI-20260726-verify-assert-whitelist 已由 M156.14 解决，
   应标记为 resolved（当前仍 open）

### P1（产线化前置，1-2 周）

3. **解决 GLM planner 180s 超时**（KI-20260721）：
   - 简化 default_planner prompt（减少 token）
   - 或换 Kimi 当 planner（Kimi 速度更快）
   - 或独立 RCA 调用超时（不继承 GLM 180s）

4. **拆分 megafile**：[src/driving/design_context.py](file:///Users/wangzhenyu/Desktop/ALLProject/flipped/src/driving/design_context.py) 5258 LOC → 按职责拆 4-5 个文件

5. **拆分巨函数**：`run_factory_loop` 599 LOC → 提取 _plan/_execute/_verify/_checkpoint helpers

6. **加 README.md**：项目入口、快速启动、架构图

### P2（产线化，2-4 周）

7. **容器化主应用**：写 Dockerfile + docker-compose，把 dev_up.sh 容器化
8. **接 CI/CD**：GitHub Actions 跑 quality_gate.sh，PR 必须门禁全绿
9. **接入 LangSmith 或 OTel**：M3 路线图承诺的 tracing
10. **前端 code-splitting**：544KB 主 chunk 拆分

### P3（增强，长期）

11. **API 认证 + Rate limiting**：JWT + slowapi/Redis 限流
12. **数据库迁移**：SQLite → Postgres（支持多实例）
13. **跨节点 EventBus**：Redis pub/sub adapter
14. **Storybook**：组件文档化
15. **性能基准测试**：`tests/perf/` + benchmark 套件

---

## 10. 量化数据汇总

| 维度 | 指标 | 数值 | 评级 |
|---|---|---|---|
| 完整性 | 里程碑完成率 | 158/159 = 99.4% | A |
| 完整性 | E2E 任务完成率 | 0/8（已修复，待重跑） | F→待验证 |
| 性能 | GLM 延迟 | 1.1s | B |
| 性能 | Kimi 延迟 | 3.1s | B |
| 性能 | Worker 单任务 | 30-55s | B |
| 用户体验 | 路由数 | 2 | C |
| 用户体验 | 组件数 | 14 | B |
| 用户体验 | a11y 工具 | axe-core ✓ | A |
| 质量 | pytest 通过 | 1697/1699 = 99.88% | A |
| 质量 | py 覆盖率 | 83.67% | B+ |
| 质量 | fe 覆盖率 | 85.26% | A- |
| 质量 | tsc 错误 | 0 | A |
| 质量 | 最大单函数 LOC | 599 | D |
| 质量 | 最大单文件 LOC | 5258 | D |
| 扩展性 | 模块化清晰度 | 9 子目录 | B+ |
| 扩展性 | Dockerfile | 0 | F |
| 扩展性 | CI/CD | 无 | F |
| 扩展性 | 依赖数 | 421 venv 包 | C |
| 安全 | 危险模式规则 | 9 | B |
| 安全 | 白名单命令 | 56 | B+ |
| 安全 | 硬编码密钥 | 0 真实 | A |
| 安全 | .env 在 gitignore | ✓ | A |
| 安全 | 真实认证 | 无 | F |
| 可观测 | 心跳监控 | 10min ✓ | A |
| 可观测 | 分布式追踪 | 无 | F |

---

## 11. 结论

flipped 项目**整体处于"接近产线化但最后一公里受阻"的状态**。

**优势**：
- 99.4% 里程碑完成率，工程纪律强（TDD + 全量回归 + 状态外置）
- 双模型架构落地，GLM 编排 + Kimi 执行分工清晰
- 安全沙箱分层完善，AGENTS.md §7 严格执行
- 测试基线健康（py 83.67% / fe 85.26% / tsc 0）
- 30 天 215 commits，节奏稳定

**核心不足**：
- E2E 端到端 0/8 完成（M156.14 已修复，待第三轮验证）
- GLM planner 180s 超时是架构级瓶颈
- megafile + 巨函数影响可维护性
- 缺 Dockerfile / CI/CD / 真实认证 / 分布式追踪

**关键判断**：项目已具备**单机 demo 级**能力，但要达到**产线级**还需 M5 硬化
里程碑的系统化推进。当前最关键的下一步是**跑通 M147-A E2E 第三轮**，验证修复
有效性，然后才能推进 M5 产线化。

---

**评估结束**。
