// flipped IDE 控制面（D13）：把 IDE 子系统暴露成 AI agent 可调用的工具。
// 三控制面叠加：typed 扩展 API(任务/终端/设置) + executeCommand 内建命令(装扩展/任意命令) + (后续) CLI(devcontainer/nix)。
// 高风险动作经 risk.classifyRisk 判定 → 人工确认(§7 沙箱外要审批)，不靠 agent 自觉。
import { execFile } from "child_process";
import { promisify } from "util";
import * as vscode from "vscode";
import {
  addDevcontainerFeature,
  DevcontainerConfig,
  devcontainerRebuildCmd,
  setMiseTool,
} from "./env";
import { classifyRisk } from "./risk";

const pexec = promisify(execFile);

type ToolHandler = (args: Record<string, unknown>) => Promise<unknown>;

/** 高风险动作弹模态确认；低风险直通。返回是否放行。 */
async function gate(action: string): Promise<boolean> {
  if (classifyRisk(action) === "low") {
    return true;
  }
  const pick = await vscode.window.showWarningMessage(
    `高风险动作需放行（§7）：${action}`,
    { modal: true },
    "放行",
    "否决",
  );
  return pick === "放行";
}

const tools: Record<string, ToolHandler> = {
  // typed API：跑任务
  "ide.runTask": async ({ name }) => {
    const tasks = await vscode.tasks.fetchTasks();
    const t = tasks.find((x) => x.name === name);
    if (!t) {
      throw new Error(`task not found: ${String(name)}`);
    }
    return vscode.tasks.executeTask(t);
  },
  // typed API：开终端并(可选)发命令
  "ide.openTerminal": async ({ name, command }) => {
    const term = vscode.window.createTerminal(typeof name === "string" ? name : "agent");
    term.show();
    if (typeof command === "string" && command) {
      if (!(await gate(command))) {
        throw new Error("rejected by user");
      }
      term.sendText(command);
    }
    return { ok: true };
  },
  // typed API：读/写设置
  "ide.getSetting": async ({ section }) =>
    vscode.workspace.getConfiguration().get(String(section)),
  "ide.updateSetting": async ({ section, value }) => {
    if (!(await gate(`settings update ${String(section)}`))) {
      throw new Error("rejected by user");
    }
    await vscode.workspace
      .getConfiguration()
      .update(String(section), value, vscode.ConfigurationTarget.Workspace);
    return { ok: true };
  },
  // executeCommand：装扩展(typed API 禁止，命令可达)
  "ide.installExtension": async ({ id }) => {
    if (!(await gate(`installExtension ${String(id)}`))) {
      throw new Error("rejected by user");
    }
    return vscode.commands.executeCommand("workbench.extensions.installExtension", id);
  },
  // executeCommand：任意内建命令(广义控制面，高风险须审批)
  "ide.runCommand": async ({ commandId, args }) => {
    if (!(await gate(`runCommand ${String(commandId)}`))) {
      throw new Error("rejected by user");
    }
    const rest = Array.isArray(args) ? args : [];
    return vscode.commands.executeCommand(String(commandId), ...rest);
  },
  // 环境即代码(D12/D13)：AI 改声明文件 → 重建。编辑 devcontainer.json 加语言 Feature
  "env.addDevcontainerFeature": async ({ feature, version }) => {
    const ws = vscode.workspace.workspaceFolders?.[0]?.uri;
    if (!ws) {
      throw new Error("no workspace");
    }
    const file = vscode.Uri.joinPath(ws, ".devcontainer", "devcontainer.json");
    let cfg: DevcontainerConfig = {};
    try {
      cfg = JSON.parse(Buffer.from(await vscode.workspace.fs.readFile(file)).toString());
    } catch {
      /* 无则新建 */
    }
    const next = addDevcontainerFeature(cfg, String(feature), version ? String(version) : "latest");
    await vscode.workspace.fs.writeFile(file, Buffer.from(JSON.stringify(next, null, 2)));
    return { ok: true, features: Object.keys(next.features ?? {}) };
  },
  // 编辑 .mise.toml 钉语言版本
  "env.miseUse": async ({ tool, version }) => {
    const ws = vscode.workspace.workspaceFolders?.[0]?.uri;
    if (!ws) {
      throw new Error("no workspace");
    }
    const file = vscode.Uri.joinPath(ws, ".mise.toml");
    let toml = "";
    try {
      toml = Buffer.from(await vscode.workspace.fs.readFile(file)).toString();
    } catch {
      /* 无则新建 */
    }
    await vscode.workspace.fs.writeFile(file, Buffer.from(setMiseTool(toml, String(tool), String(version))));
    return { ok: true };
  },
  // 重建 devcontainer 使声明生效(高风险 → 审批)
  "env.rebuildDevcontainer": async () => {
    const ws = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;
    if (!ws) {
      throw new Error("no workspace");
    }
    if (!(await gate("devcontainer rebuild"))) {
      throw new Error("rejected by user");
    }
    const cmd = devcontainerRebuildCmd(ws);
    const { stdout } = await pexec(cmd[0], cmd.slice(1));
    return { ok: true, stdout: stdout.slice(-500) };
  },
};

export function activate(context: vscode.ExtensionContext): void {
  for (const [name, handler] of Object.entries(tools)) {
    context.subscriptions.push(
      vscode.commands.registerCommand(name, (args?: Record<string, unknown>) => handler(args ?? {})),
    );
  }
  console.log("flipped IDE 控制面已激活，工具：", Object.keys(tools).join(", "));
}

export function deactivate(): void {
  // no-op
}
