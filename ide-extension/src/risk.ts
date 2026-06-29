// IDE 控制面 · 风险分类（镜像 Python driving/approval.classify_risk；D13 / §7）。
// 高风险 = 逸出沙箱 / 不可逆 / 对外副作用 / 触碰凭据 → 须人工放行。
const HIGH_RISK: RegExp[] = [
  /\bgit\s+push\b/i,
  /\bgit\b.*\bmerge\b/i,
  /\brm\s+-rf\b/i,
  /\bsudo\b/i,
  /\bnpm\s+publish\b/i,
  /\bdeploy\b/i,
  /\bkubectl\b/i,
  /\bterraform\s+(apply|destroy)\b/i,
  /secret|token|password|credential/i,
  /devcontainer.*rebuild/i,
  /\bnix\s+profile\b/i,
  /installExtension/i,
  /settings.*update.*user/i,
  /\bshutdown\b|\breboot\b/i,
];

export function classifyRisk(action: string): "high" | "low" {
  const a = action || "";
  return HIGH_RISK.some((re) => re.test(a)) ? "high" : "low";
}
