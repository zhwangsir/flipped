// flipped IDE 控制面（D13）：把 IDE 子系统暴露成 AI agent 可调用的工具。
// 三控制面叠加：typed 扩展 API(任务/终端/设置) + executeCommand 内建命令(装扩展/任意命令) + (后续) CLI(devcontainer/nix)。
// 高风险动作经 risk.classifyRisk 判定 → 人工确认(§7 沙箱外要审批)，不靠 agent 自觉。
// M146 加固：桥鉴权(token) + 请求体上限 + EADDRINUSE 容错 + runTask 审批 + JSONC 容错解析 + 参数校验。
import { execFile } from "child_process";
import { randomBytes } from "crypto";
import * as fs from "fs";
import * as http from "http";
import * as os from "os";
import * as path from "path";
import { promisify } from "util";
import * as vscode from "vscode";
import { dispatchTool, parseToolRequest } from "./bridge";
import {
  addDevcontainerFeature,
  DevcontainerConfig,
  devcontainerRebuildCmd,
  parseJsonc,
  setMiseTool,
} from "./env";
import { classifyRisk } from "./risk";

const pexec = promisify(execFile);

type ToolHandler = (args: Record<string, unknown>) => Promise<unknown>;

/** 请求体上限 1MB：防本机失控/恶意进程打爆扩展宿主内存（M146）。 */
const MAX_BODY_BYTES = 1 * 1024 * 1024;

/** 桥鉴权 token 文件（0600，仅本机用户可读；Python 驾驭层从同路径读取）。 */
function tokenFilePath(port: number): string {
  return path.join(os.homedir(), ".flipped", `ide-bridge-${port}.token`);
}

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

/** 必填字符串参数校验：缺失即抛带参数名的错误（防 "undefined" 写进声明文件，M146）。 */
function requireStr(args: Record<string, unknown>, key: string): string {
  const v = args[key];
  if (typeof v !== "string" || !v) {
    throw new Error(`missing required arg: ${key}`);
  }
  return v;
}

const tools: Record<string, ToolHandler> = {
  // typed API：跑任务。tasks.json 可封装任意 shell 命令 → 与 openTerminal 同级审批（M146 P1）
  "ide.runTask": async ({ name }) => {
    const taskName = requireStr({ name }, "name");
    if (!(await gate(`runTask ${taskName}`))) {
      throw new Error("rejected by user");
    }
    const tasks = await vscode.tasks.fetchTasks();
    const t = tasks.find((x) => x.name === taskName);
    if (!t) {
      throw new Error(`task not found: ${taskName}`);
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
  // typed API：读/写设置。undefined(键不存在)显式转 null，保证响应恒带 result 字段（M146）
  "ide.getSetting": async ({ section }) => {
    const v = vscode.workspace.getConfiguration().get(String(section));
    return v === undefined ? null : v;
  },
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
  "env.addDevcontainerFeature": async (args) => {
    const feature = requireStr(args, "feature");
    const version = typeof args.version === "string" && args.version ? args.version : "latest";
    const ws = vscode.workspace.workspaceFolders?.[0]?.uri;
    if (!ws) {
      throw new Error("no workspace");
    }
    const file = vscode.Uri.joinPath(ws, ".devcontainer", "devcontainer.json");
    let cfg: DevcontainerConfig = {};
    let raw: string | null = null;
    try {
      raw = Buffer.from(await vscode.workspace.fs.readFile(file)).toString();
    } catch {
      /* 文件不存在 → 新建（仅此情形容忍） */
    }
    if (raw !== null) {
      // 文件存在：JSONC 容错解析；失败则拒绝覆盖，防静默数据丢失（M146 P1）
      cfg = parseJsonc(raw);
    }
    const next = addDevcontainerFeature(cfg, feature, version);
    await vscode.workspace.fs.writeFile(file, Buffer.from(JSON.stringify(next, null, 2)));
    return { ok: true, features: Object.keys(next.features ?? {}) };
  },
  // 编辑 .mise.toml 钉语言版本
  "env.miseUse": async (args) => {
    const tool = requireStr(args, "tool");
    const version = requireStr(args, "version");
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
    await vscode.workspace.fs.writeFile(file, Buffer.from(setMiseTool(toml, tool, version)));
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
    // timeout 10min + maxBuffer 16MB：防请求悬挂与 ENOBUFS（M146）
    const { stdout } = await pexec(cmd[0], cmd.slice(1), {
      timeout: 10 * 60 * 1000,
      maxBuffer: 16 * 1024 * 1024,
    });
    return { ok: true, stdout: stdout.slice(-500) };
  },
};

export function activate(context: vscode.ExtensionContext): void {
  // 1) 注册为 VS Code 命令(供命令面板/键位/其它扩展调用)
  for (const [name, handler] of Object.entries(tools)) {
    context.subscriptions.push(
      vscode.commands.registerCommand(name, (args?: Record<string, unknown>) => handler(args ?? {})),
    );
  }

  // 2) agent↔扩展桥：本地 HTTP(仅 127.0.0.1 + Bearer token) 让 Python 驾驭层调 IDE 工具
  const port = vscode.workspace.getConfiguration("flipped").get<number>("bridgePort", 39217);
  const token = randomBytes(24).toString("hex");
  const server = http.createServer((req, res) => {
    if (req.method !== "POST" || req.url !== "/tool") {
      res.writeHead(404);
      res.end();
      return;
    }
    // 鉴权：本机 token（防恶意网页经 simple request 驱动本地执行，M146 P1）
    if (req.headers.authorization !== `Bearer ${token}`) {
      res.writeHead(401, { "content-type": "application/json" });
      res.end(JSON.stringify({ ok: false, error: "unauthorized" }));
      return;
    }
    // 仅接受 JSON（text/plain 可绕 CORS preflight，拒绝之）
    const ct = String(req.headers["content-type"] || "");
    if (!ct.includes("application/json")) {
      res.writeHead(415, { "content-type": "application/json" });
      res.end(JSON.stringify({ ok: false, error: "content-type must be application/json" }));
      return;
    }
    let body = "";
    let size = 0;
    let tooBig = false;
    req.on("data", (c: Buffer) => {
      size += c.length;
      if (size > MAX_BODY_BYTES) {
        tooBig = true;
        res.writeHead(413, { "content-type": "application/json" });
        res.end(JSON.stringify({ ok: false, error: "payload too large" }));
        req.destroy();
        return;
      }
      body += String(c);
    });
    req.on("end", () => {
      if (tooBig) {
        return;
      }
      void (async () => {
        try {
          const { name, args } = parseToolRequest(body);
          const result = await dispatchTool(name, args, tools);
          res.writeHead(200, { "content-type": "application/json" });
          res.end(JSON.stringify({ ok: true, result }));
        } catch (e) {
          res.writeHead(400, { "content-type": "application/json" });
          res.end(JSON.stringify({ ok: false, error: String(e) }));
        }
      })();
    });
  });
  // 第二个 VS Code 窗口激活时 EADDRINUSE：警告并跳过，不让扩展宿主崩（M146）
  server.on("error", (e: NodeJS.ErrnoException) => {
    if (e.code === "EADDRINUSE") {
      console.warn(`flipped bridge: 127.0.0.1:${port} 已被占用（另一窗口？），本窗口不起桥`);
      return;
    }
    console.error("flipped bridge error:", e);
  });
  server.listen(port, "127.0.0.1", () => {
    console.log(`flipped bridge: 127.0.0.1:${port}`);
    // 仅在成功监听后落 token（EADDRINUSE 的窗口不覆盖），0600 仅本机用户可读
    try {
      const p = tokenFilePath(port);
      fs.mkdirSync(path.dirname(p), { recursive: true });
      fs.writeFileSync(p, token, { mode: 0o600 });
    } catch (e) {
      console.error("flipped bridge: token 落盘失败", e);
    }
  });
  context.subscriptions.push({ dispose: () => server.close() });

  console.log("flipped IDE 控制面已激活，工具：", Object.keys(tools).join(", "));
}

export function deactivate(): void {
  // no-op
}
