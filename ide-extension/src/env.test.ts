// 环境即代码管理 · 纯逻辑单测（编译后 node 直接跑）。
import {
  addDevcontainerFeature,
  devcontainerRebuildCmd,
  miseInstallCmd,
  setMiseTool,
} from "./env";

function assert(cond: boolean, msg: string): void {
  if (!cond) {
    console.error("FAIL:", msg);
    process.exit(1);
  }
}

// addDevcontainerFeature
const base = { name: "dev", features: { "ghcr.io/devcontainers/features/node": { version: "20" } } };
const withPy = addDevcontainerFeature(base, "python", "3.12");
assert(
  (withPy.features as any)["ghcr.io/devcontainers/features/python"]?.version === "3.12",
  "应加上 python feature",
);
assert((withPy.features as any)["ghcr.io/devcontainers/features/node"]?.version === "20", "应保留 node");
assert((base.features as any)["ghcr.io/devcontainers/features/python"] === undefined, "原对象不可变");
assert(
  addDevcontainerFeature({}, "ghcr.io/x/rust", "1").features !== undefined,
  "含 / 的 feature 直接用",
);

// setMiseTool
const t1 = setMiseTool("", "python", "3.12");
assert(t1.includes("[tools]") && t1.includes('python = "3.12"'), "空 toml 应建 [tools] + 条目");
const t2 = setMiseTool('[tools]\npython = "3.10"\n', "python", "3.12");
assert(t2.includes('python = "3.12"') && !t2.includes('3.10'), "应替换已有版本");
const t3 = setMiseTool('[tools]\nnode = "20"\n', "rust", "1.80");
assert(t3.includes('node = "20"') && t3.includes('rust = "1.80"'), "应在已有 [tools] 追加");
const t4 = setMiseTool('[env]\nFOO = "bar"\n', "python", "3.12");
assert(t4.includes('FOO = "bar"') && t4.includes("[tools]") && t4.includes('python = "3.12"'), "保留其它段并加 [tools]");

// 命令构建
assert(JSON.stringify(devcontainerRebuildCmd("/ws")) ===
  JSON.stringify(["devcontainer", "up", "--workspace-folder", "/ws", "--remove-existing-container"]),
  "devcontainer 重建命令");
assert(JSON.stringify(miseInstallCmd()) === JSON.stringify(["mise", "install", "--yes"]), "mise 安装命令");

console.log("env.test ✅ 全部通过");
