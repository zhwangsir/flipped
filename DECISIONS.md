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

## D8 · M2 验收方式 + 工程化修复
- **日期**：2026-06-29 ｜ **批准**：实测
- M2 验收用 **Cline CLI headless**（与编辑器同一 agent core，免 GUI/computer-use）在隔离 fixture 跑多文件改动。
- `web_search` 加"瞬时空结果/网络错自重试"（§6）：agent loop 消息数 192→4。
- verify_0/1/2 加固（多 query/加时长，**不放宽断言**）。
- 运维：macOS **无 setsid**；后台服务（LiteLLM/SearXNG）用 run_in_background，会话重启后需 `start_proxy.sh` / `docker compose up` 重启。

## D9 · 驾驭层（M3）三层分工，不 fork Cline
- **日期**：2026-06-29 ｜ **批准**：调研(task wuw3zewas) + 推荐
- **决策**：6 件套按"Cline 原生 / hooks 单步守门 / LangGraph 跨步状态机"分工，**不需 fork(B)**。详见 [research-cline-hooks-driving-layer.md](research-cline-hooks-driving-layer.md)。
  - **A（Cline 原生/hooks）**：上下文压缩(Auto Compact 零代码)、可观测采集(PostToolUse 日志 hook)、单步守门(PreToolUse)、日常审批(Plan/Act+auto-approve)。
  - **C（LangGraph，复用 M1/D6）**：强制验证、循环检测、子Agent主从(supervisor)、硬审批断点(interrupt)、可观测归档(checkpoint)。
- **理由**：Cline hooks 是单次调用边界回调（无跨步记忆、不能强制下一步），LangGraph 的 checkpoint+interrupt+supervisor 正好补跨步状态机这层。
- **前置**：C 侧崩溃恢复须把 checkpointer 从 InMemorySaver 换 SqliteSaver/PostgresSaver；interrupt 副作用须放断点之后/幂等；supervisor handoff 须裁剪历史。
- **顺序**：先 A 侧（含 PostToolUse 日志 hook 实测）→ 搭 C supervisor 骨架 → 接 (1)(2)(4硬断点)(5)。

## D10 · 产品形态 = 桌面 IDE（fork VS Code / Code-OSS）— 重大转向
- **日期**：2026-06-29 ｜ **批准**：用户
- **决定**：最终产品是类似 IDEA / VSCode / HBuilder 的**桌面 IDE**（不是个人装置/一键套件）。目标用户：自己/少数人。
- **实现路径（提案，待调研 wvwkbktvg 确认）**：fork **Code-OSS**(VSCode 内核)换皮成品牌 IDE（Cursor/Windsurf/字节 Trae 模式——业界都是 fork，无人从零写 IDE），内建 Cline 派生的 AI agent。
- **重大影响**：
  - **D9 重定**：驾驭层不能是外部 Python 进程（桌面产品里不能让用户单跑 LangGraph）→ 移入**内建扩展(TS, 可能 fork Cline)** 或 **IDE 随启 sidecar 服务**（复用现有 Python/LangGraph）。待调研定。
  - **D4 演进**：Cline 从"配置使用"升级为"内建/fork 进 IDE"。
  - **路线重排**：M2–M5 围绕 IDE 产品重排；M5 产线化 = 出桌面 IDE 安装器(签名/公证/Open VSX)。
  - **M0–M3 复用**：M0(LiteLLM/exo)→模型后端(端点外置让用户填)；M1 搜索→内建工具/MCP；M3.2 observe.py→并入扩展或 sidecar。不废，但 re-home。
- **策略**：两阶段——先做扎实"脑"(AI agent + 驾驭层 as 扩展)，再做"壳"(fork+换皮+打包桌面 App)。脑未验证前不先做壳。

## D11 · 驾驭层落点 = Cline 原生/hooks + LangGraph 本地 sidecar
- **日期**：2026-06-29 ｜ **批准**：调研(wbnb5vubp) + 推荐
- 承接 D9：压缩→Cline Auto Compact；采集→PostToolUse(observe.py)；守门→PreToolUse；日常审批→Plan/Act；**强制验证/循环检测/子Agent主从/硬审批/checkpoint 归档 → LangGraph 本地 sidecar**。
- **否决**：脑验证前把 LangGraph 用 TS 重写进 Cline fork（高成本零增量）。佐证：Cursor=独立 Rust 编排服务(Anyrun)、Windsurf=独立本地 Rust agent——重 agent 逻辑放独立进程。
- 打包：`python-build-standalone` + `uv` 经 `electron-builder extraResources`（**否决 PyInstaller 黑盒**）；主进程 spawn + /health 探活 + 退出 kill；macOS 逐二进制签名+公证。模型端点外置为用户可填。

## D12 · 随项目内置环境 = Dev Containers + mise（Nix 为 power 选项）
- **日期**：2026-06-29 ｜ **批准**：调研 + 推荐
- 主干 **Dev Containers**(devcontainer.json + Features 层叠多语言) + **mise**(.mise.toml 版本钉定，容器内/本地共用)；**Nix flake** 进阶可选；运行时打进安装器仅离线兜底。
- AI 管环境 = 改 `devcontainer.json`/`.mise.toml` 两个声明文件 + 触发 Rebuild 自愈。提供 mise-only 降级(原生 Windows/无 Docker)。
- Windows 前置 WSL2+Docker Desktop，源码放 WSL FS。真复现需锁镜像 digest + Feature 版本 + .mise.toml。

## D13 · AI 控制面 = 薄扩展注册工具，不为控制 IDE 而 fork
- **日期**：2026-06-29 ｜ **批准**：调研 + 推荐
- 三控制面叠加：Cline 现有工具 + typed 扩展 API(tasks/debug/settings/terminals) + executeCommand 内建命令(装扩展/重载) + CLI(devcontainer/nix)。建薄"IDE 控制面"扩展注册为 MCP/Cline 工具。
- fork 仅为：外壳品牌化 + 必须在 stable 用的 proposed API 白名单。
- **安全**：高风险(rebuild/nix 改动/装扩展/User 设置写/任意终端)→人工审批；只读自省自动放行。坑：内建命令 ID 跨 fork/版本不稳，防御性校验。

## D14 · 外壳 = Code-OSS fork（VSCodium 脚手架）+ 阶段化路线
- **日期**：2026-06-29 ｜ **批准**：调研 + 推荐
- 用 **VSCodium 构建仓库**为脚手架换皮；市场=**Open VSX**(微软市场红线)；不打包微软闭源 builtin；**Cline(Apache-2.0) 作 bundled builtin**(留 LICENSE/NOTICE)；三平台签名公证。
- 佐证：Cursor/Windsurf/Trae 均 Code-OSS fork + Open VSX。代价：上游月度 rebase、签名/公证、Open VSX 供应链审计。
- **阶段化(脑→环境→壳)**：Phase 1 脑(stock VS Code 里做完 agent+控制面+sidecar+驾驭层) → Phase 2 环境(environment-as-code + AI 管环境) → Phase 3 壳(fork+品牌+打包出安装器=M5)。脑先于壳。

## D15 · 核心架构原则：多 Agent 协作 + 专属监督 Agent；恒用最新最强技术
- **日期**：2026-06-30 ｜ **批准**：用户
- **要求**：(1) 所有内容上最新最强技术；(2) 任何任务由多个 agent 协作完成，并设**专属"监督 Agent"**监督其他 agent 的**效率**与**方向**是否有偏。
- **落地**：驾驭层从"主从(GLM 调度/Kimi 执行)"升级为"**多 Agent 编排 + 监督**"：
  - **Supervisor(GLM)**：拆解任务、调度 worker、综合结果。
  - **Worker(s)(Kimi via cline)**：执行子任务，受 sidecar 强制验证/循环检测治理。
  - **Overseer/监督(GLM，专属)**：实时看 worker 轨迹(observe)，评估效率(绕路/重复/低产)与方向(是否偏离目标)，发现问题即干预(令 supervisor 重规划/换法/中止)。
  - 技术：`langgraph-supervisor`(最新) + 自定义 overseer 节点 + checkpoint/interrupt。
- 把原 M3.6 子Agent主从**提升为核心要求**，贯穿全产品（IDE 内每个任务都走此编排）。
- **"最新最强"**：LangGraph 最新 + GLM-5.2/Kimi-K2.7(本地最强) + Cline 当前版 + Code-OSS fork(业界标准)；新依赖默认取最新稳定版。

## D16 · GLM/exo 结构化输出必须用 method="function_calling"（§6 工程化）
- **日期**：2026-06-30 ｜ **批准**：实测
- **现象**：orchestrator 的 supervisor/overseer 用 `with_structured_output`(langchain 默认 `json_schema`) 对 GLM **校验失败**(GLM 返回 markdown 非 JSON)→fail-open，"GLM 智能监督"形同虚设。
- **实测**：`json_schema` ✗ / `json_mode` ✗ / **`function_calling` ✓**(GLM 返回正确结构；M0.4 已证 GLM 支持工具调用)。
- **约定**：所有对 GLM/Kimi(经 LiteLLM/exo)的 `with_structured_output` 一律 `method="function_calling"`。已修 orchestrator 两处。

## D17 · Phase 3 壳 Windows release = GitHub Actions 云构建 + 首版未签名
- **日期**：2026-06-30 ｜ **批准**：用户
- **硬约束**：本机为 macOS(Darwin ARM64)，**无法构建 Windows 原生安装包**(node-pty/spdlog/native-watchdog 等原生模块需 Windows MSVC 工具链；VSCodium 官方亦按平台在对应 OS 的 runner 出包)。
- **路径(用户选)**：A = **GitHub Actions `windows-latest` 云构建** — fork→品牌→内建(Cline+ide-extension)→sidecar 打包→Inno Setup installer 全写成 CI workflow，推到 `zhwangsir/flipped`(公开 repo，Windows runner 免费)，云端产出 `.exe`/`.msi`。否决 B(需用户本地 Windows 机器)/C(轻量 Tauri 壳，偏离 D14)。
- **签名(用户选)**：首版**未签名**分发(SmartScreen "未知发布者" 警告，用户手动放行)；CI 预留 Authenticode 接口(signtool/azure-code-signing + secret)，待用户备证书后启用。
- **发布门**：CI 产出 artifact 后**先给用户确认**再 `gh release create`(发布=对外动作)。
- **多端**：Windows 跑通后，同一管线加 `macos`/`linux` job 成矩阵(承接 D14 三平台)。

## D18 · 重大转向：产品 = AI 开发工厂(OpenHands 基座 + 我们的多 Agent 监督)，弃"VSCodium 编辑器"方向
- **日期**：2026-07-01 ｜ **批准**：用户(纠偏 + 全权委托"做出效果最好、甚至超过单 agent")
- **背景**：之前把产品当成"桌面 IDE(VSCodium 换皮)"在推(D10/D14/D17)——**编辑器中心，跑偏**。用户真实意图：像 **Claude Code / Codex** 的**本地模型驱动 agent 平台**——AI 自主用工具在**沙盒**里干活、**内置浏览器**、工具齐全(AI 开发工厂)。
- **决策**：
  - **基座 = OpenHands**(`github.com/OpenHands/OpenHands`，MIT，~79k★，活跃)。现成提供：Docker 沙盒(`DockerWorkspace`/runtime)、AI 浏览器(`BrowserToolSet`/browser-use/Playwright)、原生 MCP + 内置工具、**Agent Canvas Web 控制台**、LiteLLM(接 `:4000`)、**Python SDK + `AgentBase` 可扩展**。
  - **我们的差异化(保留并复用)= 多 Agent 监督编排**(`orchestrator.py`：Supervisor GLM + Overseer GLM)作**外层 orchestrator**：经 OpenHands Python SDK 把子任务派进 fresh `DockerWorkspace` 执行，经 `conversation.state.events`/callbacks 让 Overseer 监督效率与方向。Worker 由"cline CLI"切换为"OpenHands 沙盒 Conversation"。
  - **本地模型**：GLM/Kimi via LiteLLM `:4000`(`openai/<name>` 前缀 + 在 LiteLLM 注册模型能力)。GLM-5.2-fp8 工具调用 M0.4 已验证，缓解 OpenHands 对弱工具调用模型的已知摩擦(#11632/#6918 等)。
  - **交互**：先 Agent Canvas Web 控制台；后续 Electron 包成桌面 App(承接用户"桌面 App 后续")。
- **取代**：D10/D14/D17 的"桌面 IDE/VSCodium fork/Windows 安装器"方向降级搁置(未推的 `release-windows.yml` 暂不推进)。Cline 仍可作可选 worker/参考。
- **候选横评依据**(均一手核实)：OpenHands ✓(沙盒+浏览器+MCP+Web+SDK)；Cline(最佳 agent 运行时但无沙盒)；SWE-agent/mini(研究/维护态)；Goose(无浏览器/沙盒)；Continue(仓库只读)；Tabby(非 agent)；bolt.diy(浏览器内 WebContainer，无 Docker/Python)；Devika(已弃)。
- **风险**：OpenHands 本地模型工具调用摩擦 → spike 首步验证；上游活跃但 rebrand 频繁(registry/命名变动)需以官方 quickstart 为准。

## D19 · Bot Channel 平台选型：Telegram raw httpx + 企业微信(WeCom)应用回调
- **日期**：2026-08-05 ｜ **批准**：实测勘察(PLAN M182)
- **背景**：用户要求「Telegram 机器人 + 微信机器人」完整接入。勘察结论：**个人微信无官方 bot API**（任何个人号机器人方案都是逆向协议，有封号风险且随时失效）。
- **决策**：
  - **Telegram 走 raw httpx**（已有依赖），Bot API sendMessage + webhook secret_token 头验证(hmac.compare_digest)，**零新增重依赖**（不引 python-telegram-bot）。
  - **微信落地企业微信(WeCom)应用回调**：SHA1 验签 + AES-256-CBC 加解密(pycryptodome 新增登记)，pycryptodome 缺失时 available()=False 优雅降级不炸后端。个人微信接入明确不进路线图。
  - token/secret 全走 env(FLIPPED_BOT_TELEGRAM_TOKEN/SECRET、FLIPPED_BOT_WECOM_*)，绝不硬编码；httpx trust_env=False(D5 防线)。
- **影响**：M182 落地；STATE.json M182 known_limitations 首条注明个人微信取舍；用户若坚持个人微信需另行决策（逆向协议风险自担）。

## D20 · 列表类 API 契约：返回全量插入序，展示排序职责下沉消费侧
- **日期**：2026-08-05 ｜ **批准**：契约勘误实测(M183 verify d2/e1/e2 失败定位)
- **背景**：verify_m183.sh 初版断言假设 GET /worker/rules「按 priority desc 排序 + 停用规则消失」，与实现不符三连败。定位后确认真实契约意图：前端 WorkerRulesPanel 自行排序展示，且需看到停用规则以便复启；注入层(build_worker_rules_text)才是 priority desc 的真正消费方。
- **决策**：**列表 GET 接口一律返回全量(含停用/软删除项)按插入序**；排序/过滤是消费侧职责（前端展示排序、注入层 priority desc），服务端不做展示优化。停用项留列表供复启（toggle 是状态翻转不是删除）。
- **理由**：单一数据源不做多视图；消费侧各取所需（面板要全量可复启、注入层要 enabled+排序）；契约稳定不随 UI 需求漂移。
- **影响**：修脚本对齐契约而非改实现（契约勘误流程：先查 PLAN 与前端真实消费再定归属）；M183 verify d2/e1/e2 改为校验 PUT 落库/toggle enabled 字段；注入层排序正确性由真 local_worker 黑盒 l2/l3 钉死。
