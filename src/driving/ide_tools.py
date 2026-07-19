"""M141 · IDE 控制面工具面接入驾驭层：注册表 + 动作渲染 + 五级管线裁决 + 审计。

现状缺口（M3 遗留首项）：ide-extension 的 TS 桥（127.0.0.1:39217 POST /tool，9 工具）
与 Python `ide_client` 均已建好，但编排层拿不到——工具未纳入 M136-E 五级权限管线、
调用无 factory_events 审计。本模块补上中间这层：

- `IDE_TOOL_REGISTRY`：与 extension.ts tools 表对齐的注册表（漂移守门靠测试硬编码对照）。
- `render_ide_action`：把一次工具调用渲染成可评估动作串。**安全关键**：openTerminal 带
  command 时渲染为命令本体，让管线直接评估真实命令（`rm -rf /` 在 L2 即 deny）。
- `governed_ide_call`：render → evaluate_command（IDE_RULES+DEFAULT_RULES 合并，链式拆分
  语义：任一分段 deny 则整体 deny）→ 仅 allow 才执行；deny/ask 留痕不执行。
  执行异常捕获进 `error` 不上抛（桥不可用时调用方自行降级）。

审计：给定 audit_conn+factory_id 时写 `ide_tool_call` 事件（append_event 天然 fail-open），
allow/deny/ask 全留痕——谁拦的、为什么拦、执行报错，都可在 TUI/事件流里追溯。
"""
from __future__ import annotations

from dataclasses import dataclass

from driving.approval import DEFAULT_RULES, PermissionVerdict, evaluate_command
from driving.event_log import append_event
from driving.ide_client import call_ide_tool

# 与 ide-extension/src/extension.ts 的 tools 表对齐；tests/test_ide_tools.py 做漂移守门
IDE_TOOL_REGISTRY: dict[str, dict] = {
    "ide.runTask": {"description": "运行 VS Code 任务（typed tasks API）", "required": ["name"]},
    "ide.openTerminal": {"description": "开终端，可附带发送命令（命令经管线评估）", "required": []},
    "ide.getSetting": {"description": "读工作区设置（只读）", "required": ["section"]},
    "ide.updateSetting": {"description": "写工作区设置", "required": ["section", "value"]},
    "ide.installExtension": {"description": "安装扩展（executeCommand，高风险）", "required": ["id"]},
    "ide.runCommand": {"description": "执行任意内建命令（广义控制面，高风险）", "required": ["commandId"]},
    "env.addDevcontainerFeature": {"description": "编辑 devcontainer.json 加语言 Feature（D12）", "required": ["feature"]},
    "env.miseUse": {"description": "编辑 .mise.toml 钉语言版本（D12）", "required": ["tool", "version"]},
    "env.rebuildDevcontainer": {"description": "重建 devcontainer 使声明生效（高风险）", "required": []},
}

# IDE 专属规则叠加层：与 DEFAULT_RULES 合并（deny>ask>allow 优先级语义不变）。
# 只读/沙箱内声明文件编辑 = allow；广义写动作 = ask；危险命令本体靠 DEFAULT_RULES deny。
IDE_RULES: list[dict] = [
    {"decision": "allow", "pattern": "ide getSetting*"},
    {"decision": "allow", "pattern": "ide runTask*"},
    {"decision": "allow", "pattern": "ide openTerminal"},
    {"decision": "allow", "pattern": "env addDevcontainerFeature*"},
    {"decision": "allow", "pattern": "env miseUse*"},
    {"decision": "ask", "pattern": "ide updateSetting*"},
    {"decision": "ask", "pattern": "ide runCommand*"},
    {"decision": "ask", "pattern": "installExtension*"},
]

_COMBINED_RULES = IDE_RULES + DEFAULT_RULES


def render_ide_action(name: str, args: dict | None = None) -> str:
    """把一次 IDE 工具调用渲染成可评估动作串。未知工具名抛 KeyError（注册表守门）。

    安全关键：openTerminal 带 command 时返回命令本体——管线直接评估真实命令，
    `rm -rf /` / `sudo ...` 在 L2 规则表即被 deny，而不是被 "ide.openTerminal" 名义放行。
    """
    if name not in IDE_TOOL_REGISTRY:
        raise KeyError(f"unknown IDE tool: {name}")
    a = args or {}
    if name == "ide.openTerminal":
        cmd = str(a.get("command") or "").strip()
        return cmd if cmd else "ide openTerminal"
    if name == "ide.runTask":
        return f"ide runTask {a.get('name', '')}"
    if name == "ide.getSetting":
        return f"ide getSetting {a.get('section', '')}"
    if name == "ide.updateSetting":
        return f"ide updateSetting {a.get('section', '')}"
    if name == "ide.installExtension":
        return f"installExtension {a.get('id', '')}"
    if name == "ide.runCommand":
        return f"ide runCommand {a.get('commandId', '')}"
    if name == "env.addDevcontainerFeature":
        return f"env addDevcontainerFeature {a.get('feature', '')}"
    if name == "env.miseUse":
        return f"env miseUse {a.get('tool', '')} {a.get('version', '')}"
    return "devcontainer rebuild"  # env.rebuildDevcontainer


@dataclass(frozen=True)
class IdeCallResult:
    """一次 governed IDE 工具调用的结论。decision=allow 才执行过 caller。"""

    decision: str  # "allow" | "deny" | "ask"
    level: str
    reason: str
    result: object = None
    error: str | None = None


def evaluate_ide_action(name: str, args: dict | None = None, *,
                        cwd: str | None = None, mode: str = "default") -> PermissionVerdict:
    """单独做权限裁决（不执行）。链式命令语义：任一分段 deny → 整体 deny。"""
    action = render_ide_action(name, args)
    return evaluate_command(action, cwd=cwd, mode=mode, rules=_COMBINED_RULES)


def governed_ide_call(
    name: str,
    args: dict | None = None,
    *,
    cwd: str | None = None,
    mode: str = "default",
    caller=call_ide_tool,
    audit_conn=None,
    factory_id: str | None = None,
) -> IdeCallResult:
    """五级管线裁决 + 仅 allow 执行 + factory_events 审计。

    - deny/ask：不执行 caller，结论留痕后返回（ask 需人工放行后由上层重调）。
    - allow：执行 caller；执行异常捕获进 error 不上抛（fail-open，桥不可用可判）。
    - 审计：audit_conn+factory_id 给定时写 ide_tool_call 事件；append_event 自身 fail-open。
    """
    action = render_ide_action(name, args)  # KeyError 上抛：未知工具名属于编程错误
    verdict = evaluate_command(action, cwd=cwd, mode=mode, rules=_COMBINED_RULES)
    result: object = None
    error: str | None = None
    if verdict.decision == "allow":
        try:
            result = caller(name, args or {})
        except Exception as e:  # noqa: BLE001 — fail-open：桥不可用/工具报错都进 error
            error = str(e)[:300]
    if audit_conn is not None and factory_id:
        append_event(audit_conn, factory_id, "ide_tool_call", {
            "name": name,
            "args": args or {},
            "action": action,
            "decision": verdict.decision,
            "level": verdict.level,
            "reason": verdict.reason,
            "error": error,
        })
    return IdeCallResult(verdict.decision, verdict.level, verdict.reason, result, error)
