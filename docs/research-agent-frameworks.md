# 调研：Python Agent 框架选型（M1→M5 骨架）

> 日期 2026-06-29 ｜ 多源 + context7 核对 LangGraph 1.2.x ｜ 置信：高(~85%)

## 结论：选 LangGraph（+ LangSmith / OTel）

唯一真正区分候选的硬指标是**原生执行态 checkpoint**（进程崩了能从中断处续跑，不是"对话记忆"）——这是 M5「崩溃恢复/断点续跑」的命根子，也是 M3「人工审批中断后恢复」的底座。LangGraph 把 checkpoint 做进**核心架构**，HITL(`interrupt()`)、子Agent、断点续跑共用同一 checkpointer；其余候选要么外挂(Pydantic-AI/OpenAI SDK 靠 Temporal)、要么把对话记忆误当 checkpoint、要么基座冻结。

## 候选对比（✅原生 / 🟡需外挂 / ❌无）

| 能力 | LangGraph | Pydantic-AI | OpenAI Agents SDK | AutoGen/AG2 | LlamaIndex |
|---|---|---|---|---|---|
| 自定义 OpenAI 兼容端点 | ✅ | ✅ | ✅ | ✅ | ✅ |
| 原生 tool calling + 流式 | ✅ | ✅ | ✅(须 Chat Completions) | ✅ | ✅ |
| **checkpoint(崩溃恢复)** | ✅核心 | 🟡Temporal/DBOS | ❌需 Temporal | 🟡有坑 | 🟡 |
| HITL 中断(审批) | ✅ | ✅ | ✅ | ✅ | ✅ |
| 子Agent(主-从) | ✅supervisor/swarm | 🟡委托 | ✅handoffs | ✅GroupChat | ✅ |
| 可观测/tracing | ✅LangSmith+OTel | ✅Logfire+OTel | ✅(默认外联OpenAI) | ✅OTel | ✅ |
| 2026 活跃 | ✅1.2.6 | ✅2.1.0(刚破坏性大改) | ✅0.17.7 | ⚠️microsoft/autogen 已冻结, 用 AG2 | ✅ |

## 选 LangGraph 的项目化理由
- **M5 崩溃恢复** = 决定性：`SqliteSaver`/`PostgresSaver` + 同 `thread_id` 重放即续跑，无需引入 Temporal 这类重型常驻服务。
- **M3 六件套同源**：人工审批/子Agent/可观测/循环上限全建立在同一 checkpoint+graph 上，审批恢复与崩溃恢复共用机制。
- **主-从双模型天然契合**：GLM(architect) supervisor + Kimi(coder) worker，各绑不同 `ChatOpenAI(model=别名)` 指向 :4000。

## 落地坑（已踩/必看）
1. **NO_PROXY(D5)**：LangGraph 用 httpx/openai SDK，会被本机 HTTP_PROXY 劫持发往 exo/:4000 的请求→502。Python 进程必设 `NO_PROXY`。（本项目 loop.py 走 localhost:4000 本不受影响，已防御性设置。）
2. LiteLLM 只暴露 architect/coder 别名 → agent 必须显式传 model 别名，否则默认 gpt-* 会 404。
3. checkpoint 后端：原型用 `InMemorySaver`(进程退出即丢，**不满足 M5**)；M5 必须换 `SqliteSaver`/`PostgresSaver`。
4. `create_react_agent`(`langgraph.prebuilt`) 在 V1 已弃用 → V2 用 `langchain.agents.create_agent`(签名近似)。本项目 M1 暂用旧 API + 静默告警，待 M3 装 `langchain` 再迁移。
5. 生态分包多、有过 API 改名/yank 版本 → **锁版本**(`langgraph==1.2.6`)。

## 当前已装（M1）
`langgraph==1.2.6` + `langchain-openai==1.3.3`（经清华 PyPI 镜像）。M3/M5 再加 `langgraph-checkpoint-sqlite` / `langgraph-supervisor` / `langsmith`。

## 反向提示（来自调研）
M1 的最小 loop 本可不引框架；但已按用户决策用成熟框架(LangGraph)起步，框架成本花在最需要它的 M3/M5。

> 全量对比/来源见会话记录 task abf81330d7d50cc72（含各框架官方文档 URL）。
