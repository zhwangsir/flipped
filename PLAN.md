 # M5 · 硬化与产线化：性能 / 稳定性 / 安全 / 崩溃恢复
 
 ## 目标
 1. 性能：监控并调优 MLX 双模型吞吐、KV cache / 上下文策略、模型换载策略。
 2. 稳定性：让 orchestration-api 与 orchestrator 在崩溃 / 重启后可从 LangGraph checkpoint 断点续跑。
 3. 安全：密钥管理、命令白名单、高风险动作加固。
 4. 验收：一个长任务能连续自主运行，并在 orchestration-api 被强制杀死后从 checkpoint 恢复继续执行。
 
 ## M4 完成报告（已验证）
 - `src/mcp_server/`：MCP stdio server，注册 5 个工具：`web_search`、`rag_query`、`rag_ingest`、`run_coding_task`、`research_and_code`。
 - `src/rag/`：Chroma 本地持久化向量库 + 可插拔嵌入（默认 `sentence-transformers/all-MiniLM-L6-v2`，未安装则 fallback 到 `MockEmbedding`）+ 文件/目录/文本 ingest。
 - `src/driving/researcher.py`：聚合 `web_search` + `rag_query` 调研上下文，供 `research_and_code` 使用。
 - 新增测试：`tests/test_rag.py`、`tests/test_mcp_server.py`、`tests/test_researcher.py`。
 - 新增 `scripts/verify_m4.sh` 与 `pytest.ini`（禁用 `anyio` pytest 插件，避免干扰 `asyncio.run` 测试）。
 - 更新 `requirements.txt`（`mcp`、`chromadb`、`uvicorn>=0.30.0`）与 `.env.example`（`RAG_DB_DIR`、`RAG_EMBEDDING_MODEL`）。
 - 验证：`bash scripts/verify_m4.sh` 退出码 0；M4 单测 13 passed；全量回归 47 passed, 2 warnings；`cd console && npm run build` 通过。
 - 环境限制：Codex 沙箱禁止 TCP bind 与 outbound 网络，真实 LLM + 网络 + 编码端到端由注入 mock 的测试兜底验证状态机与调用链。
 
 ## 关键决策
 - **RAG 向量库选 Chroma**：本地持久化、无需外部服务、Apple Silicon 友好。
 - **嵌入模型可插拔**：默认尝试 `sentence-transformers/all-MiniLM-L6-v2`，未安装时自动 fallback 到 `MockEmbedding`，保证沙箱/测试可运行。
 - **MCP 包名避开冲突**：`src/mcp/` 改名为 `src/mcp_server/`，避免与 PyPI 的 `mcp` 包命名冲突。
 - **pytest.ini 禁用 anyio 插件**：`mcp`/`chromadb` 引入的 `anyio` pytest 插件会干扰 `test_api_approval_flow.py` 的 `asyncio.run`，导致全量回归失败；禁用后 47 passed。
 
 ## 详细步骤
1. **M5.1 性能可观测** ✅ 已完成
   - 新增 `src/metrics/__init__.py` / `src/metrics/collector.py`：线程安全 `MetricsCollector` + LangChain `MetricsCallbackHandler`。
   - 指标覆盖：LLM total_calls / total_tokens / prompt_tokens / completion_tokens / total_latency / TTFT / errors。
   - `src/api/main.py` 新增 `GET /api/v1/metrics`；`src/api/schemas.py` 新增 `MetricsResponse`（已修复缩进）。
   - `src/driving/orchestrator.py` 的 `_make_llm` 支持 `callbacks`；`default_supervisor` / `default_overseer` 注入 `MetricsCallbackHandler`。
   - 新增 `tests/test_metrics.py` 7 个用例；修复 `src/metrics/` 前导空格导致的 `IndentationError`。
   - 验证：`test_metrics.py 7 passed` / 全量 `54 passed` / `console build` 通过 / `scripts/verify_m5.sh` 退出码 0。

2. **M5.2 上下文 / KV cache 管理** 🚧 进行中
   - 新增 `src/driving/context_manager.py`：
     - `estimate_tokens(history)`：可插拔 token 估算器（默认按字符混合启发式，可选 tiktoken 若已安装）。
     - `compress_history(history, max_tokens, keep_recent, summarizer)`：当 token 超过阈值时，把早期 history 摘要成一条 `summary` 条目，保留最近 `keep_recent` 条完整记录。
     - 默认摘要器生成 `{step:"summary", tokens_before, items, digest}`，不丢失关键步类型。
   - 在 `orchestrator.py` 中：
     - `OrchestratorState` 增加 `context_summary` 字段；`default_supervisor` 把 `context_summary` 放入 prompt。
     - 增加 `compress` 节点：在每次回到 supervisor 前调用 `compress_history`，如果触发压缩则更新 `history` + `context_summary`。
     - `build_orchestrator` 接受 `max_context_tokens` / `keep_recent` 配置。
   - Checkpoint 保留策略：
     - 新增 `CheckpointRetention` 包装 `SqliteSaver`，按 `thread_id` 保留最近 N 个 checkpoint，删除旧 checkpoint 及关联 writes。
     - `drive_orchestrated` 在运行结束后调用 `retention.trim()`，避免长任务 checkpoint 无限膨胀。
   - 测试：
     - `tests/test_context_manager.py`：token 估算、压缩触发、摘要内容、retention 删除。
     - 全量回归（≥54 passed）与 `scripts/verify_m5.sh` 通过。
 3. **M5.3 模型换载 / 路由降级策略**
    - 增加单模型模式 / 双模型模式自动切换：当 `coder` 不可用时只跑 `architect` 级任务，或切换到本地 fallback 模型。
    - 实现 `exollama` 健康检查（`/v1/models` 可达性 + 指定模型在线）。
    - 当 LiteLLM proxy `:4000` 不可用且 `FLIPPED_MODEL_BASE_URL` 已设置时自动直连；proxy 恢复后切回。
 
 4. **M5.4 崩溃恢复与断点续跑**
    - `orchestration-api` 启动时扫描未完成的会话（`status=running`/`paused`），通过 LangGraph checkpoint 恢复。
    - 提供 `POST /api/v1/sessions/{id}/resume` 端点或自动恢复；`worker_error` 时根据是否已持久化决定重试或交人工。
    - 新增 `tests/test_recovery.py`：注入 mock checkpoint，模拟 kill + resume 后继续到 `verified`。
    - 新增 `scripts/verify_m5.sh`：检查恢复单测、白名单单测、性能指标单测、全量回归。
 
 5. **M5.5 安全加固**
    - 密钥管理：所有 API key 只走 env / `.env`，禁止硬编码；新增启动时 `secrets_validation` 检查（`.env` 存在且 `EXO_API_KEY` 未写入源码）。
    - 命令白名单：`orchestrator` / `openhands_worker` 对 terminal 命令做白名单/黑名单过滤（如 `rm -rf /`、`curl` 外发、反弹 shell 等）。
    - 高风险动作分类器与 `approval` 整合，确保 `push`/`merge`/`deploy`/`kubectl apply` 等必须审批。
    - 新增 `tests/test_safety.py` 覆盖命令白名单与密钥检查。
 
 6. **M5.6 长任务验收（沙箱内模拟）**
    - 设计一个长任务（如：调研 + 多文件代码 + 测试）让 orchestrator 在注入 mock 上跑，中途人为清空当前状态但保留 checkpoint，再恢复后从 checkpoint 继续到 `verified`。
    - 在沙箱中无法真实 bind 端口或 kill 进程，用 pytest 注入方式模拟崩溃恢复。
    - 非沙箱环境可复跑真实 LLM + OpenHands 的长任务，作为最终验收。
 
 ## 验收标准
 - `python -m pytest tests/test_recovery.py tests/test_safety.py tests/test_metrics.py -q` 全绿（新增）。
 - `python -m pytest tests/ -q` 全量回归通过（≥47 passed）。
 - `bash scripts/verify_m5.sh` 退出码 0。
 - `orchestration-api` 能从已有 checkpoint 恢复未完成的会话并继续执行。
 - 命令白名单拦截高风险命令，且高风险动作仍强制走审批。
 - 无新增硬编码密钥，`.env` 示例与 `.gitignore` 完整。
 - `cd console && npm run build` 通过。
 
 ## 回滚策略
 - 不破坏现有 `orchestrator` 图结构，新增 `recovery` / `context_limit` 节点与配置项。
 - 安全白名单默认启用，但可通过 `SAFETY_ALLOW_UNSAFE_COMMANDS=1` 环境变量临时关闭（仅用于测试）。
 - 所有恢复逻辑先走单测，再走 `verify_m5.sh`，最后才接入真实会话。
