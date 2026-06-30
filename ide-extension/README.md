# flipped IDE 控制面（VS Code 扩展）

让 AI agent 驱动 IDE 子系统（D13）：任务/终端/设置/扩展/任意命令 + 环境即代码（devcontainer/mise）。高风险动作走人工确认（§7）。Python 驾驭层经本地 HTTP 桥（仅 127.0.0.1:39217）调用这些工具。

## 工具
- `ide.runTask` / `ide.openTerminal` / `ide.getSetting` / `ide.updateSetting` — typed 扩展 API
- `ide.installExtension` / `ide.runCommand` — executeCommand 内建命令
- `env.addDevcontainerFeature` / `env.miseUse` / `env.rebuildDevcontainer` — 环境即代码

## 构建与运行
```bash
npm install            # 依赖(@types/vscode, typescript)
npm run typecheck      # 类型检查
npm run compile        # 编译到 out/
npm test               # 纯逻辑单测(risk/env/bridge)
# 在 VS Code 里按 F5 启动 Extension Development Host 试运行
```

## 桥客户端（Python 侧）
`src/driving/ide_client.py` 的 `call_ide_tool(name, args)` 经 `POST http://127.0.0.1:39217/tool` 调用。
