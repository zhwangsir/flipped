# flipped 测试策略 · 对标 Claude Code / Trae-Agent 可借鉴之处

> 背景：用户要求完成六维度测试策略优化后，参考 Claude Code 与 Trae-Agent 的测试理念，
> 看看 flipped 当前体系有什么可取之处、哪些可以借鉴补强。
>
> 本文不是泛泛对比，而是逐条落到 flipped 的具体文件/脚本/里程碑上，
> 给出"可立即落地"的改进项与优先级。
>
> 写入时间：2026-07-27

---

## 0. 三方测试体系速览

| 维度 | Claude Code | Trae-Agent | flipped（当前） |
|------|-------------|------------|-----------------|
| 核心理念 | Verification Loop（让 Agent 自己验证自己） | 多 Agent 协同 + 规则驱动确定性 | 六维度策略 + quality_gate.sh + 心跳监控 |
| 工作循环 | 9 步：Explore → Plan → CLAUDE.md → Build → Hooks → Tests → Review → Fix → Ship | 8 阶段：需求 → 架构 → UI → **测试设计** → 分解 → 开发 → **测试验证** → 评审 | §2 标准循环：读状态 → 选里程碑 → 写测试 → 写实现 → 跑测试 → commit → 收工 |
| 门禁机制 | Hooks（Command Hook exit 2 阻断 + Stop Hook 收尾门禁） | Validator Agent 强制第二遍 + 规则集 | quality_gate.sh（G1-G5 已有，G6-G10 待落地） |
| 验证复用 | Skill 打包（.claude/skills/verify-*/SKILL.md） | SOLO 模式 + 多角色共识 | scripts/quality_gate.sh + scripts/security_scan.sh |
| 失败信号 | 结构化 JSON（rule + location + expected + actual + suggestedfix + retryable） | 缺陷密度 + 风险等级标注 | DEFECT_LOG.md（半结构化 Markdown） |
| 独立审查 | Review subagent（独立上下文 critic） | 多角色共识评审（架构师+测试+开发者） | orchestrator.py 的 Overseer（跨模型族监督） |

---

## 1. Claude Code 可借鉴之处

### 1.1 ⭐⭐⭐ Verification Loop 打包成 Skill（最高优先级）

**Claude Code 做法**：把"开发者反复手工执行的检查"打包成 `.claude/skills/verify-*/SKILL.md`，每个会话自动应用。Boris Cherny（Claude Code 作者）原话：

> "Probably the most important thing to get great results out of Claude Code: give Claude a way to verify its work. If Claude has that feedback loop, it will 2-3x the quality of the final result."

Skill 的 6 个固定字段：Trigger / Scope / Criteria / Evidence / Repair / Exit。

**flipped 对标**：当前 `scripts/quality_gate.sh` 是 shell 脚本，不是 Skill。Agent 不会主动调用它，必须靠 AGENTS.md 第 §3 节强制提醒。

**落地建议**（P0）：
- 创建 `.claude/skills/verify-quality/SKILL.md`，把六维度门禁打包成 Skill
- Trigger：每个里程碑完成时 / 用户说"完成"时
- Scope：读 `src/` `console/src/` `tests/` `reports/`
- Criteria：`quality_gate.sh` 退出码 0 + coverage ≥ 80% + 0 HIGH bandit
- Evidence：`reports/quality_metrics.json` + `TEST_LOG.md` 追加
- Repair：失败时读 `reports/bandit.json` / `reports/pip-audit.json` 定位
- Exit：连续 2 轮全绿收尾，或 3 轮失败升级人工

**收益**：Agent 从"被提醒才跑门禁"变成"主动跑门禁"，对齐 Claude Code 的核心收益。

### 1.2 ⭐⭐⭐ 结构化失败信号（最高优先级）

**Claude Code 做法**：失败信号必须是结构化 JSON，直接驱动下一步修复：

```json
{
  "status": "fail",
  "rule": "LOG_NO_SECRET_PAYLOAD",
  "location": "src/http/error-handler.ts:42",
  "expected": "requestId exists and payload is absent",
  "actual": "request.body is passed to logger.error",
  "suggested_fix": "remove request.body; keep requestId",
  "retryable": true
}
```

rule + location + expected + actual 把搜索空间压到有限区域，Agent 可以形成修复假设、改最小范围、再跑同一检查。

**flipped 对标**：当前 `DEFECT_LOG.md` 是半结构化 Markdown，`TEST_LOG.md` 是流水账。失败时 Agent 要从长日志里猜发生了什么。

**落地建议**（P0）：
- 升级 `scripts/security_scan.sh` 输出 `reports/findings.jsonl`，每行一个结构化发现
- 升级 `quality_gate.sh` 失败时输出结构化 fail 信号（含 rule/location/expected/actual/suggested_fix/retryable）
- `DEFECT_LOG.md` 新增条目时同步写一条 JSON 到 `reports/defects.jsonl`

### 1.3 ⭐⭐ Hook 强制非协商规则

**Claude Code 做法**：
- Command Hook：读事件 JSON，exit 2 阻断动作，stderr 交回 Agent
- Stop Hook：收尾门禁，但要检查 `stop_hook_active` 防无限循环，设最大循环次数

**flipped 对标**：`quality_gate.sh` 是"软门禁"——Agent 可以选择不跑。AGENTS.md §3 是"文档约束"，不是"代码约束"。

**落地建议**（P1）：
- 在 `scripts/quality_gate.sh` 末尾加 Stop Hook 风格的总门禁：失败时 exit 2 + stderr 给出结构化失败信号
- 配合 1.2 的结构化失败信号，让 Agent 收到 exit 2 后能直接定位修复
- 防无限循环：加 `FLIPPED_MAX_VERIFY_LOOPS=3` 环境变量，超过即升级人工

### 1.4 ⭐⭐ Review Subagent（独立上下文 critic）

**Claude Code 做法**：用一个独立上下文的 Review subagent 审查主 Agent 的产出。它没参与编写，所以不会"自证"。

**flipped 对标**：`orchestrator.py` 的 Overseer 已经是跨模型族监督（GLM 监督 Kimi），但 Overseer 监督的是"效率/方向"，不是"代码质量"。

**落地建议**（P1）：
- 在 `orchestrator.py` 的 Verifier 节点后加一个 `Reviewer` 节点
- Reviewer 用独立上下文（fresh Agent），只读 worker 产出的 diff + 验收结果
- Reviewer 输出结构化 verdict：`{quality_score, issues: [...], approve: bool}`
- 不 approve 则回灌给 Supervisor 重新派发

### 1.5 ⭐ CLAUDE.md 作为"版本化契约"

**Claude Code 做法**：`CLAUDE.md` 不是 notes，是 contract。如果仓库违反它，要么修仓库要么改契约，不让它变成 aspirational（愿望式）。

**flipped 对标**：`AGENTS.md` 已经是契约形态（§1 不可违背的核心原则、§3 测试协议、§7 安全护栏），但部分条目是 aspirational：
- §3 说"不准注释掉测试、不准把断言改宽松" —— 实际靠 Agent 自觉
- §7 说"沙箱内自由跑，沙箱外要审批" —— 实际没有代码级强制

**落地建议**（P2）：
- 把 AGENTS.md 的"不可违背"条目逐条对照代码级强制手段
- 没有强制手段的条目要么补强制（Hook/门禁），要么降级为"建议"
- 避免契约变成愿望式

---

## 2. Trae-Agent 可借鉴之处

### 2.1 ⭐⭐⭐ 独立"测试设计"阶段（先于开发）

**Trae-Agent 做法**：八阶段工作流里，"测试设计"是独立阶段（第 4 阶段），在"任务分解"和"开发实现"之前。测试专家角色先制定测试策略和用例，开发者照着实现。

**flipped 对标**：AGENTS.md §2 标准循环是"写测试 → 写实现"，但实际执行时测试经常被简化（只写 happy path，不写边界/异常）。`orchestrator.py` 的 Supervisor 拆子任务时也不强制要求"先出测试用例"。

**落地建议**（P0）：
- 在 `orchestrator.py` 的 Supervisor 节点输出里强制加 `test_cases: list[str]` 字段
- Worker 执行子任务前，Verifier 先校验测试用例是否覆盖：normal / boundary / error / concurrency
- 测试用例不达标则 Supervisor 重新拆解

### 2.2 ⭐⭐⭐ Validator Agent 强制第二遍

**Trae-Agent 做法**：多 Agent 链路里，Validator Agent 是强制第二遍：Code generation → Run linter + test suite → Architecture review → Documentation check → Refactoring diff。永远不信任 Agent 输出，必须验证。

**flipped 对标**：`orchestrator.py` 的 Verifier 只跑验收命令，不做"代码质量验证"（lint/typecheck/coverage）。

**落地建议**（P0）：
- Verifier 节点升级为"复合验证"：跑验收命令 + 跑 lint + 跑 typecheck + 检查 coverage
- 任一失败即 `verified=False`，回灌给 Supervisor
- 这正是 1.4 Reviewer 节点的简化版（同模型族，但用不同 prompt）

### 2.3 ⭐⭐ Karpathy 四原则强制执行

**Trae-Agent 做法**：v2.4 引入 Karpathy 四原则检查脚本：
- Think Before Coding（先想后写）
- Simplicity First（简单优先）
- Surgical Changes（外科手术式改动，只改必要的）
- Goal-Driven Execution（目标驱动执行）

**flipped 对标**：AGENTS.md §1.3 "小步快跑"、§1.4 "状态外置" 精神一致，但没有代码级检查。

**落地建议**（P1）：
- 创建 `scripts/karpathy_check.py`，检查 git diff 是否符合四原则
  - Surgical Changes：diff 行数 / 文件数比是否合理（如单文件改动 > 200 行告警）
  - Simplicity First：新增依赖是否必要（检查 package.json/pyproject.toml diff）
  - Think Before Coding：commit message 是否含"why"（不只是"what"）
- 集成到 quality_gate.sh 的 G11 门禁

### 2.4 ⭐⭐ SOLO 模式长工作流上下文保持

**Trae-Agent 做法**：长工作流（> 2000 tokens）用 SOLO 架构，保持上下文不腐烂。短任务用标准模式。

**flipped 对标**：AGENTS.md §2.5 "外层执行循环（Ralph 模式）" 已经是 SOLO 思路——每轮起全新上下文，进度活在文件与 git 历史里。但实际执行时单会话经常超长，上下文腐烂。

**落地建议**（P1）：
- 在 `scripts/heartbeat.py` 加上下文健康度检测：单会话 token 数 / 消息轮数 / 未提交改动数
- 超阈值（如 100 轮或 50K tokens）时主动建议"落盘 + 起新会话"
- 配合 `driving/context_manager.py` 的 `compress_history` 自动触发

### 2.5 ⭐⭐ 多角色共识评审

**Trae-Agent 做法**：复杂任务自动组织多角色评审（架构师+测试+开发者+UI 设计师+产品经理），共识通过才发布。

**flipped 对标**：`orchestrator.py` 的 Overseer 是单监督者，不是多角色共识。

**落地建议**（P2）：
- 在里程碑级（非子任务级）加"多角色共识评审"节点
- 用不同 alias（architect/coder/reviewer）跑同一产出，输出各自 verdict
- 共识 = 所有角色 approve；分歧则升级人工
- 这比 Claude Code 的单 Reviewer 更强，但成本更高，只用于里程碑

### 2.6 ⭐ Ensemble Reasoning（生成/剪枝/选择）

**Trae-Agent 学术做法**：Trae Agent（SWE-bench 第一名）把问题求解拆成三个模块化 Agent：
- Generation Agent：生成多个候选补丁
- Pruning Agent：剪枝明显错误的候选
- Selection Agent：从剩余候选中选最优

**flipped 对标**：当前 Worker 是单路径执行（一个子任务一个方案）。

**落地建议**（P3，实验性）：
- 对高风险子任务（`classify_risk` 标为 high 的），让 Worker 生成 2-3 个候选方案
- 用 Overseer 做 Pruning（去掉明显错误的）
- 用 Verifier 做 Selection（跑验收命令，选通过的）
- 成本高，仅用于关键路径

---

## 3. flipped 已有/可保留的优势

对比下来，flipped 有些做法 Claude Code / Trae-Agent 反而没有：

### 3.1 六维度全覆盖

Claude Code 的 Verification Loop 偏"功能验证"（跑测试 + 浏览器验证），Trae-Agent 偏"流程验证"（多角色评审）。flipped 的六维度（功能/性能/兼容/安全/回归/UX）是**最完整的测试矩阵**，特别是：
- **安全测试**：bandit + pip-audit + npm audit + detect-secrets 四件套，Claude Code / Trae-Agent 都没内置
- **性能测试**：pytest-benchmark + locust + Lighthouse 三层，Claude Code 只有"测 UX 感觉"
- **兼容性测试**：Playwright 三浏览器矩阵，Claude Code 只用 Chrome 扩展

### 3.2 心跳监控 + 趋势历史

`scripts/heartbeat.py` 每 10 分钟扫一次：STATE.json + git + 模型就绪 + 测试基线 + 偏差分析，写 `heartbeat_history.jsonl`。Claude Code 和 Trae-Agent 都没有这种"项目级健康度时序数据"。

### 3.3 跨模型族监督

`orchestrator.py` 的 Overseer 用 GLM 监督 Kimi（不同模型族），避免同模型自偏。Claude Code 的 Review subagent 是同模型，Trae-Agent 的多角色也是同模型。这是 flipped 的独特优势。

### 3.4 循环熔断 + 迭代预算

AGENTS.md §6 的"同一 bug 修 ≥3 次仍失败即停止" + §2.5 的 Ralph 外层循环 + 单任务迭代预算，是 Claude Code / Trae-Agent 都没有的"防失控"机制。

### 3.5 状态外置 + 断点续传

STATE.json + PLAN.md + TEST_LOG.md + DECISIONS.md 四件套，配合 §2.5 的"每轮起全新上下文"。Claude Code 的 CLAUDE.md 是"项目事实"，但不是"进度状态"。flipped 的状态外置更彻底。

---

## 4. 落地优先级与工时

| 优先级 | 改进项 | 来源 | 工时 | 预期收益 |
|--------|--------|------|------|----------|
| **P0** | Verification Skill 打包 | Claude Code 1.1 | 2h | Agent 主动跑门禁，不再靠提醒 |
| **P0** | 结构化失败信号 JSON | Claude Code 1.2 | 3h | 失败定位从"读长日志"变"读 JSON" |
| **P0** | 测试设计独立阶段 | Trae 2.1 | 4h | 测试用例覆盖边界/异常，不再只 happy path |
| **P0** | Validator Agent 复合验证 | Trae 2.2 | 3h | Verifier 从"跑命令"升级为"质量验证" |
| P1 | Hook 强制门禁 | Claude Code 1.3 | 2h | 门禁从"软约束"变"硬阻断" |
| P1 | Review Subagent | Claude Code 1.4 | 4h | 独立上下文 critic，防自证 |
| P1 | Karpathy 四原则检查 | Trae 2.3 | 3h | 防"大刀阔斧重写"，强制外科手术式改动 |
| P1 | SOLO 上下文健康度 | Trae 2.4 | 2h | 防上下文腐烂 |
| P2 | CLAUDE.md 契约化 | Claude Code 1.5 | 2h | 契约不变成愿望式 |
| P2 | 多角色共识评审 | Trae 2.5 | 6h | 里程碑级多视角审查 |
| P3 | Ensemble Reasoning | Trae 2.6 | 8h | 高风险任务多候选择优 |

**P0 合计 12h**，建议立即排入下一个 milestone（M157）。

---

## 5. 一个最小可落地的起手式（本周内）

如果只能做一件事，做这个：

### 把六维度门禁打包成 Verification Skill

1. 创建 `.claude/skills/verify-quality/SKILL.md`：

```markdown
---
name: verify-quality
description: flipped 六维度质量验证 Skill。每个里程碑完成时主动跑，失败给结构化信号。
---

## Trigger
- 用户说"完成"/"done"/"搞定"时
- 里程碑标记为 done 前
- git commit 前

## Scope
读：src/ console/src/ tests/ reports/ STATE.json
写：reports/quality_metrics.json reports/findings.jsonl TEST_LOG.md

## Criteria（PASS 条件）
- quality_gate.sh exit 0
- py_coverage ≥ 80%
- fe_lines_cov ≥ 28%
- bandit HIGH = 0
- pip-audit 漏洞 = 0（或全部有 wontfix 理由）
- tsc_errors = 0
- build_ok = 1

## Evidence（失败信号 schema）
每次失败输出一行 JSON 到 reports/findings.jsonl：
{
  "ts": "2026-07-27T...",
  "rule": "QG_COVERAGE_BELOW_FLOOR",
  "location": "tests/test_api_terminal.py",
  "expected": "py_coverage >= 80.0",
  "actual": "78.3",
  "suggested_fix": "补 src/api/browser.py 的边界测试",
  "retryable": true
}

## Repair
1. 读 reports/findings.jsonl 最新一行
2. 按 suggested_fix 修复
3. 重跑 quality_gate.sh
4. 通过则收尾，否则循环（最多 3 次）

## Exit
- PASS：收尾，更新 STATE.json + TEST_LOG.md
- 3 次修复仍失败：升级人工，写 DEFECT_LOG.md
- verifier 自身 ERROR（脚本崩）：停止，不混为代码失败
```

2. 在 `AGENTS.md` §3 加一句："每个里程碑完成前，**必须**调用 `verify-quality` Skill。"

3. 升级 `scripts/quality_gate.sh`：失败时往 `reports/findings.jsonl` 写结构化信号（而不是只 echo 到 stdout）。

这一步对齐了 Claude Code 的核心理念（Verification Loop + Skill 打包 + 结构化失败信号），也是 P0 四项里收益最大的。

---

## 6. 结论

**flipped 当前体系 vs Claude Code / Trae-Agent 的相对位置**：

- **测试覆盖广度**：flipped > Claude Code > Trae-Agent（六维度 vs 功能验证 vs 流程验证）
- **验证自动化深度**：Claude Code > flipped > Trae-Agent（Skill 打包 + Hook 强制 vs shell 脚本 vs 人工调度）
- **多 Agent 协同**：Trae-Agent > flipped > Claude Code（八阶段多角色 vs Supervisor-Worker-Overseer vs Explore-Plan-Review）
- **防失控机制**：flipped > Claude Code > Trae-Agent（循环熔断 + 迭代预算 + 心跳监控 vs Hook exit 2 vs 规则集）

**一句话总结**：flipped 的测试体系在"广度"和"防失控"上已领先，但在"自动化深度"上落后于 Claude Code。最值得借鉴的是 **Verification Skill 打包 + 结构化失败信号**——这是把 flipped 已有的 quality_gate.sh 从"被动执行"升级为"主动验证"的关键一步，也是把六维度策略从"纸面策略"变成"代码级强制"的桥梁。

---

## 参考资料

- Claude Code 9-Step Loop: https://mer.vin/2026/07/claude-code-9-step-loop-explore-plan-hooks-and-senior-style-review/
- Building verification loops in Claude Code with skills: https://claude.com/blog/building-verification-loops-in-claude-code-with-skills
- 让 Claude Code 自己修到通过：验证循环怎么搭: http://m.toutiao.com/group/7665626710062285327/
- Claude Code Verification Loops for Quality (Boris Cherny): https://www.houstonitdevelopers.com/blog/claude-code-verification-loops-boris-cherny-tip
- Claude Code 2026 Best Practices: Guardrails & Tests: https://joulyan.com/en/blog/claude-code-2026-best-practices
- 基于Trae做AI驱动的测试实践: https://blog.csdn.net/qq_42831750/article/details/161085092
- 10 Best Tips for TRAE Mastery: https://github.com/HighMark-31/TRAE-Tips/blob/main/10BestTips.md
- SOLO + GLM-5: The Best Combo for TRAE: https://github.com/HighMark-31/TRAE-Tips/blob/main/SOLO_BestCombo.md
- Trae Agent: An LLM-based Agent for Software Engineering with Test-time Scaling (arXiv): https://arxiv.org/pdf/2507.23370
- Trae Multi-Agent Skill 使用说明: https://github.com/weiransoft/TraeMultiAgentSkill/blob/main/USAGE.md
