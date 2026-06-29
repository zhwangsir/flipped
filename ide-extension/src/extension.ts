// flipped IDE 控制面（D13）：把 IDE 子系统暴露成 AI agent 可调用的工具。
// 三控制面叠加：typed 扩展 API(任务/终端/设置) + executeCommand 内建命令(装扩展/任意命令) + (后续) CLI(devcontainer/nix)。
// 高风险动作经 risk.classifyRisk 判定 → 人工确认(§7 沙箱外要审批)，不靠 agent 自觉。
import * as vscode from "vscode";
import { classifyRisk } from "./risk";

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
