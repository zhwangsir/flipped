# 自主开发一体式工厂 · 路线图

> 目标:把 flipped 打造成**真正意义上可自主循环开发**的 AI 工厂 —— 用户给一个目标,系统自己拆解 → 写码 → 跑测 → 修错 → 循环直到验收通过,全程可见、可控、可续跑。
>
> 本文档是 `/loop` 自主推进的持久骨架:每轮挑一个最高价值增量,实现→验证→提交→更新 STATE→下一轮。

## 参考工具 → 借鉴的长处

| 工具 | 核心长处 | 映射到 flipped |
|------|---------|---------------|
| **Devin** | 端到端自主(plan→code→test→fix→loop)、自我验证、长时程 | orchestrator 多 Agent 循环 + 真实验证探测 |
| **Qoder** (Quest) | 仓库 wiki/记忆、长时程 agentic quest | 仓库记忆(RAG 自动索引活动项目) + spec 驱动 |
| **Windsurf** (Cascade) | 实时 agentic flow、memories、live preview | 循环事件流式推送 + 浏览器实时预览 |
| **Cursor** (Composer/Agent) | 代码库索引、.cursorrules、多文件 apply | RAG 索引 + 项目规则文件 |
| **Claude Code** | plan mode、subagent、hooks、MCP、TODO 追踪、CLAUDE.md 记忆 | 规划模式(有) + subagent=orchestrator + MCP(有) + 计划清单 + AGENTS.md 规则 |
| **TRAE** (SOLO) | 上下文工程、@ 提及、builder | 上下文 + @ 提及(有) |
| **Codex** | 云端任务委派、PR 生成、沙盒自主 | Docker 沙盒(有) + PR 生成(future) + UI(有) |
| **CodeBuddy** (Craft) | 多 Agent craft | Supervisor/Worker/Overseer(有) |
| **KimiCode** | 长上下文 coder 模型 | 执行者模型(有) |

## 现状盘点(已有的强项)

后端 `drive_orchestrated(goal, cwd, verify_cmd)` 已实现:
- **Supervisor(GLM)** 拆下一步子任务(干净上下文,不污染)
- **Worker(OpenHands/Kimi)** 在 Docker 沙盒执行
- **Overseer(GLM)** 分层监督:确定性预检(循环检测)+ GLM 方向判断 → continue/replan/abort
- **强制 Verify** 跑验收命令判定 done
- **checkpoint 崩溃恢复 / 审批中断 / 上下文压缩 / 循环检测 / 熔断**

这已经比多数工具的循环更完备。缺的是"最后一公里"让它成为**用户可一键驱动、全程可见**的工厂。

## 六大增量(按优先级)

> **状态(2026-07-04):F1–F6 全部完成 ✅**。自主循环已可用:选「自主」模式 + 给目标 →
> 探测怎么验证 → 读项目规则/结构 → 拆子任务(实时计划卡)→ 沙盒执行(轨迹上屏)→
> 监督 → 沙盒跑真测判定 → 循环。后端 190 tests 全绿。
> 下一阶段(F7+):交付步(验收通过后沙盒内自动 commit)/并行线程/端到端真机(需 exo LAUNCH 模型)。

### F1 · 真实自我验证 【地基】✅ 完成
`verify_cmd` 默认 `["true"]`(永远通过)= 循环空转,自主开发是假的。
- **F1a** 验证命令探测器:读项目文件 → 推断测试/构建命令(pytest / npm test / cargo test / go test / make test …)。纯函数,完全可测。✅
- **F1b** `GET /project/verify` 端点:活动项目的探测结果(命令 + 来源 + 置信度)。
- **F1c** 自主模式接线:orchestrator 的 verify_cmd 用探测结果,不再手填。
- **F1d** 验证在正确位置跑(沙盒/host bind-mount 目录),修 `_safe_default_verifier` 的 cwd 语义。

### F2 · 透明的实时循环 ✅ 完成
`orchestrator_stream.py` 把 Supervisor/Worker/Overseer/Verify 每步产出即 emit WS 事件(去 NullEventBus 黑盒)。

### F3 · 一等「自主」模式 ✅ 完成
composer `mode=auto`;`_select_runner` 路由到 orchestrator,自动探测验证命令,无需手配。

### F4 · 实时计划清单(可见脊柱)✅ 完成
`PlanTracker`(后端 emit `plan` 事件)+ `PlanCard`(前端钉流顶,状态图标 ✓/⟳/↻/✗ + 计数)。

### F5 · 仓库记忆(Qoder wiki / Cursor 索引)✅ 完成
`repo_map.py` 把活动项目压成紧凑结构地图(技术栈/目录布局)喂 Supervisor。选确定性结构地图而非
语义 RAG:Supervisor 需布局感知,语义检索对 Worker 更有用而 Worker(OpenHands)已能探索沙盒。

### F6 · 项目规则文件(AGENTS.md / .cursorrules / CLAUDE.md)✅ 完成
`project_rules.py` 读项目根规则文件(AGENTS.md/CLAUDE.md/.cursorrules/.windsurfrules/…)注入 Supervisor prompt。

## F7+ · 下一阶段(闭环交付与规模化)

- **F7 交付步**:验收通过后在沙盒内自动 `git commit`(生成规范提交信息),给自主开发一个有形产物(Devin/Codex 式)。
- **F8 端到端真机**:exo LAUNCH 双模型后跑一个真实项目全循环验证(当前受基础设施限制)。
- **F9 并行线程 / worktree**:多目标并行,状态板(Codex parallel threads)。
- **F10 成本/预算**:token 预算显示与上限(Devin ACU 式)。

## 验证纪律

- 后端每个增量:pytest 全绿(含新用例),不放宽断言。
- 前端每个增量:tsc + build 绿 + 隔离 Playwright(自带 Chromium,不碰用户浏览器)端到端实测。
- 真实模型端到端受限于 exo 需 LAUNCH 模型(基础设施侧),以注入测试兜底,并如实标注。
- 每轮提交:`<type>: <描述>`,更新 STATE.json 的 current_milestone。
