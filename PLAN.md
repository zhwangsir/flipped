 # M5 · 硬化与产线化：性能 / 稳定性 / 安全 / 崩溃恢复
 
## 目标
1. 性能：监控并调优 MLX 双模型吞吐、KV cache / 上下文策略、模型换载策略。
2. 稳定性：让 orchestration-api 与 orchestrator 在崩溃 / 重启后可从 LangGraph checkpoint 断点续跑。
3. 安全：密钥管理、命令白名单、高风险动作加固。
4. 验收：一个长任务能连续自主运行，并在 orchestration-api 被强制杀死后从 checkpoint 恢复继续执行。
 5. **M5.5 安全加固** 🚧 进行中

 4. **M5.4 崩溃恢复与断点续跑** ✅ 已完成
    - `src/driving/orchestrator.py` 新增 `resume_orchestrated(thread_id, db_path, ...)`：从 `SqliteSaver` checkpoint 读取状态，未 `done` 且无 `__interrupt__` 时调用 `graph.invoke(None, config)` 断点续跑。
    - `drive_orchestrated` 支持可选注入 supervisor/worker/overseer/verifier。
    - `src/api/schemas.py`：`Session` 新增 `goal/verify_cmd/cwd/checkpoint_db_path`；`SessionStatus` 新增 `paused`。
    - `src/api/session.py` 增加 JSON 持久化 `load/save/update`。
    - `src/api/main.py`：lifespan 加载持久化会话并自动恢复 `running`/`paused` 且带 checkpoint 的会话；新增 `POST /api/v1/sessions/{id}/resume`。
    - `tests/test_recovery.py` 3 个用例通过；`tests/test_api_recovery.py` 修复 `TestClient` 上下文与 `thread_id` 对齐后 3 个用例全绿。
    - 验证：全量回归 79 passed / console build 通过 / `bash scripts/verify_m5.sh` 退出码 0。
 
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
