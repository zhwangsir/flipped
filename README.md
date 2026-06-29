# flipped

接入本地 MLX 双模型的 **agentic 代码编辑器平台**。

| 角色 | 模型 | 位置 |
|------|------|------|
| 编排者 / 架构师（主 Agent） | GLM-5.2 (`mlx-community/GLM-5.2-DQ4plus-q8`) | exo 集群 |
| 执行者 / 码农（子 Agent） | Kimi-K2.7-Code (`mlx-community/Kimi-K2.7-Code-4bit`) | exo 集群 |

**基座**：fork Roo Code + 自定义驾驭层（强制验证 / 循环检测 / 上下文压缩 / 人工审批 / 子 Agent / 可观测性）+ MCP 联网与外部能力。

## 架构（M0 已定，决策 D1/D2）

```
客户端 / 编辑器
   -> LiteLLM Proxy (:4000)        # 统一路由 architect→GLM / coder→Kimi、降级、密钥、可观测
   -> exo 集群 (100.64.201.37:52415)  # 已是 OpenAI 兼容，张量并行多节点
   -> { GLM-5.2, Kimi-K2.7-Code }
```

> 本机（Apple M5 Max / 128GB）是开发/控制节点，**不加载模型**；模型驻留在 exo 集群。

## 工作方式

本项目由自主开发 Agent 按 [AGENTS.md](AGENTS.md) 的流程推进：先计划、验证靠运行、小步提交、状态外置、诚实报告。

- 当前进度 / 里程碑 / 已知问题：[STATE.json](STATE.json)
- 当前里程碑详细计划：[PLAN.md](PLAN.md)
- 架构决策记录：[DECISIONS.md](DECISIONS.md)
- 测试证据流水：[TEST_LOG.md](TEST_LOG.md)

## 脚本

- `scripts/monitor_cluster.py` — 盯 exo 集群从 502 恢复，模型 ready 即自动跑工具调用验证。
- `scripts/toolcall_test.py` — 单次工具调用解析验证（`python3 scripts/toolcall_test.py <model_id>`）。
- `scripts/verify_milestone_0.sh` — M0 一键验收（待集群恢复后补全）。
