# Phase B · B4 计划：tool-calling 加固 + cost warning 修复 ✅

## 目标
1. 让 orchestrator 的 Supervisor/Overseer 在 LiteLLM proxy 不可用时能直连 exo，不阻塞端到端闭环。
2. 给 OpenHands Worker 增加 tool-calling 稳定性参数，并抑制 litellm cost map 相关噪音。

## 涉及文件
- `src/driving/orchestrator.py`：`_make_llm` 支持 `FLIPPED_MODEL_BASE_URL` / `FLIPPED_ARCHITECT_MODEL` / `FLIPPED_CODER_MODEL`。
- `src/executor/openhands_worker.py`：LLM 增加 `drop_params=True` / `native_tool_calling=True`；设置 `LITELLM_LOG=ERROR`。
- `scripts/verify_b4.sh`：真实 GLM Supervisor → OpenHands Worker(Kimi) → GLM Overseer → docker exec 强制验证。

## 验收结果 ✅
- `scripts/verify_b4.sh` 退出码 0：
  - GLM-5.2-fp8 调度子任务；
  - Kimi-K2.7-Code-4bit（OpenHands SDK）在 Docker 沙盒创建 `/workspace/b4_done.txt` 并验证内容 hello；
  - GLM Overseer 判定方向/效率；
  - 强制验证通过，`verified=True, stop_reason=verified, iteration=1`。
- `python -m pytest tests/` ✅ 29 passed。

## 已知状态
- LiteLLM proxy `:4000` 仍因本地 Postgres/prisma 未启动，但已可通过环境变量直连 exo，不再是阻塞点。

## 下一步：B5
- UI 去 AI 感打磨：减少机械 system prompt 输出、优化事件流可读性、给 Console 增加 Human-in-the-loop 审批 UI、错误状态可视化等。
