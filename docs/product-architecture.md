# flipped 产品架构 —— AI 驱动的多平台桌面 IDE

> 定稿 2026-06-29 ｜ 依据 5 路调研(task wbnb5vubp) + M0–M3 实测 ｜ 决策 D10–D14
> 目标：类似 VSCode/IDEA/HBuilder 的**多平台桌面 IDE**，**随项目内置多语言环境**(Python/Java/Rust…)，**整个 IDE 由 AI 底层驱动管理**。用户=自己/少数人。

## 一句话方案

**把三个成熟范式拼起来**：`Code-OSS fork(Cursor/Windsurf 模式) 做多平台外壳` + `Dev Containers + mise(IDX/devcontainer 模式) 做随项目内置环境` + `Cline 派生 agent + IDE 控制面 + LangGraph sidecar(Replit/Cursor-Anyrun 模式) 做 AI 底层驱动`。每块都有现成实现可借，**不从零造**。

## 目标架构（分层）

```
┌─ 外壳 Shell ── Code-OSS fork (VSCodium 脚手架) → 品牌化 product.json ──────────┐
│  Electron 三平台(mac 签名公证 / Win Authenticode / Linux) · 市场=Open VSX        │
│                                                                                │
│  ┌─ 脑 Brain：内建 AI 扩展 (Cline 派生, Apache-2.0 bundled builtin) ──────────┐  │
│  │  • Cline 原生工具(文件/终端/编辑/搜索) + hooks(PreToolUse 守门/PostToolUse 采集)│ │
│  │  • IDE 控制面工具(新增)：typed API(任务/调试/设置/终端) + executeCommand     │  │
│  │    (装扩展/重载) + CLI(devcontainer/nix) → 让 AI 管 终端/调试/扩展/环境       │  │
│  └──────────────────────────────────────────────────────────────────────────┘  │
│         │ 本地 stdio/HTTP (LSP 风格)                                            │
│  ┌─ 驾驭 Driving：LangGraph sidecar (Python, IDE 随启, 复用 M1/M3) ───────────┐  │
│  │  强制验证 · 循环检测 · 子Agent主从(GLM 调度/Kimi 执行) · 硬审批 interrupt ·   │  │
│  │  checkpoint 归档(崩溃恢复)。打包: python-build-standalone + uv (extraResources)│ │
│  └──────────────────────────────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────────────────────────────┘
        │ OpenAI 兼容 base_url（用户可填，默认 localhost:4000）        [M0 复用]
   LiteLLM(:4000) → exo 集群 → GLM-5.2(architect) / Kimi-K2.7-Code(coder)

┌─ 随项目内置环境 Environment-as-code ───────────────────────────────────────────┐
│  主干: Dev Containers — .devcontainer/devcontainer.json + Features(py/java/rust/…)│
│  版本钉定: mise — .mise.toml(容器内/本地共用)                                     │
│  进阶: Nix flake(可复现性最强, power 选项)  ｜ 兜底: 运行时打进安装器(离线)         │
│  AI 管理方式: 改 devcontainer.json/.mise.toml 这两个声明文件 + 触发 Rebuild 自愈   │
└────────────────────────────────────────────────────────────────────────────────┘
        │ 内建工具/MCP: web_search(SearXNG)                          [M1 复用]
```

## 各层选型与理由

### 1. 外壳 = Code-OSS fork（D14）
- 用 **VSCodium 构建仓库**为脚手架（不从零搭），`product.json` 换品牌；三平台打包 + 签名公证。
- **法律硬线**：① 不能用微软官方扩展市场 → **Open VSX**；② 微软闭源 builtin(C++/Pylance/Remote/C#)在 fork 中已被技术性禁用，不可分发。
- **Cline(Apache-2.0)** 可作 bundled builtin 随 IDE 发，须保留 LICENSE/NOTICE 署名。
- 佐证：Cursor / Windsurf / 字节 Trae **都是 Code-OSS fork + Open VSX**。
- 代价：跟随上游**月度 rebase**；macOS 公证 / Windows 签名 / Open VSX 供应链审计。

### 2. 随项目内置环境 = Dev Containers + mise（D12）
- **Dev Containers** 为主干：`devcontainer.json` 一文件声明环境，多语言用 **Features**(`ghcr.io/devcontainers/features` 的 python/java/rust)层叠；隔离 + 跨平台一致 + AI 可改可重建自愈（"AI 搞坏也能删容器重来"是社区主流模板）。
- **mise**(`.mise.toml`)在容器内/本地共用，做语言版本钉定，比 asdf 快 20–200x，跨平台含原生 Windows。
- **Nix flake** 作 power 选项（可复现性最强，但 Windows 弱、学习曲线陡，不做默认）。
- 提供 **mise-only 降级**（不想装 Docker/想原生 Windows 的少数人）。
- Windows 前置：WSL2 + Docker Desktop，源码放 WSL 文件系统(非 /mnt/c)避免 IO 塌方。

### 3. AI 底层驱动 = 控制面工具，不为控制而 fork（D13）
- AI 不靠 fork 就能驱动 IDE 大部分子系统，三个控制面叠加：
  - **Cline 现有工具**（文件/终端）
  - **typed 扩展 API**（tasks/debug/settings/terminals 读写）
  - **executeCommand 内建命令**（装/卸扩展、重载窗口——typed API 禁止但命令可达）
  - **CLI**（devcontainer/nix）做环境管理：装语言/切版本=**改声明文件 + rebuild**，不在终端裸装。
- 实现：一个薄的 **"IDE 控制面"扩展**注册这些为 MCP/Cline 工具。
- fork 仅用于：外壳品牌化 + 少数必须在 stable 用的 proposed API 白名单。
- **安全**：高风险动作(rebuild/nix 改动/装扩展/User 级设置写/任意终端命令)走**人工审批**；只读自省自动放行。

### 4. 驾驭层落点 = Cline 原生/hooks + LangGraph sidecar（D11）
- **不在脑验证前把 LangGraph 用 TS 重写进 fork**（高成本零增量）。
- 混合落点(承接 D9)：压缩→Cline Auto Compact；采集→PostToolUse(observe.py re-home)；守门→PreToolUse；日常审批→Plan/Act；**强制验证/循环检测/子Agent主从/硬审批/checkpoint 归档→LangGraph sidecar**。
- 佐证：Cursor=UI + 独立 Rust 编排服务(Anyrun)；Windsurf=独立本地 Rust agent(Devin Local)。**重 agent 逻辑放独立进程，不塞编辑器扩展沙箱**。
- 打包：`python-build-standalone` + `uv` 经 `electron-builder extraResources` 随包；主进程 spawn + 健康探活 + 退出 kill；macOS 对每个嵌入二进制逐个签名 + 公证。
- 模型端点外置为用户可填（默认 :4000），桌面产品不硬编码内网集群。

## M0–M3 成果如何并入（不浪费）

| 已完成 | 在新架构中的角色 |
|---|---|
| M0 LiteLLM/exo | 模型后端；端点外置成用户配置 |
| M1 web_search + LangGraph loop | 内建工具/MCP + **驾驭 sidecar 的基础** |
| M2 Cline 接入 | → **内建 builtin AI 扩展**（脑） |
| M3.1 D9 分层 | 直接成立，细化为 D11 |
| M3.2 observe.py(cline --json) | → sidecar 的可观测 + "工具事件→可见+checkpoint" |

## 重排路线图（脑 → 环境 → 壳）

> 原则：**脑先于壳**。Phase 1 在**普通 VS Code** 里就交付完整 AI-IDE 体验（免 fork/签名重活），快速见效；最贵的"做成品牌 App"放最后。

- **Phase 1 · 脑**（= 续 M3 + M4 控制面）：在 stock VS Code 里把 Cline 派生 agent + IDE 控制面工具 + LangGraph sidecar + 驾驭层(强制验证/循环/子Agent/审批) 做扎实、可验收。
- **Phase 2 · 环境**（= M4 一部分）：environment-as-code 声明(devcontainer+mise) + AI 管环境(改声明+rebuild) + 快照加速。
- **Phase 3 · 壳**（= M5 产线化）：fork Code-OSS(VSCodium 脚手架) → 品牌化 → Cline 内建 builtin → Open VSX → 三平台打包/签名/公证 → 出安装器。

## 现成可借参照（按"研究与重用"）
- **Google Project IDX / Firebase Studio**：Code-OSS + **Nix 内置环境** + AI（环境内置范本）
- **Replit + Agent**：AI **工具化管理整套环境** + verifier + auto-commit（AI 控制面 + 安全范本）
- **Cursor / Windsurf / 字节 Trae**：Code-OSS fork + 独立 agent 进程（外壳 + sidecar 范本）
- **DevPod(loft-sh, Go, 开源)**：client-only + provider 管 devcontainer（若重新评估"轻于 fork"的路线可借）
