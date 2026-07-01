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

2. **M5.2 上下文 / KV cache 管理** ✅ 已完成
   - 修复 LangGraph `InvalidUpdateError`：移除 `START -> compress` 边；`compress_node` 仅在 `compress_history` 真正触发压缩时才返回 `history` + `context_summary`，否则返回 `{}`，避免与 `supervisor` 在同一 superstep 中同写 `history`。
   - 新增 `src/driving/context_manager.py`：
     - `estimate_tokens(history)`：可插拔 token 估算器（默认按字符混合启发式，可选 tiktoken 若已安装）。
     - `compress_history(history, max_tokens, keep_recent, summarizer)`：当 token 超过阈值且历史条目数 > `keep_recent` 时，把早期 history 摘要成一条 `summary` 条目，保留最近 `keep_recent` 条完整记录。
     - 默认摘要器生成 `{step:"summary", tokens_before, items, digest}`，不丢失关键步类型。
   - 在 `orchestrator.py` 中：
     - `OrchestratorState` 增加 `context_summary` 字段；`default_supervisor` 把 `context_summary` 放入 prompt。
     - 增加 `compress` 节点：在每次回到 supervisor 前调用 `compress_history`，如果触发压缩则更新 `history` + `context_summary`。
     - `build_orchestrator` 接受 `max_context_tokens` / `keep_recent` 配置。
   - Checkpoint 保留策略：
     - 新增 `CheckpointRetention` 包装 `SqliteSaver`，按 `thread_id` 保留最近 N 个 checkpoint，删除旧 checkpoint 及关联 writes。
     - `drive_orchestrated` 在运行结束后调用 `retention.trim()`，避免长任务 checkpoint 无限膨胀。
   - 测试：
     - 新增 `tests/test_context_manager.py`：8 个用例覆盖 `simple_estimator`、压缩触发、摘要内容、自定义 summarizer、短历史保护、`CheckpointRetention` trim。
     - 全量回归 62 passed / console build 通过 / `scripts/verify_m5.sh` 退出码 0。
 3. **M5.3 模型换载 / 路由降级策略** ✅ 已完成
    - 新增 `src/driving/model_router.py`：
      - `is_endpoint_healthy(base_url, timeout)`：GET `/v1/models` 判断服务是否可达。
      - `is_model_available(base_url, model_id, timeout)`：在 `/v1/models` 列表中检查指定模型是否在线。
      - `resolve_model_config(alias)`：优先使用 LiteLLM proxy；proxy 健康且 alias 可用时走 proxy + alias，否则回退到 `FLIPPED_MODEL_BASE_URL` 直连 exo + 完整模型 id。
      - `resolve_worker_model_config()`：为 OpenHands Worker 选择可用 endpoint + 模型名，运行时 proxy 指向 `host.docker.internal:4000` 供容器内访问。
    - 在 `src/driving/orchestrator.py` 的 `_make_llm` 中接入 `resolve_model_config`，Supervisor/Overseer 根据运行时健康状态自动选择 proxy 或直连。
    - 在 `src/driving/orchestrator.py` 的 `openhands_worker` 节点中接入 `resolve_worker_model_config`，Worker 创建时动态选择 endpoint。
    - 新增 `tests/test_model_router.py`：11 个用例覆盖 proxy 健康/直连健康/双端不可用、alias 可用性判断、worker 配置解析。
    - 全量回归 73 passed / console build 通过 / `scripts/verify_m5.sh` 退出码 0。

 4. **M5.4 崩溃恢复与断点续跑** ✅ 已完成
    - 新增 `resume_orchestrated(thread_id, db_path, ...)`：从 `SqliteSaver` checkpoint 恢复未完成的 orchestrator 运行，自动处理已完成/已中断状态，续跑至 `verified` 或终止状态。
    - `src/api/main.py`：新增 `POST /api/v1/sessions/{id}/resume` 端点；lifespan 启动时扫描 `running`/`paused` 会话并自动 `_resume_orchestrator`；`_resume_orchestrator` 支持 mock 与真实两种模式。
    - `src/api/session.py`：会话模型支持 `checkpoint_db_path` 字段，用于关联持久化 checkpoint 数据库。
    - 新增 `tests/test_api_recovery.py`：3 个 API 级用例（无会话 404 / 无 checkpoint 400 / 真实 checkpoint 恢复后状态到达 `done`）。
    - 修复 `tests/test_recovery.py` / `test_api_recovery.py` 的 `thread_id` 对齐与 TestClient 上下文管理器问题，避免 checkpoint 写入在 API 测试外被隔离。
    - 验证：`test_recovery.py 3 passed` / `test_api_recovery.py 3 passed` / 全量 79 passed / `verify_m5.sh` 退出码 0。

 5. **M5.5 安全加固** ✅ 已完成
    - 新增 `src/driving/safety.py`：
      - `is_safe_command` / `is_dangerous_command`：危险模式黑名单（`rm -rf`、`mkfs`、`dd of=/dev/`、管道 sh、反弹 shell、`sudo` 等） + 命令白名单。
      - `normalize_command`：剥离 `bash -c` / `sh -c` 与外层引号，避免绕过。
      - `scan_source_for_secrets` / `validate_secrets`：扫描源码中硬编码的 `api_key/token/secret/password` 与 `EXO_API_KEY/LITELLM_MASTER_KEY/OPENAI_API_KEY`。
      - `audit_openhands_events`：审计 OpenHands `terminal` ActionEvent，命中危险命令则快速失败。
      - `SAFETY_ALLOW_UNSAFE_COMMANDS=1` 环境变量仅在测试中临时关闭白名单。
    - `src/driving/orchestrator.py`：默认 verifier 改为 `_safe_default_verifier`，验收命令前过白名单 + 高风险命令需审批（`classify_risk`）。
    - `src/executor/openhands_worker.py`：`RemoteConversation.run` 结束后审计 terminal 事件，发现危险命令立即抛出 `RuntimeError`。
    - `src/api/main.py`：lifespan 启动时调用 `validate_secrets`，无 `.env` 且未设 `EXO_API_KEY` 时打印安全提醒（不阻塞启动）。
    - `tests/conftest.py`：测试 fixture 设置 `EXO_API_KEY=dummy`，避免 lifespan 在无 `.env` 时打印警告。
    - 新增 `tests/test_safety.py`：12 个用例覆盖命令归一化、危险命令拦截、安全命令放行、未知命令拦截、环境变量覆盖、密钥扫描、`.env`/环境变量校验、OpenHands 事件审计。
    - 验证：`test_safety.py 12 passed` / 全量 91 passed / `verify_m5.sh` 退出码 0 / console build 通过。

 6. **M5.6 长任务验收（沙箱内模拟）** 🚧 进行中
    - 目标：新增/扩展测试模拟长任务（多步 orchestrator 经历 supervisor→worker→overseer→verify 多个迭代，中途保留 checkpoint 后进程崩溃，再调用 `resume_orchestrated` 从 checkpoint 续跑到 `verified`）。
    - 在沙箱中无法真实 bind 端口或 kill 进程，用 pytest 注入方式模拟崩溃恢复：通过 `graph.stream(..., stream_mode="updates")` 运行若干 update 后主动 break，再调用 `resume_orchestrated` 完成剩余迭代。
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
