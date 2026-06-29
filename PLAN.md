# PLAN.md — 当前里程碑：M3 · 驾驭层

> M0、M1、M2 已完成（详见 STATE.json / TEST_LOG.md / DECISIONS.md）。本文件描述 M3。

## M3 目标（AGENTS.md §5）

在 Cline（D4 基座）之上逐个叠加驾驭层能力，每加一个写测试：
1. 强制验证节点（Agent 自称完成后强制跑验收脚本）
2. 循环检测（最近 N 步动作签名，同文件/同动作 ≥3 次则中断重规划）
3. 上下文压缩（接近窗口上限自动总结+落盘）
4. 人工审批断点（高风险动作前暂停等确认，§7）
5. 子 Agent（主-从：GLM 调度，Kimi 干活；子任务独立干净上下文，结构化交回）
6. 可观测性（tracing / 本地日志，每步输入/输出/工具调用可追溯）

## 首要设计决策（M3.1，先定再做）

**驾驭层落在哪一层？** 三种路径，需先评估（呼应 M2 "先轻后重"）：
- **(A) Cline hooks + SDK + .clinerules（轻，优先评估）**：Cline CLI 有 `--hooks-dir`（运行时钩子注入）、`@cline/sdk`（createTool/生命周期钩子）、`.clinerules`。强制验证（hook 在 agent 完成时跑验收）、可观测（hook 记录每步）、循环检测（hook 看动作历史）也许无需改源码即可实现。
- **(B) fork Cline 源码（重，D4 预定但仅在必要时）**：Bun + Git LFS + protobuf + 两包构建 + F5。深度改 agent loop（如内建循环检测/压缩策略）才需要。
- **(C) LangGraph 编排层（D6）包在 Cline 外**：用 M1 的 LangGraph 基建做主-从子 Agent 调度 + checkpoint（崩溃恢复/审批中断），Cline 作为"执行器"。

✅ **已决（D9，调研 task wuw3zewas）**：3=A(Cline Auto Compact 零代码)；6=A 采集(PostToolUse 日志 hook)+C 归档(checkpoint)；4=A 兜底(Plan/Act+auto-approve)+C 硬断点(interrupt)；1/2/5=C(LangGraph supervisor/状态机)。**不 fork(B)**。详见 [research-cline-hooks-driving-layer.md](docs/research-cline-hooks-driving-layer.md)。前置：C 侧换 SqliteSaver/PostgresSaver。

## 步骤与验收（M3.1 定方案后细化）

| # | 能力 | 验收(每个都要测) | 状态 |
|---|------|------------------|------|
| M3.1 | 方案决策（D9：A/C 分工，不 fork） | DECISIONS D9 + docs 落盘 | ✅ done |
| M3.2 | 可观测采集：PostToolUse/PreToolUse 日志 hook（A，先实测 hook 协议） | cline 跑任务 --hooks-dir，JSONL 落每步工具调用 | todo |
| M3.2 | 强制验证节点 | agent 谎称完成 → 强制验收脚本拦下 | todo |
| M3.3 | 循环检测 | 构造同动作重复 → ≥3 次被中断重规划 | todo |
| M3.4 | 上下文压缩 | 长会话接近上限 → 自动总结+落盘且不崩 | todo |
| M3.5 | 人工审批断点 | 高风险动作（push/部署）→ 暂停等确认 | todo |
| M3.6 | 子 Agent 主-从 | 主 Agent 派子任务、子任务独立上下文、结构化交回 | todo |
| M3.7 | 可观测性 | 每步输入/输出/工具调用可追溯（日志/tracing） | todo |

## M3 完成定义（DoD §8）

- [ ] 六项能力各自实现且有可重复测试
- [ ] verify_milestone_3.sh 实跑通过，证据入 TEST_LOG
- [ ] 全量回归（verify_0/1/2）仍通过
- [ ] 无硬编码密钥；git commit + STATE 更新

## 风险

- 部分能力 Cline 已内建（compaction 有 `--compaction`、审批有 auto-approve 开关、checkpoint 有还原）→ 别重复造，先盘点 Cline 现有能力再决定自建哪些。
- fork+build 偏重（Bun/protos）→ 仅在 A/C 不够时启动。
- 会话/进程重启会杀后台服务 → M3 的常驻组件需可一键重启 + 状态外置（呼应 §2.5 Ralph）。

## 下一里程碑预告（M4）

DeepAgents 后端包成 MCP Server + RAG（向量库）；编辑器内触发"调研+落地代码"复合任务。
