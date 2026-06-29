# PLAN.md — 当前里程碑：M0 · 环境与服务层

> 本文件只描述**当前里程碑**的详细步骤与验收标准（AGENTS.md §4）。完成后归档要点到 DECISIONS.md，再开下一里程碑的新 PLAN。

## M0 目标（按实测修正）

把两个本地 MLX 模型经统一入口暴露为可被 agentic 客户端调用的 OpenAI 兼容服务，并**实测工具调用解析正确**。

原文 M0 假设「单机 mlx-openai-server + 双模型本地常驻 1.35TB」在本机（M5 Max 128GB）不成立。已与用户确认改为：**复用现成 exo 集群 + LiteLLM(:4000) 前置**（决策 D1/D2/D3）。

```
客户端/编辑器  ->  LiteLLM Proxy(:4000)  ->  exo 集群(100.64.201.37:52415)  ->  GLM-5.2 / Kimi-K2.7-Code
                    路由/降级/密钥/可观测                已是 OpenAI 兼容
```

## 步骤与验收

| # | 步骤 | 涉及文件 | 验证方式 | 状态 |
|---|------|----------|----------|------|
| M0.1 | 初始化骨架与状态文件 | AGENTS.md, STATE.json, PLAN.md, DECISIONS.md, TEST_LOG.md, README.md, .gitignore | `ls` 全部存在 + `git log` 有初始提交 | doing |
| M0.2 | 确认集群两模型在线 | — | `curl /v1/models` 含 GLM-5.2 与 Kimi-K2.7-Code | ✅ done |
| M0.3 | 起草 LiteLLM 配置 | infra/litellm/config.yaml, .env.example | `litellm --config ... --dry-run` 通过；启动后 `/v1/models` 列出 architect/coder 别名 | todo |
| M0.4 | **工具调用实测（命根子）** | scripts/toolcall_test.py | 两模型对带 tools 的请求返回结构化 `tool_calls`（非塞进 content）| **blocked**（集群 502） |
| M0.5 | 降级验证 | infra/litellm/config.yaml | 停一个模型，LiteLLM fallback 到另一个/报可控错误 | todo |
| M0.6 | 一键验收脚本 | scripts/verify_milestone_0.sh | 任何时候 `bash scripts/verify_milestone_0.sh` 退出码 0 | todo |

## M0 完成定义（DoD，AGENTS.md §8）

- [ ] `verify_milestone_0.sh` 实跑通过，输出记入 TEST_LOG.md
- [ ] 两模型工具调用解析实测通过（M0.4）
- [ ] LiteLLM 路由 + 降级实测通过（M0.3/M0.5）
- [ ] 无硬编码密钥（token 走 `.env`，`.env` 在 `.gitignore`）
- [ ] git commit + STATE.json 更新
- [ ] 遗留问题显式记录

## 当前阻塞与并行策略

- 🔴 **阻塞**：exo 集群推理 502（ISSUE-1）。M0.4/M0.5 需实时推理，暂挂 blocked。
- 🟢 **并行可做**（不依赖实时推理）：M0.1 骨架、M0.3 LiteLLM 配置起草、M2 Roo Code fork 调研。
- 🔭 **后台监控**：`scripts/monitor_cluster.py` 盯集群恢复，模型一 ready 即自动复跑 M0.4 工具调用验证并写 TEST_LOG.md。

## 下一里程碑预告（M1）

自托管 SearXNG + 联网搜索工具 + 最小 agent loop 跑通一个需实时信息的真实查询。M0 验收通过后再展开。
