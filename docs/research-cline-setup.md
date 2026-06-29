# 调研：Cline 落地（M2 基座，D4）

> 日期 2026-06-29 ｜ docs.cline.bot + 仓库 + context7 ｜ 置信：高

## 安装

- 扩展 id：`saoudrizwan.claude-dev`（Cline，Apache-2.0）。装：`code --install-extension saoudrizwan.claude-dev`（本机已装 v4.0.2）。
- **CLI**（关键）：`npm i -g cline`（v3.0.33）。注意 npmmirror 不镜像平台二进制 `@cline/cli-darwin-arm64`，**必须从官方 registry 装**（`--registry https://registry.npmjs.org`）。
- Node SDK：`@cline/sdk`（M3 自定义工具/钩子可用）。

## 接本地 OpenAI 兼容端点（:4000 LiteLLM）

- Provider 必须选 **"OpenAI Compatible"**（不是 plain "OpenAI"，后者自定义 Base URL 字段被移除 #7128）。
- 字段：Base URL = `http://localhost:4000/v1`（带 /v1）；API Key = LiteLLM master_key；Model = 直接填别名 `architect`/`coder`（自由文本，**大小写敏感**，须与 LiteLLM model_name 完全一致）。
- **CLI 非交互配置**：`cline auth openai-compatible -k <key> -m coder -b http://localhost:4000/v1 --data-dir <dir>`。
- 工具调用是硬需求（M0.4 已证 exo 两模型 OK）。

## 按模式分模型（Plan→architect/GLM, Act→coder/Kimi）

- Cline 原生支持 "Use different models for Plan and Act"（planModeModelId/actModeModelId）。官方示例正是"强模型规划 + 快模型实现"。
- ⚠️ **GUI 已知坑**：同一 Base URL 只换 model id 时，两模式会联动成同一模型（#8126/#5660/#9796）。我们 architect/coder 共用 exo 同端点 → 命中条件。
- 规避：① CLI/headless 每次 `-m` 指定模型，无此问题（M2 走这条）；② GUI 上若联动，给两模式配成两个独立 provider 条目，或 LiteLLM 暴露两个独立 base URL 路径（/architect、/coder）。
- Cline 无具名 API Profile（Roo 有）；自定义指令走 `.clinerules/`（手动 toggle，不按模式自动切）。

## 自动化验收：CLI headless（M2 用，免 GUI/computer-use）

- Cline 现为 monorepo + "Cline Core"(gRPC) + CLI + SDK，**共用同一 agent core** → CLI headless 跑任务 = 编辑器内 agent loop 的忠实代理。
- 一次性 headless：`cline --json --auto-approve true -P openai-compatible -m coder --data-dir <dir> -c <repo> --timeout N "<task>"`。
- ⚠️ `--auto-approve` 会无人值守跑 shell 命令 → **务必在隔离 throwaway repo(git init) 内跑**（呼应 CLAUDE.md 红线）。本项目用 `scripts/verify_milestone_2.sh` 在 mktemp 隔离目录验收。

## fork+构建（留给 M3）

- M2 **不需要 fork**，install+配置即满足验收。
- M3 加驾驭层才 fork：构建用 **Bun**（非 npm/pnpm）+ Git LFS + 强制 protobuf 生成 + 两包构建，再 F5 起 Extension Development Host。步骤：`git clone` → `cd apps/vscode && bun run install:all` → `cd ../sdk && bun run build` → `bun run protos` → `bun run dev` → F5。构建偏重，预留时间。

## 坑清单
- 平台二进制走官方 registry（npmmirror 缺）。
- context window 默认 ~128K，手填 "Context Window Size" 历史上不一定生效（#2073/#1044），需实测。
- LiteLLM 若返回 `usage:null`，Cline 上下文表显示 0%（#9433，需 LiteLLM 透传 usage）。
- 长工具任务个别模型把 tool call 输出成纯文本 → mistake_limit_reached（#10551），报错会误导你换 Claude。

> 全量来源见会话记录 task ws3m2ej7r。
