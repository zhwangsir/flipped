// agent↔扩展桥 · 纯逻辑单测。
import { dispatchTool, parseToolRequest, ToolMap } from "./bridge";

function assert(cond: boolean, msg: string): void {
  if (!cond) {
    console.error("FAIL:", msg);
    process.exit(1);
  }
}

// parseToolRequest
const r = parseToolRequest('{"name":"ide.runTask","args":{"name":"build"}}');
assert(r.name === "ide.runTask" && (r.args as any).name === "build", "应解析 name+args");
const r2 = parseToolRequest('{"name":"x"}');
assert(r2.name === "x" && JSON.stringify(r2.args) === "{}", "缺 args 应为空对象");
let threw = false;
try {
  parseToolRequest('{"args":{}}');
} catch {
  threw = true;
}
assert(threw, "缺 name 应抛错");

// dispatchTool
const tools: ToolMap = {
  echo: async (a) => ({ got: a }),
};
(async () => {
  const out = (await dispatchTool("echo", { v: 1 }, tools)) as any;
  assert(out.got.v === 1, "应分派到 echo 并回结果");
  let unknownThrew = false;
  try {
    await dispatchTool("nope", {}, tools);
  } catch {
    unknownThrew = true;
  }
  assert(unknownThrew, "未知工具应抛错");
  console.log("bridge.test ✅ 全部通过");
})();
