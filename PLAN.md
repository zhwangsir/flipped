# PLAN.md — 当前里程碑：M2 · 代码编辑器形态（Cline）

> M0、M1 已完成（详见 STATE.json / TEST_LOG.md / DECISIONS.md）。本文件描述 M2。

## M2 目标（AGENTS.md §5，按 D4 修正）

把 **Cline**（D4：替代已停服的 Roo Code）接到我们的服务层：API Provider = OpenAI Compatible → `http://localhost:4000`（LiteLLM），规划/架构阶段用 GLM-5.2（别名 `architect`），实现/编码阶段用 Kimi-K2.7-Code（别名 `coder`）。在编辑器内下达多文件改动任务，全流程跑通。

**验收（AGENTS.md M2）**：在编辑器内下达一个多文件改动任务，Agent 能**读文件 → 改代码 → 跑命令 → 自检**全流程跑通；并核查工具调用配对正确（M0.4 已证 exo 侧 OK）。

## 策略（D4）

**M2 先 install + 配置验证**编辑器流；**源码 fork 推迟到 M3**（届时加驾驭层才需改源码）。理由：M2 验收不需要改 Cline 源码，装现成版 + 配置即可达成，最小代价（Karpathy Rule 2）。

## 链路

```
VS Code + Cline 扩展
   └ API Provider: OpenAI Compatible → http://localhost:4000 (LiteLLM master key)
       ├ Plan/Architect 模式 → 模型 "architect" (GLM-5.2)
       └ Act/Coder 模式     → 模型 "coder" (Kimi-K2.7-Code)
   → LiteLLM(:4000) → exo(:52415) → GLM / Kimi
```

## 步骤与验收

| # | 步骤 | 验证方式 | 状态 |
|---|------|----------|------|
| M2.1 | 装 Cline 扩展 + `code` CLI 入 PATH | VS Code 里 Cline 面板出现；`code --version` 可用 | todo |
| M2.2 | 配 OpenAI Compatible → :4000（key=master_key，model=architect/coder） | Cline 内发一句话，经 LiteLLM 收到 GLM/Kimi 回复（看 LiteLLM 日志命中别名） | todo |
| M2.3 | 按模式分模型：Plan→architect(GLM)、Act→coder(Kimi) | 切模式时实际命中对应模型（依赖调研 ws3m2ej7r 结论） | todo |
| M2.4 | 端到端多文件改动任务 | 在一个测试小项目里让 Cline 读多文件→改→跑命令→自检，工具调用全程不失效 | todo |
| M2.5 | 证据留痕 + 验收脚本/记录 | 截图/日志记入 TEST_LOG；可脚本化部分入 verify_milestone_2 | todo |

## M2 完成定义（DoD §8）

- [ ] Cline 经 :4000 能正常对话（架构/编码两别名都通）
- [ ] 多文件改动任务端到端跑通（读→改→跑→自检），工具调用不失效
- [ ] 证据记入 TEST_LOG（Cline 是 GUI，验收含截图/日志）
- [ ] 全量回归（verify_milestone_0/1）仍通过
- [ ] 无硬编码密钥；git commit + STATE 更新

## 已知交互点 / 风险

- **Cline 是 GUI 扩展**：M2.4 端到端验收很可能需要**你在 VS Code 里实操**，或我用 computer-use 驱动（较重）。调研 ws3m2ej7r 在查是否有 headless/CLI 驱动方式。
- 按模式分模型能力以调研结论为准；若 Cline 不支持，则用两个 API Profile 手动切换兜底。
- model id 必须与 LiteLLM 暴露的别名完全一致（architect/coder）；context window 等可能要手填。
- `code` CLI 未在 PATH（VS Code app 已装）→ M2.1 先补。

## 下一里程碑预告（M3）

驾驭层：强制验证 / 循环检测 / 上下文压缩 / 人工审批 / 子Agent / 可观测——此时 **fork Cline** 落自定义代码（基于 D6 LangGraph 的 checkpoint/中断机制思路）。
