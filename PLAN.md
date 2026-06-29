# PLAN.md — 当前阶段：Phase 1 · 脑（驾驭层 + AI 控制面）

> 产品=AI 驱动多平台桌面 IDE（D10）。完整架构见 [docs/product-architecture.md](docs/product-architecture.md)。
> 路线分三阶段（D14）：**Phase 1 脑（在 stock VS Code 做）→ Phase 2 环境 → Phase 3 壳(fork+打包)**。脑先于壳。
> 已完成：M0 服务层 ✅ · M1 工具链 ✅ · M2 Cline 接入 ✅。

## Phase 1 目标（≈ 原 M3 驾驭层 + M4 控制面，落在 LangGraph sidecar + Cline 扩展）

驾驭层按 D9/D11 分工：Cline 原生/hooks（单步/压缩/采集）+ **LangGraph 本地 sidecar**（跨步状态机：验证/循环/子Agent/审批/checkpoint）。

| # | 能力 | 落点 | 验收 | 状态 |
|---|------|------|------|------|
| 可观测 | cline `--json` 流解析→结构化轨迹+审计 | A: observe.py | 真实 cline 运行被捕获+审计落盘 | ✅ done (M3.2) |
| **强制验证** | 完成后**强制**跑验收命令判定 done，不过回灌重做，触顶熔断 | C: sidecar.py | 单测(回灌+熔断) + e2e(驱动 cline 真验收) | ✅ done (M3.3) |
| 循环检测 | 跨步记忆动作指纹，同动作≥N 中断重规划 | C: sidecar | 同签名重复→中断+重规划提示 | ✅ done (M3.4) |
| 上下文压缩 | 接近上限自动总结落盘 | A: Cline Auto Compact（零代码，验证即可） | 长任务自动 compact 不丢决策 | todo |
| 人工审批断点 | 高风险动作前硬暂停(interrupt) + Plan/Act 兜底 | A+C | 高风险动作暂停，resume 放行/否决 | ✅ done (M3.5) |
| 子Agent主从 | GLM 调度 / Kimi 执行，子任务干净上下文、结构化交回 | C: supervisor | 子上下文不含主线无关历史 | todo |
| IDE 控制面 | agent 工具管 终端/调试/任务/设置/扩展/环境 | Cline 扩展(typed API+executeCommand+CLI) | 各子系统可被 agent 操作 + 高风险审批 | todo（M4 起） |

## 已落地组件（Phase 1）
- `src/driving/observe.py` — cline 事件流解析 + 审计（可观测）。
- `src/driving/sidecar.py` — LangGraph 强制验证状态机：`build_graph(executor,verifier)` 可注入测试；`drive(task,cwd,verify_cmd,data_dir,db_path)` 用 SqliteSaver（崩溃恢复地基）。
- `tests/test_observe.py` / `tests/test_sidecar.py` — 确定性单测。
- `scripts/verify_milestone_3.sh` — M3.2+M3.3 一键验收（含 e2e）。

## Phase 1 DoD
- [ ] 驾驭层各能力实现且各有可重复测试（单测 + e2e）
- [ ] verify_milestone_3.sh 全绿，证据入 TEST_LOG
- [ ] 全量回归 verify_0/1/2 仍通过
- [ ] 无硬编码密钥；git commit + STATE 更新

## 下一步（Phase 1 续）
1. **人工审批硬断点**（sidecar：高风险工具前 `interrupt()`，注意副作用放断点之后/幂等）。
2. **子Agent主从**（langgraph-supervisor：GLM 调度、Kimi 执行，自定义 handoff 裁剪历史）。
3. **IDE 控制面扩展骨架**（Phase 1/2 衔接：注册环境/终端/调试工具）。
4. **上下文压缩**：验证 Cline 原生 Auto Compact 即可（零代码）。

## 风险
- 会话/进程重启杀后台服务（LiteLLM/SearXNG）→ 需 `start_proxy.sh` 重启；Phase 3 打包成托管服务根治。
- e2e 依赖 exo 集群在线 + 工具调用稳定（已 M0 实测）。
- LangGraph interrupt 的 node 重跑陷阱：副作用动作放断点之后或幂等（D11）。

## 阶段预告
- **Phase 2 · 环境**：environment-as-code（devcontainer + mise，D12）+ AI 管环境（改声明+rebuild）。
- **Phase 3 · 壳**：fork Code-OSS（VSCodium 脚手架，D14）+ 品牌化 + Cline 内建 builtin + Open VSX + 三平台签名公证 → 出安装器。
