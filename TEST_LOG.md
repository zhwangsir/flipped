# TEST_LOG.md — 测试与验证证据流水

> 命令 + 输出摘要 + 结论，追加写入（AGENTS.md §3）。

## [2026-06-29] M0 前置勘察（首次接管）

### 宿主机硬件核对
- 命令：`sw_vers` / `sysctl machdep.cpu.brand_string hw.memsize` / `df -h /`
- 输出摘要：macOS 26.5 (25F71)；**Apple M5 Max**；**128GB RAM**；磁盘 1.8TB / 剩 1.1TB。
- 结论：与 AGENTS.md「2TB」假设不符 → 本机为开发/控制节点（决策 D2）。

### exo 集群目录可达性
- 命令：`curl -s http://100.64.201.37:52415/v1/models`
- 输出摘要：返回 **140 个模型**，含 `mlx-community/GLM-5.2-DQ4plus-q8` 与 `mlx-community/Kimi-K2.7-Code-4bit`（均在线）。
- 结论：M0.2 ✅ 通过 — 服务层已是 OpenAI 兼容（决策 D1）。

### exo 集群拓扑（/state）
- 命令：`curl -s http://100.64.201.37:52415/state`
- 输出摘要：2 个实例 — GLM-5.2(4 分片, ~465GB, 78 层) + Kimi-K2.7-Code(4 分片, ~641GB, 61 层)；Thunderbolt 桥接、张量并行；存在多个 `DownloadPending` 分片。
- 结论：模型分片仍在下载/放置，未进入可服务状态。

### 🔴 致命阻塞：推理面 502
- 命令：对 `GLM-5.2-DQ4plus-q8` / `Kimi-K2.7-Code-4bit` / `Qwen3-0.6B-8bit` 发 `/v1/chat/completions`（纯聊天 + 带 tools 两种）。
- 输出摘要：**全部 5 秒快速 502 Bad Gateway**（连最小模型也 502，非冷加载超时）。
- 结论：集群推理整体不可用 → ISSUE-1。M0.4 工具调用验证 **blocked**，已启动后台监控 `monitor_cluster.py` 等恢复自动复验。

### 本地工具链
- 命令：逐个 `--version`
- 输出摘要：git 2.50 / node v24.14 / npm 11.12 / pnpm 11 / python3 3.9.6 / docker 29.5 / uv 0.11 / brew 6.0 ✅；缺 litellm / code CLI / yarn。
- 结论：开发工具链基本就绪，M0.3 起草 LiteLLM 配置前需 `pip install litellm` 或用 docker 镜像。

---

## [2026-06-29 15:52:19] 集群恢复监控启动
轮询 http://100.64.201.37:52415/v1/chat/completions，每 120s，最多 30 次。

## [2026-06-29] M0.3 LiteLLM 代理验证 + M0.6 验收脚本

### LiteLLM 安装
- 命令：`uv venv --python 3.11 .venv && uv pip install 'litellm[proxy]'`
- 结果：**LiteLLM 1.90.0** 装入 `.venv` ✅

### 代理别名暴露（不依赖集群）
- 命令：`litellm --config infra/litellm/config.yaml --port 4000` 后台启动；`curl /v1/models`
- 输出：`data=[architect, coder]`；`/health/readiness = {"status":"healthy"}`
- 结论：**M0.3 配置层 ✅** — 别名机制成立，对外仅暴露 architect / coder（隐藏真实 model id）。

### M0 验收脚本实跑（scripts/verify_milestone_0.sh，退出码 1）
- M0.2 exo 目录：✅ GLM-5.2 / Kimi 均在
- M0.3 代理别名：✅ architect / coder
- M0.4 工具调用(exo 直连)：❌ 两模型均 502（集群未恢复，命根子待验）
- M0.5 经代理路由：❌ 上游 502 → 降级耗尽
- 结论：M0 中**不依赖实时推理的部分全部就绪**；M0.4/M0.5 待集群恢复（monitor_cluster.py 盯）。退出码 1 是诚实反映集群阻塞，非脚本缺陷。

### 调研补记（M2 基座）
- Roo Code 已于 2026-05-15 停服归档 → ISSUE-2 / 决策 D4（待用户在 Kilo Code / Cline 间选）。

## [2026-06-29] exo 4 台 RDMA 诊断（为何只能 2 台）+ 集群现状复查

### 集群现状（/state 实测）
- 4 台 dgmt-studio01-04，均 Mac Studio **M3 Ultra / 512GB / macOS 26.5.1**（4×512=2TB，即 AGENTS.md 的"2TB"）。
- `instances=0`（无模型 LAUNCH）；`DownloadPending=553` 分片；推理 502 = **没有模型在服务**（502 直接根因 = 未 LAUNCH + 仍在下载）。

### RDMA 邻接（topology.connections 解析）
- 6 对节点中 **5 对有直连 RDMA，唯独 studio01↔studio02 降级为纯 TCP/IP**（无 sourceRdmaIface）。
  - ✅ 01-03 / 01-04 / 02-03 / 02-04 / 03-04 ｜ ❌ 01-02
- `nodeThunderboltBridge`：四台全 `exists:false/enabled:false`；`thunderboltBridgeCycles=[]`（未检测到环）。
- `nodeRdmaCtl`：四台 `enabled:true`（控制器本身 OK）。
- RDMA 链路当前走 **80Gb/s** 口（en3/4/5）；**120Gb/s 的 TB5 口（en6/en7）闲置**。

### 结论
- 4 台 RDMA 起不来 = 缺 01↔02 链路 + Thunderbolt Bridge 未建立（cycles=[]）→ exo 组不出 ≥3 台张量组，退回 2 台。
- 注：剩余 5 边已含 4 环(01-03-02-04)，故主因更可能是 **TB Bridge 未建立**。
- 修复：① 重插 01↔02 雷雳线（优先 TB5 口）② 确认四台 Thunderbolt Bridge 启用 ③ 点 LAUNCH（Kimi 597GB 在 2 台 1024GB 即可先解锁 M0.4）。

## [2026-06-29 17:12:35] 集群恢复监控启动
轮询 http://100.64.201.37:52415/v1/chat/completions，每 180s，最多 60 次。

## [2026-06-29] 🎉 M0 完成 — 根因(本机代理)定位 + 工具调用全通过

### 根因：本机 HTTP 代理劫持 Python 请求（非集群问题）
- 现象：curl / Node fetch / 裸 socket 直连 exo = 200；但 Python httpx/urllib（连 GET 都）= 502。
- 定位：开发机 `HTTP_PROXY=HTTPS_PROXY=http://127.0.0.1:7890`(Clash)，`NO_PROXY` 未含 `100.64.201.37`。
  - httpx/urllib 读大写 HTTP_PROXY → 把 exo 请求塞进代理 → 代理到不了内网 IP → 502。
  - curl 只认小写 http_proxy(防 httpoxy)未设 → 直连成功；Node fetch 不读代理 env → 成功；裸 socket 直连 → 成功。
- 验证：httpx `trust_env=False` → 200；设 `NO_PROXY=100.64.201.37` → 200。
- 修复：start_proxy.sh / verify_milestone_0.sh 均 export NO_PROXY 含 exo IP（LiteLLM 的 httpx 同样需要）。见 D5。

### M0.4 工具调用（命根子）✅ 全通过
- GLM-5.2  流式&非流式：`get_weather({"city":"Tokyo"})` finish_reason=tool_calls
- Kimi-K2.7-Code 流式：`get_weather({"city":"Tokyo"})` finish_reason=tool_calls
- 结论：exo 对两模型工具调用解析正确（与 docs/research-exo-toolcalling.md 一致）；流式/非流式皆可。

### M0.5 经代理路由 ✅
- architect→GLM-5.2、coder→Kimi-K2.7-Code 经 LiteLLM(:4000) 均返回结构化 tool_calls。
- 部署拓扑 = 配法 B(2+2)：GLM 在 studio04+02、Kimi 在 studio03+01（不相交 RDMA 对，绕开断掉的 01↔02）。
- 注：fallback(架构↔执行) 已配置，但未做"停一个实例"的故障注入实测（需用户许可，避免打断现有部署）。

### M0 一键验收 verify_milestone_0.sh ✅ 退出码 0
- M0.2 ✅ ｜ M0.3 ✅ ｜ M0.4 ✅✅ ｜ M0.5 ✅ ｜ **M0 验收：全部通过**

## [2026-06-29] 🎉 M1 完成 — 工具链基线全通过

### 网络坑与解法（中国网络 + Clash）
- Docker 拉 searxng：docker.io/ghcr 大层经 Clash 反复 EOF → 改用国内镜像源 `docker.m.daocloud.io/searxng/searxng:latest` 一次成功，retag 回 `searxng/searxng:latest`。
- pip 装 langgraph：PyPI 经 Clash 也断 → 改用清华镜像 `--index-url https://pypi.tuna.tsinghua.edu.cn/simple` 成功。
- SearXNG 容器出站访问搜索引擎：直连超时 → settings.yml 配 `outgoing.proxies: all:// → http://host.docker.internal:7890`（容器内 host.docker.internal=192.168.5.2，即宿主 Clash），引擎恢复。

### M1.1 SearXNG ✅
- `curl 'localhost:8080/search?q=LangGraph&format=json'` → 200 application/json，20 条结果（brave/wikidata 等经代理返回）。

### M1.2 web_search 工具 ✅
- `tests/test_web_search.py` 全过（≥1 结果含 http URL、空 query 抛 SearchError、format_for_llm）。
- 多 query 实测（中英文）均返回结构化结果。

### M1.3 agent loop（LangGraph ReAct, GLM-5.2 via :4000）✅
- 真实问题"搜索 SearXNG 是什么"→ agent **自主调用 web_search**(searched=True, 4-5 消息)→ 输出带 [n] 引用 + 来源 URL 的中文答案。
- 这是 AGENTS.md M1 验收标准（需实时信息的任务，自主搜索 + 有来源）。

### M1 一键验收 verify_milestone_1.sh ✅ 退出码 0；M0 回归 ✅ 退出码 0
- M1.1 ✅ ｜ M1.2 ✅ ｜ M1.3 ✅ ｜ M0 全 ✅（无回归）

## [2026-06-29] 🎉 M2 完成 — Cline 编辑器接入 + 多文件改动端到端

### 安装与配置
- Cline CLI v3.0.33（`npm i -g cline`；平台二进制 `@cline/cli-darwin-arm64` 走**官方** registry，npmmirror 缺）+ VS Code 扩展 v4.0.2（saoudrizwan.claude-dev）。
- `cline auth openai-compatible -b http://localhost:4000/v1 -m coder`（隔离 `--data-dir .cline-data`，gitignored）。

### M2.4 多文件改动端到端（cline headless, coder=Kimi via :4000）✅
- 隔离 fixture（mathlib.py/app.py/test_math.py，基线 `add=-1` 测试失败）。
- cline 自主：读 3 文件 → 修 add bug → 加 multiply → app.py 加 product() → 跑 `python3 test_math.py` → **ALL PASS**；git diff=2 文件；退出码 0。
- 正是 AGENTS.md M2 验收（读→改→跑→自检）。M2.3 architect/GLM 经 :4000 curl 200；M2.2 配置 ✅。
- 关键洞察：用 Cline **CLI headless**（与编辑器同一 agent core）做自动化验收，免 GUI/computer-use；fork 留 M3。

### 工程化修复（§6 遇错即工程化）
- `web_search` 加"瞬时空结果/网络错自重试"（`SEARXNG_RETRIES` + 短退避）：agent loop 消息数 **192 → 4**，单测转稳。
- verify_0/1/2 加固（不放宽断言）：M0.2 catalog `--max-time 30`；M1.1/单测 多 query 任一命中；M2.3 curl 直验。
- 运维坑：LiteLLM 代理 / SearXNG 在**会话重启时被杀**，需 `start_proxy.sh` / `docker compose up` 重启；macOS **无 setsid**（detached 失败）。

### 三里程碑全绿（各自单独前台跑，退出码均 0）
- verify_milestone_0.sh ✅ ｜ verify_milestone_1.sh ✅（27 结果/单测过/loop 4 消息）｜ verify_milestone_2.sh ✅

## [2026-06-29] M3.1 驾驭层架构决策 + M3.2 可观测

### M3.1 架构(D9): 三层分工, 不 fork Cline
- 调研 task wuw3zewas: Cline 有 Claude-Code 式 hooks 系统(v3.36)。6 件套落点: A=Cline 原生(Auto Compact 压缩)+hooks; C=LangGraph(强制验证/循环检测/子Agent supervisor/硬审批 interrupt/checkpoint 归档)。B(fork) 全不需要。

### M3.2 可观测 — 实测纠偏(§6)
- 🔬 **实测发现(ISSUE-4)**: cline CLI v3.0.33 的 `--hooks-dir` **不执行**外部文件 hook(PreToolUse/PostToolUse, 试过 `.sh` 与无扩展名两种命名, 审计日志两处均空), 尽管其 `--json` 流内部 emit `hook_event`。
- ✅ 改走 **`--json` 流解析**: `agent_event` 的 content_start/content_end(contentType=tool) 带 toolName/input/output/durationMs, 信息完整; C 侧(LangGraph)驱动 cline headless 时本就读此流。
- 实现 `src/driving/observe.py`: `parse_events`(纯函数, 单测覆盖) + `run_and_observe`(驱动 cline + 落结构化审计 JSONL)。删掉不工作的文件 hook(死代码)。
- 验收 `verify_milestone_3.sh` ✅: observe 单测过; 真实 cline 运行被可观测(捕获 editor/run_commands, summary={tool_calls:2, iterations:3, reason:completed}, 审计落盘)。

## [2026-06-30] M3.3 强制验证节点 + sidecar 骨架（Phase 1）

### 实现
- `src/driving/sidecar.py`：LangGraph 状态机 execute→verify→(条件)。**强制验证**=完成后由 sidecar(非 agent)跑验收命令判定 done；不过→把失败详情回灌进任务重做；触顶 max_iterations→**熔断**(§6)。SqliteSaver checkpointer（崩溃恢复地基）。executor/verifier 可注入以便单测。
- 给 `drive()` 加 `data_dir` 透传（用 M2 隔离的 .cline-data 鉴权）。

### M3.3a 确定性单测 ✅（tests/test_sidecar.py，注入 stub 无需 LLM）
- happy path（一次过）/ 回灌重试（前两次失败→第三次过，且失败详情回灌进任务）/ 熔断（永远失败→触顶 max_iterations 停）。

### M3.3b e2e ✅（sidecar 驱动真实 cline=Kimi via :4000）
- 隔离 fixture（`add` 返回 a-b，测试失败）→ drive() 驱动 cline：editor/read_files/run_commands(3 调用,4 迭代,completed)→ **sidecar 强制跑 `python3 test_math.py`** → verified=True, iteration=1 → 终态测试 OK。
- 文件 SqliteSaver（db_path 给文件）→ 崩溃恢复地基成立。

### M3 一键验收 verify_milestone_3.sh ✅ 退出码 0
- M3.2a observe 单测 ✅ ｜ M3.2b 真实 cline 可观测 ✅ ｜ M3.3a sidecar 单测 ✅ ｜ M3.3b 强制验证 e2e ✅

## [2026-06-30] M3.4 循环检测（sidecar 跨步状态机）
- `sidecar.py` 加 `action_signature`（从工具轨迹算"工具+目标文件/命令"的有序签名）+ verify 节点循环检测：同一签名重复 ≥ `loop_threshold`(默认 3) → `stuck`/`stop_reason=loop_detected` → 中断（早于熔断）；重复 ≥2 即在回灌里**升级"换思路重规划"提示**。
- `test_sidecar.py` 加：签名相等性 / 循环检测（同签名重复 3 次即停，stop_reason=loop_detected，第 3 次任务含重规划提示）/ 熔断改用不同签名以区分（stop_reason=circuit_breaker）。全过。
- `verify_milestone_3.sh` 回归 ✅ 退出码 0（M3.2 可观测 + M3.3 强制验证 + M3.4 循环检测单测 + e2e）。

## [2026-06-30] M3.5 人工审批硬断点（LangGraph interrupt）+ D15 多Agent监督原则
- `src/driving/approval.py`：`classify_risk`(纯函数；高风险模式 push/merge/rm-rf/sudo/deploy/kubectl/凭据/装扩展/devcontainer rebuild/nix profile...) + `build_approval_graph`(classify→gate；高风险 `interrupt()` 硬暂停)。不靠 agent 自觉(Cline auto-approve 模型自分类不可靠)→**状态机强制**(§7 沙箱外要审批 / D13)。
- `test_approval.py`：风险分类 / 高风险 interrupt 暂停后 approve→放行 / reject→否决 / 低风险 auto 放行。全过。verify_milestone_3.sh 加 M3.5a。
- **D15(用户新要求)**：恒用最新最强技术；每任务多 Agent 协作 + 专属 overseer 监督效率/方向。驾驭层升级为 Supervisor(GLM)+Worker(Kimi)+Overseer(GLM)。调研(wr5pwf6m1): langgraph-supervisor 0.0.31 默认传全量历史污染上下文→官方推荐自定义 handoff 只传结构化任务；overseer=critic 节点产出结构化 verdict + 分层升级(确定性预检→GLM 语义→人类)。

## [2026-06-30] M3.6 多Agent监督编排（D15 核心）+ 结构化输出修复(D16)
- `src/driving/orchestrator.py`：手搓 LangGraph 图 **Supervisor(GLM 调度，干净结构化子任务)→Worker(Kimi via cline)→Overseer(GLM 监督：确定性预检+GLM 方向判断 verdict)→条件路由(continue/replan/abort)→强制验证**；checkpointer。节点可注入。
- `test_orchestrator.py`：7 场景确定性单测(调度/believe_done 跳过/中止/重规划/验证重试/熔断/循环)全过；verify_milestone_3.sh 加 M3.6a。
- §6 修复(D16)：`with_structured_output` 默认 `json_schema` 对 GLM ✗(返回 markdown)→ 改 `method="function_calling"` ✓。
- **真实 e2e ✅**：GLM 把目标拆成具体子任务 → Kimi 经 cline 修复(4 工具调用 completed)→ **GLM overseer 真实裁决 eff=0.95 dir=1.0** "完整闭环无绕路" → 强制验证过。**GLM 真在监督，非 fail-open**。

## [2026-06-30] M3.7 上下文压缩（Cline 原生 Auto Compact）→ 驾驭层六件套全齐
- `run_and_observe` 加 `compaction` 参数，默认 `--compaction agentic`（Cline 原生 Auto Compact，D9/D11 零自研代码）。实测 cline 接受且正常(exit 0)。
- **M3 驾驭层六件套全部 ✅**：可观测 / 强制验证 / 循环检测 / 人工审批 / 多Agent监督编排(D15) / 上下文压缩。全建立在 SqliteSaver(崩溃恢复)。

## [2026-06-30] orchestrator 接入审批硬断点（governed 多Agent loop 闭环）
- orchestrator 加 `approval_gate` 节点(supervisor→approval_gate→worker)：`require_approval=True` 时高风险子任务(classify_risk)在派给 worker 前 `interrupt()` 等放行；否决→回 supervisor 重规划。复用 M3.5 approval。
- test_orchestrator.py +2 场景：高风险→interrupt→放行执行 / 否决→换安全方案。全 9 场景过。
- §7 治理环闭合：多Agent编排里高风险动作强制人工审批（不靠 agent 自觉）。

## [2026-06-30] IDE 控制面扩展骨架（D13，TS VS Code 扩展，Phase 1→2 衔接）
- `ide-extension/`：package.json + tsconfig + src/{risk.ts, extension.ts, risk.test.ts}。
- extension.ts 注册 IDE 控制面工具(D13 三控制面)：typed API(`ide.runTask`/`openTerminal`/`get|updateSetting`) + executeCommand(`ide.installExtension`/`runCommand`)。高风险动作经 `risk.classifyRisk` → 模态人工确认(§7)。
- 验证：npm install(npmmirror) ✓；`tsc --noEmit` typecheck ✓(extension.ts vs @types/vscode)；compile ✓；risk.test ✅(镜像 Python classify_risk)。
- 后续：CLI 工具(devcontainer/nix 环境管理) + agent↔扩展桥(MCP/HTTP) + 运行时(extension host)验证。

## [2026-06-30] IDE 控制面 + 环境即代码工具（D12/D13）
- `ide-extension/src/env.ts`：`addDevcontainerFeature`(加语言 Feature)/`setMiseTool`(钉版本)/`devcontainerRebuildCmd`/`miseInstallCmd`，纯函数不可变。
- extension.ts 加环境工具：`env.addDevcontainerFeature`/`env.miseUse`(改声明文件) + `env.rebuildDevcontainer`(CLI，高风险审批)。**AI 管环境 = 改 devcontainer.json/.mise.toml + rebuild(D12)**。
- 验证：typecheck ✓(含 child_process/util vs @types/node)；compile ✓；risk.test + env.test ✅(env: feature 增/不可变, mise 建段/替换/追加/保留其它段, 命令构建)。

## [2026-06-30] Phase 2 环境模板（D12）— 随项目内置多语言环境
- `infra/env-templates/{devcontainer.json, .mise.toml}`：Dev Containers Features(python3.12/node20/rust/java21/mise) 层叠 + postCreate 跑 `mise install`；.mise.toml 钉 4 语言版本(容器内/本地共用)。
- `scripts/verify_phase2.sh` ✅：devcontainer 多语言 Features 完整 + mise install postCreate；.mise.toml 钉定完整。
- AI 经 IDE 控制面 `env.addDevcontainerFeature`/`env.miseUse`(已测) 改这些声明 + rebuild 管环境(D12 闭环)。

## [2026-06-30] Capstone e2e 暴露 ISSUE-1 重现 + §6 worker_error 快速失败
- Capstone(多文件任务)失败**根因 = exo 集群 GLM/Kimi 实例又下线**（litellm "No instance found... No deployments available"；直连 coder :4000 → 429）。**非编排器 bug**——编排器正确地熔断停住(未假成功/未无限空转)。需用户在 exo Web UI 重新 LAUNCH 两模型(ISSUE-1 重现，与会话重启时同类)。
- §6 工程化：orchestrator 加 **worker_error 快速失败**——执行器退出非0且0工具调用(常为上游不可用)→ `stop_reason=worker_error` 立即停，不耗尽 N 轮才笼统 circuit_breaker。test_orchestrator +1 场景(共10)，全过。
- README.md 升级为完整系统文档(架构/已建/如何运行/诚实边界)。

## [2026-06-30] IDE 控制面 agent↔扩展桥（D13）— Python 驾驭层 ↔ IDE
- `ide-extension/src/bridge.ts`：`parseToolRequest`/`dispatchTool`(纯逻辑)；extension.ts 起本地 HTTP(**仅 127.0.0.1:39217**) `POST /tool` → 分派到 IDE 工具。
- `src/driving/ide_client.py`：`build_tool_request`/`parse_tool_response`(纯) + `call_ide_tool`(走桥)。
- 验证：TS typecheck+compile ✓；bridge.test + Python test_ide_client ✅(分派/解析两端逻辑)。运行时 roundtrip(扩展宿主在跑 + Python 调用)待开宿主验。

## [2026-06-30] Phase 3 外壳脚手架（D14）— 待签名状态
- `shell/product.overrides.json`：flipped 品牌字段(三平台) + **Open VSX** 市场(微软市场红线)。
- `shell/apply_branding.py`：deep_merge 把覆盖合并进 VSCodium product.json(纯函数可测)。
- `shell/BUILD.md`：fork→换皮→内建 Cline/扩展→三平台构建→签名公证 runbook，**[需你]** 标注 Apple/Windows 证书步骤。
- `scripts/verify_phase3_scaffold.sh` ✅：配置合法+Open VSX；合并逻辑实测(覆盖+保留+不可变)。
- 余(用户/网络门控)：VSCodium clone+build + 签名公证分发（需 Apple 开发者证书）。

## [2026-06-30] Kimi 恢复 + architect 切到 GLM-5.2-fp8
- 用户重新 LAUNCH：Kimi-K2.7-Code(coder ✅) + **GLM-5.2-fp8**(替换原 DQ4plus-q8)。
- `config.yaml` architect → `mlx-community/GLM-5.2-fp8`；代理重启，别名 architect/coder 就绪。
- verify_milestone_3 **live 回归 ✅**(observe/sidecar e2e 经真实 Kimi + 全单测)。
- GLM-5.2-fp8(全精度大模型)仍在加载；architect 暂未服务；capstone(需 GLM 监督)待其就绪。

## [2026-06-30] 🎉 Phase 1 capstone — GLM-5.2-fp8 监督 Kimi 多文件任务 ✅
- 多Agent监督编排在**多文件任务**上端到端通过(verified, iteration 1)：
  [GLM 调度] 拆解目标 → [Kimi 执行] 建 calc.py+main.py(12 工具调用 completed) →
  [GLM 监督] action=continue **dir=1.0 eff=0.6** "方向完全正确；但 12 次工具调用偏多(低效)" → [强制验证] OK。
- **GLM overseer 真做了效率+方向双维监督**(dir=1.0 确认方向、eff=0.6 主动指出工具调用偏多)——正是 D15 核心。
- 前置：用户 LAUNCH GLM-5.2-fp8(736GB,fp8)+Kimi(2+2 部署)；architect/coder 两别名 live。终态 calc.py/main.py 建成、test OK。
- **至此 Phase 1 脑在真实多文件复杂度上完全验证。**

## [2026-06-30] verify_0 动态模型 id(§6) — GLM-5.2-fp8 工具调用全通
- `verify_milestone_0.sh` 改为从 `config.yaml` 动态解析 architect/coder 真实 model id(避免用户换模型后脚本陈旧)。
- 重跑全绿：M0.4 **GLM-5.2-fp8** + Kimi 工具调用 ✅、M0.5 架构路由 ✅。新 GLM 命根子(工具调用解析)确认。

## [2026-07-01] Phase B · B1/B2 完成 + 依赖冲突解决 + Worker 迁移到 OpenHands SDK

### 环境：py3.12 venv 依赖冲突解决
- 原 `fastapi==0.138.1` 与 `openhands-ai==1.8.0` 锁定的 `litellm==1.84.1` 冲突（litellm 要求 fastapi==0.124.4）。
- 已降级并锁定：`fastapi==0.124.4`、`uvicorn[standard]==0.30.0`；补齐 `langgraph==1.2.6` / `langchain-openai==1.3.3` / `langgraph-checkpoint-sqlite==3.1.0` / `langchain-core==1.4.8`。
- `requirements.txt` 已同步；`python -m pytest tests/` ✅ **29 passed, 1 warning**。

### B1 · orchestration-api 骨架
- 验收脚本 `scripts/verify_b1.sh` ✅：创建会话 → 派发任务 → WebSocket 收集 24 个事件 → 会话状态 `done`。
- 修复运行方式：给 `uvicorn` 加 `PYTHONPATH=src`，避免 `ModuleNotFoundError('executor')`。

### B2 · Worker 迁移到 OpenHands SDK
- `src/executor/openhands_worker.py`：封装 `RemoteConversation` + `Agent` + `RemoteWorkspace`；直连 exo 模型 `openai/mlx-community/Kimi-K2.7-Code-4bit`；显式预注册 `file_editor/task_tracker/terminal` 工具（解决 `TerminalTool not registered`）。
- 事件翻译：`ActionEvent/ObservationEvent/MessageEvent` → flipped 统一 `Event` schema（`tool_call`, `file_change`, `terminal`, `tool_result`, `message`, `status`, `error`）。
- 验收脚本 `scripts/verify_b2.sh` ✅：真实任务 → WS 23 个事件 → 沙盒内 `b2_hello.py` + `b2_hello_test.py` 建成，`pytest -q` 1 passed。

### orchestrator 默认 Worker 切到 OpenHands
- `src/driving/orchestrator.py`：新增 `openhands_worker` 节点 + `NullEventBus`；保留 `cline_worker` 以便回退；`default_worker = openhands_worker`。
- `_openhands_signature`：把 OpenHands 动作事件转成 sidecar 循环检测可比的签名。
- `test_orchestrator.py` 回归 ✅（注入 stub，不依赖真 OpenHands）。

### SearXNG 上游抖动兼容
- 上游搜索引擎（Google/Brave/DuckDuckGo）返回空 `results`，但 Wikidata/Wikipedia `infoboxes` 仍有可信内容。
- `src/tools/web_search.py`：`_parse` 在 `results` 为空时 fallback 到 `infoboxes`，`test_web_search.py` ✅。

### 当前状态
- Phase B 进度：B1 ✅ / B2 ✅ / B3（Console 接真实 WS）待做 / B4（tool-calling 加固 + cost warning）待做 / B5（UI 去 AI 感）待做。
- LiteLLM proxy `:4000` 仍因本地 Postgres/prisma 初始化阻塞，Phase B 已让 Supervisor/Overseer 仍走原 `:4000`（后续若 proxy 起不来，再让 orchestrator 直连 exo）。
