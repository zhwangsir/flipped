# DECISIONS.md — 架构决策记录

> 记录重要架构选择 + 理由，避免后续反复纠结（AGENTS.md §4）。

## D1 · 服务层复用 exo 集群 + LiteLLM 前置，弃用 mlx-openai-server
- **日期**：2026-06-29 ｜ **批准**：用户
- **背景**：AGENTS.md M0 推荐单机 `mlx-openai-server` 挂双模型。但用户实际运行的是分布式 **exo 集群**，已把两个目标模型(`GLM-5.2-DQ4plus-q8`、`Kimi-K2.7-Code-4bit`)暴露为 OpenAI 兼容接口。
- **决策**：不另建 mlx-openai-server。架构为 `客户端 -> LiteLLM(:4000) -> exo(:52415)`。LiteLLM 负责统一路由(architect→GLM / coder→Kimi)、降级、密钥、可观测接入点。
- **理由**：服务层已就绪，重复造单机栈与集群路线冲突且本机内存不够；LiteLLM 这层仍带来路由/降级/统一入口价值。
- **影响**：AGENTS.md M0 中 `--tool-call-parser`/`--reasoning-parser` 配对(mlx-openai-server 概念)不适用；改由 exo 自身处理工具调用 → 见 D3。

## D2 · 本机为开发/控制节点，模型驻留在 exo 集群
- **日期**：2026-06-29 ｜ **批准**：实测核对
- **背景**：AGENTS.md 假设宿主机 2TB 内存可双模型常驻 1.35TB。实测本机为 **Apple M5 Max / 128GB / 1.1TB 可用盘**。
- **决策**：本机仅作开发与控制节点（跑编辑器 fork、驾驭层、LiteLLM、脚本），**不在本机加载模型**。"2TB" 指 exo 集群跨 Thunderbolt 节点的聚合内存。
- **理由**：128GB 物理上装不下大模型；集群已承载分片(GLM-5.2/Kimi 各 4 分片)。
- **影响**：M5 的「模型换载策略/KV cache 调优」属集群侧；本机侧关注客户端、驾驭层、可观测。

## D3 · M0 验收核心 = 经 exo 的工具调用实测
- **日期**：2026-06-29 ｜ **批准**：用户
- **背景**：整条 agentic 链路(M2 编辑器 + M3 驾驭层)成败取决于工具调用能被正确解析；AGENTS.md 警告"否则静默失效"。
- **决策**：M0 必须用真实带 `tools` 的请求实测两模型返回结构化 `tool_calls`（而非把调用塞进 content）。不稳则在驾驭层加结构化输出约束 + 重试（呼应 M2）。
- **理由**：验证靠运行不靠看（§1.2）；这是后续一切的地基。
- **现状**：因集群推理 502 暂时 blocked，已由后台监控 `monitor_cluster.py` 在集群恢复后自动复验。
