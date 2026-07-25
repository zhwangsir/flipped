// IDE 控制面 · 环境即代码管理（D12/D13）：AI 通过编辑声明文件 + 重建来管环境。
// 纯函数（声明编辑 / 命令构建）可单测；实际 fs 写入与 CLI 执行在 extension 侧。
export interface DevcontainerConfig {
  name?: string;
  image?: string;
  features?: Record<string, unknown>;
  [k: string]: unknown;
}

/** 往 devcontainer.json 加一个 Feature(语言运行时)；返回新对象(不可变，§编码风格)。 */
export function addDevcontainerFeature(
  cfg: DevcontainerConfig,
  feature: string,
  version = "latest",
): DevcontainerConfig {
  const id = feature.includes("/") ? feature : `ghcr.io/devcontainers/features/${feature}`;
  return { ...cfg, features: { ...(cfg.features ?? {}), [id]: { version } } };
}

/** 设定 .mise.toml 里某工具版本；返回新 toml 文本(行级编辑，保留其余内容)。 */
export function setMiseTool(toml: string, tool: string, version: string): string {
  const entry = `${tool} = "${version}"`;
  // 转义正则元字符：含 "."（错位匹配）或 "+"（直接 SyntaxError）的工具名不再崩（M146）
  const toolRe = tool.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const lines = (toml || "").replace(/\n$/, "").split("\n");
  const out: string[] = [];
  let inTools = false;
  let toolsHeaderIdx = -1;
  let replaced = false;
  for (const line of lines) {
    const t = line.trim();
    if (t.startsWith("[")) {
      inTools = t === "[tools]";
    }
    if (inTools && new RegExp(`^\\s*${toolRe}\\s*=`).test(line)) {
      out.push(entry);
      replaced = true;
      continue;
    }
    out.push(line);
    if (t === "[tools]") {
      toolsHeaderIdx = out.length;
    }
  }
  if (!replaced) {
    if (toolsHeaderIdx >= 0) {
      out.splice(toolsHeaderIdx, 0, entry);
    } else {
      if (out.length && out[out.length - 1].trim() !== "") {
        out.push("");
      }
      out.push("[tools]", entry);
    }
  }
  return out.filter((l, i) => !(l === "" && i === 0)).join("\n") + "\n";
}

/** devcontainer 重建命令(在 workspace 重建容器，使声明变更生效)。 */
export function devcontainerRebuildCmd(workspace: string): string[] {
  return ["devcontainer", "up", "--workspace-folder", workspace, "--remove-existing-container"];
}

/** mise 安装命令(按 .mise.toml 装/钉版本)。 */
export function miseInstallCmd(): string[] {
  return ["mise", "install", "--yes"];
}

/**
 * JSONC 容错解析（devcontainer.json 官方允许注释/尾逗号）。
 * 状态机剥注释（尊重字符串与转义，不误伤 "https://…"）→ 去尾逗号 → JSON.parse。
 * 解析仍失败则抛错——调用方必须拒绝覆盖原文件，防静默数据丢失（M146 P1）。
 */
export function parseJsonc(text: string): DevcontainerConfig {
  let out = "";
  let inStr = false;
  let esc = false;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    const n = text[i + 1];
    if (inStr) {
      out += c;
      if (esc) {
        esc = false;
      } else if (c === "\\") {
        esc = true;
      } else if (c === '"') {
        inStr = false;
      }
      continue;
    }
    if (c === '"') {
      inStr = true;
      out += c;
      continue;
    }
    if (c === "/" && n === "/") {
      while (i < text.length && text[i] !== "\n") i++;
      out += "\n";
      continue;
    }
    if (c === "/" && n === "*") {
      i += 2;
      while (i < text.length && !(text[i] === "*" && text[i + 1] === "/")) i++;
      i++;
      continue;
    }
    out += c;
  }
  const stripped = out.replace(/,(\s*[}\]])/g, "$1");
  return JSON.parse(stripped) as DevcontainerConfig;
}
