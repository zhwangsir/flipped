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
- **调研确认(2026-06-29)**：exo **原生支持结构化 tool_calls**（按模型分派解析器，无 `--tool-call-parser` CLI flag）；Kimi-K2 与 GLM 均有 exo 专用解析器 + 单测 → **M0.4 大概率通过**。唯一风险是 K2.7/GLM-5.2 版本命名匹配，以实测为准。详见 [research-exo-toolcalling.md](research-exo-toolcalling.md)。

## D4 · M2 编辑器基座 = Cline（已定 2026-06-29）
- **日期**：2026-06-29 ｜ **批准**：⏳ pending（ISSUE-2）
- **背景**：AGENTS.md M2 要求"fork Roo Code"。但调研确认 **Roo Code 于 2026-05-15 被官方归档停服**（仓库只读、末版 v3.54.0，团队转云端 agent Roomote）。作为 fork 基座意味着无上游更新、无安全补丁、社区迁走。
- **候选**：
  - **Kilo Code**（推荐）：Roo Code 的 fork，与 Roo 共享真实 git 历史；Apache-2.0；2026 活跃维护；自定义模式=custom agents，支持 **Sticky Models**（按 agent 钉模型，可声明式做到 Architect→GLM-5.2 / Coder→Kimi-K2.7-Code，修复 Roo 仅 UI 绑定的弱点）；有 Roo→Kilo 迁移向导（.roomodes→.kilo/agents/*.md）。
  - **Cline**：Roo 的上游；MIT（更宽松）；5M+ 安装、社区最大；多 agent/coordinator 委派，不同 agent 可配不同模型。基座最干净，但"按模式分模型"需用其多 agent 机制自行组织。
- **影响**：选 Kilo → AGENTS.md M2 的 Roo 思路几乎平移，per-mode-model 更顺；选 Cline → 基座更稳但模式体系要重搭。两者都原生支持 OpenAI Compatible 指向 LiteLLM :4000。
- **新证据(2026-06-29 调研)**：exo 社区实测(#1840)反馈 **Cline 对本地模型最稳**；Kilo Code 有 `MODEL_NO_TOOLS_USED` 通病、需手动开工具开关并对齐 Model ID/context window。这与"Kilo 更贴合 per-mode-model"形成真实权衡。
- **修正建议**：本项目命根子是工具调用稳定性、且 exo 是实际后端 → 建议在 **M0.4 实测拿到 ground truth 后再定基座**（可顺带 A/B 两个客户端）。若需现在选：要稳→Cline，要贴合 AGENTS.md 模式体系→Kilo，略偏 Cline。
- **不阻塞**：M0/M1 不依赖此决策；到 M2 前定即可。
- **决议（2026-06-29）**：选 **Cline**。决定因素 = exo 社区实测(#1840)Cline 对本地模型最稳，而 exo 是我们后端→稳定性压倒一切；MIT 最自由；Roo 上游=AGENTS.md 思路本源；最活跃。Kilo 的 Sticky-Models 虽贴合但 `MODEL_NO_TOOLS_USED` 对工具调用敏感场景有风险。**M2 策略**：先 install+配置验证编辑器流（指向 :4000，Plan/Architect→GLM、Act/Coder→Kimi），**源码 fork 推迟到 M3** 加驾驭层时再做（届时才需要改源码）。
- **M0 实测补充(2026-06-29)**：exo 工具调用已对两模型实测通过；编辑器栈 Node fetch 直连 exo 正常（且不受本机代理影响，见 D5）→ M2 基座技术风险已基本排除，可在 Cline/Kilo 间随时定。

## D5 · 访问 exo 必须绕开本机 HTTP 代理（NO_PROXY）
- **日期**：2026-06-29 ｜ **批准**：实测根因
- **背景**：开发机设了 `HTTP_PROXY=HTTPS_PROXY=http://127.0.0.1:7890`(Clash)，`NO_PROXY` 未含 exo 内网 IP。Python httpx/urllib（含 LiteLLM）读大写 `HTTP_PROXY` → 把发往 `100.64.201.37` 的请求塞进代理 → 代理到不了内网 → **502**。
- **为何 curl/Node 不受影响**：curl 出于 httpoxy 安全只认小写 `http_proxy`(未设)；Node fetch / 裸 socket 不读代理 env。
- **决策**：所有访问 exo 的 Python 进程必须 `export NO_PROXY=100.64.201.37,...`（已写入 `scripts/start_proxy.sh` 与 `scripts/verify_milestone_0.sh`）。
- **影响**：解释了此前大量"集群 502"实为本机代理劫持而非集群故障；修复后 M0.4/M0.5 全通过。编辑器(Node)无需此设置。

## D6 · agent 框架 = LangGraph
- **日期**：2026-06-29 ｜ **批准**：用户（"用成熟框架"）+ 调研推荐
- **背景**：M1 需 agent loop；用户选"用成熟框架"。调研对比 LangGraph/Pydantic-AI/OpenAI Agents SDK/AutoGen/LlamaIndex（详见 [research-agent-frameworks.md](research-agent-frameworks.md)）。
- **决策**：选 **LangGraph**。决定性理由：唯一把**原生执行态 checkpoint** 做进核心架构 → 直接支撑 M5 崩溃恢复/断点续跑 + M3 人工审批中断恢复（同源机制），且主-从双模型(GLM supervisor / Kimi worker)天然契合。
- **现状**：M1 已装 `langgraph==1.2.6`+`langchain-openai==1.3.3`，用 `create_react_agent` 跑通 ReAct loop。M3/M5 再加 checkpoint-sqlite/supervisor/langsmith，并迁移到 `langchain.agents.create_agent`。

## D7 · 中国网络：镜像源 + 容器出站代理
- **日期**：2026-06-29 ｜ **批准**：实测
- **背景**：Clash(7890) 对 Docker Hub/PyPI 大文件下载反复 EOF；SearXNG 容器直连搜索引擎超时。
- **决策**：① Docker 镜像走 `docker.m.daocloud.io`；② pip/uv 走清华 `pypi.tuna.tsinghua.edu.cn`；③ SearXNG `outgoing.proxies` 指向 `http://host.docker.internal:7890`（宿主 Clash）。
- **影响**：避免反复重试浪费；后续新依赖/镜像默认走镜像源。
