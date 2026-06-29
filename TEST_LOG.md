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
