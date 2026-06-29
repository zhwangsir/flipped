# PLAN.md — 当前里程碑：M1 · 工具链基线

> M0 已完成（详见 STATE.json / DECISIONS.md / TEST_LOG.md）。本文件现描述 M1。

## M1 目标（AGENTS.md §5）

自托管 SearXNG → 实现联网搜索工具并验证可返回结果 → 搭一个最小 agent loop，能调用该工具完成一个真实查询任务。

**验收**：给一个需要实时信息的任务，agent **自主调用搜索**并给出**有来源**的答案。

## 链路

```
最小 agent loop (GLM-5.2 主 Agent, 经 LiteLLM:4000 或 exo 直连)
   --tool_call--> web_search 工具 --HTTP--> 自托管 SearXNG (:8080, JSON 输出)
   <--结构化结果+来源URL--                            搜索多引擎聚合
```

## 步骤与验收

| # | 步骤 | 涉及文件 | 验证方式 | 状态 |
|---|------|----------|----------|------|
| M1.1 | 部署 SearXNG（Docker），开启 JSON 输出 | infra/searxng/{docker-compose.yml, settings.yml} | `curl 'localhost:8080/search?q=test&format=json'` 返回结果 JSON | todo |
| M1.2 | web_search 工具：query → SearXNG JSON → 结构化 {title,url,snippet} | src/tools/web_search.py | 单测：给定 query 返回 ≥1 条带 url 的结果 | todo |
| M1.3 | 最小 agent loop：GLM 经工具调用自主搜索→综合带来源答案 | src/agent/loop.py | 跑一个实时问题，loop 自主调 web_search 并引用来源 | todo |
| M1.4 | 一键验收 | scripts/verify_milestone_1.sh | 退出码 0：实时问题→自主搜索→有来源答案 | todo |

## M1 完成定义（DoD §8）

- [ ] SearXNG 可返回 JSON 搜索结果
- [ ] web_search 工具有单测且通过
- [ ] agent loop **端到端**跑通一个真实实时查询（真实 agent loop，非仅测函数 — §3）
- [ ] verify_milestone_1.sh 实跑通过，输出记入 TEST_LOG
- [ ] 全量回归（含 verify_milestone_0.sh）仍通过
- [ ] 无硬编码密钥；git commit + STATE 更新

## 关键设计决策（待确认）

1. **SearXNG 部署 = Docker**（docker-compose，本机已装 docker 29.5）。已知坑：SearXNG **默认禁用 JSON 输出**，settings.yml 须加 `search.formats: [html, json]`；本地用需放宽 limiter/bot 检测。
2. **agent loop 实现**：
   - (A) **最小手写**：~150 行 Python，直接对 exo 的 OpenAI 兼容 API 跑 tool-calling 循环（复用 M0 已验证的工具调用 + NO_PROXY）。轻、可控、零新框架。
   - (B) **复用 DeepAgents 骨架**：AGENTS.md 多次提到"先前的 DeepAgents 骨架"/ M4 要把 DeepAgents 包成 MCP。若你已有该骨架，可移植以与 M4 衔接。
3. **主 Agent 模型** = GLM-5.2（编排者，AGENTS.md 指定）；经 LiteLLM `architect` 别名或 exo 直连。

## 依赖与风险

- 新依赖：Docker SearXNG 服务（§7 新服务，已随"选 M1"获批）。Python 侧仅用 httpx（已装）。
- 风险：SearXNG JSON 默认关 / limiter 拦截 localhost / 公共实例不可用故必须自托管；agent loop 访问 exo 需 NO_PROXY（D5），访问 SearXNG 是 localhost（在 NO_PROXY 内）。

## 下一里程碑预告（M2）

编辑器形态：基座在 Cline / Kilo 间定（D4），接 :4000，Architect→GLM / Coder→Kimi。M1 通过后展开。
