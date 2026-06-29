// 纯逻辑单测（编译后 node 直接跑，无需 vscode 宿主）。
import { classifyRisk } from "./risk";

function assert(cond: boolean, msg: string): void {
  if (!cond) {
    console.error("FAIL:", msg);
    process.exit(1);
  }
}

assert(classifyRisk("git push origin main") === "high", "git push 应 high");
assert(classifyRisk("rm -rf build") === "high", "rm -rf 应 high");
assert(classifyRisk("kubectl apply -f x.yaml") === "high", "kubectl 应 high");
assert(classifyRisk("workbench.extensions.installExtension foo") === "high", "installExtension 应 high");
assert(classifyRisk("ls -la") === "low", "ls 应 low");
assert(classifyRisk("npm run compile") === "low", "npm run 应 low");

console.log("risk.test ✅ 全部通过");
