"""驾驭层 · 人工审批硬断点（D11 / M3.5）+ M136-E 五级权限管线。

高风险动作前用 LangGraph `interrupt()` **确定性硬暂停**，等人放行/否决（AGENTS.md §7「沙箱外要审批」）。
不靠 agent 自觉（Cline auto-approve 是模型自分类、不可靠，D13）——由状态机强制。
配 checkpointer 后：interrupt 暂停 → `Command(resume=决定)` 续跑。

M136-E 新增 Grok-Build 风格五级权限管线（`evaluate_permission` / `evaluate_command`，纯函数可单测）：
L1 hooks → L2 规则表(glob, deny>ask>allow) → L3 记忆放行(`.flipped/approvals.json`)
→ L4 只读白名单 → L5 模式策略(default/dontAsk/plan)。首个出结论的级别短路。
旧的 classify_risk / 审批图契约保持不变，classify 节点额外把管线 verdict 记入 state["verdict"]。
"""
from __future__ import annotations

import fnmatch
import json
import os
import re
from dataclasses import dataclass
from typing import TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

# 高风险动作模式：逸出沙箱 / 不可逆 / 对外副作用 / 触碰凭据（§7、D13）
HIGH_RISK_PATTERNS = [
    r"\bgit\s+push\b", r"\bgit\b.*\bmerge\b", r"\brm\s+-rf\b", r"\bsudo\b",
    r"\bdocker\b.*\b(rm|rmi|prune)\b", r"\bnpm\s+publish\b", r"\bpip\b.*\bupload\b",
    r"\bdeploy\b", r"\bkubectl\b", r"\bterraform\s+(apply|destroy)\b",
    r"\bcurl\b.*\b(POST|PUT|DELETE)\b", r"secret|token|password|credential",
    r"devcontainer.*rebuild", r"\bnix\s+profile\b", r"installExtension",
    r"settings.*update.*user", r"\bshutdown\b|\breboot\b",
]

APPROVE_WORDS = {"approve", "approved", "yes", "y", "true", "1", "ok", "放行", "同意"}


def classify_risk(action: str) -> str:
    """把一个动作（命令 / 工具描述）分类为 high / low 风险。纯函数，可单测。"""
    a = action or ""
    for pat in HIGH_RISK_PATTERNS:
        if re.search(pat, a, re.IGNORECASE):
            return "high"
    return "low"


class GateState(TypedDict, total=False):
    action: str
    risk: str
    approved: bool
    decided: str  # approved / rejected / auto
    verdict: dict  # M136-E：五级权限管线结论 {"decision","level","reason"}
    cwd: str  # 可选：供 L3 记忆放行定位项目目录
    mode: str  # 可选：default / dontAsk / plan，默认 default


# ---------------------------------------------------------------------------
# M136-E · 五级权限管线（Grok-Build 风格）
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PermissionVerdict:
    """一次权限评估的结论。decision: allow/deny/ask；level: 哪个级别拍板；reason: 为什么。"""

    decision: str  # "allow" | "deny" | "ask"
    level: str  # "L1".."L5" | "combined"
    reason: str

    def to_dict(self) -> dict:
        return {"decision": self.decision, "level": self.level, "reason": self.reason}


# L2 默认规则表：fnmatch glob 命中整个 action 字符串；多规则命中按 deny > ask > allow 裁决
DEFAULT_RULES = [
    {"decision": "deny", "pattern": "rm -rf /"},
    {"decision": "deny", "pattern": "sudo *"},
    {"decision": "deny", "pattern": "git push --force*"},
    {"decision": "deny", "pattern": "*secret*"},
    {"decision": "deny", "pattern": "*token*"},
    {"decision": "ask", "pattern": "git push*"},
    {"decision": "ask", "pattern": "npm publish*"},
    {"decision": "ask", "pattern": "docker"},
    {"decision": "ask", "pattern": "docker *"},
    {"decision": "ask", "pattern": "curl*-X POST*"},
    {"decision": "ask", "pattern": "curl*-X PUT*"},
    {"decision": "ask", "pattern": "curl*-X DELETE*"},
]

_RULE_PRECEDENCE = {"deny": 0, "ask": 1, "allow": 2}

# L4 只读命令白名单：按命令头（首个 token）匹配
READ_ONLY_HEADS = {
    "ls", "cat", "head", "tail", "grep", "rg", "find", "pwd", "echo",
    "which", "whoami", "date", "wc", "file", "stat", "env", "printenv",
    "hostname", "uname", "less", "more", "tree", "du", "df", "jq",
    "basename", "dirname", "realpath", "readlink", "type", "whereis", "id",
}

# L4 只读命令白名单：按前两个 token 匹配（带子命令/参数的只读形态）
READ_ONLY_PREFIXES = {
    "git status", "git log", "git diff", "git show", "git branch",
    "git rev-parse", "git remote", "git blame", "git ls-files",
    "python --version", "python3 --version", "node --version",
    "npm list", "npm ls", "pip list", "pip show",
    "cargo --version", "go version",
}

# 含重定向 / tee 的命令视为有写副作用，永不当作只读（简化判定，已知局限）
_WRITE_HINTS = re.compile(r">|\btee\b")


def _is_read_only(action: str) -> bool:
    """保守判定只读命令。已知局限：不解析引号/子 shell，`find -delete`、`sed -i` 等变体不覆盖。"""
    tokens = action.strip().split()
    if not tokens:
        return False
    if _WRITE_HINTS.search(action):
        return False
    if tokens[0] in READ_ONLY_HEADS:
        return True
    return " ".join(tokens[:2]) in READ_ONLY_PREFIXES


def _grants_path(cwd: str) -> str:
    return os.path.join(cwd, ".flipped", "approvals.json")


def load_grants(cwd: str) -> list:
    """读取 `<cwd>/.flipped/approvals.json`（JSON glob 列表）。缺失/损坏/结构不对 → 空列表（fail-open）。"""
    try:
        with open(_grants_path(cwd), encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return [p for p in data if isinstance(p, str)]
        return []
    except Exception:
        return []


def remember_grant(cwd: str, pattern: str) -> list:
    """把一个已批准的 glob pattern 持久化到项目级 approvals.json（幂等去重），返回完整列表。"""
    grants = load_grants(cwd)
    if pattern not in grants:
        grants.append(pattern)
    os.makedirs(os.path.dirname(_grants_path(cwd)), exist_ok=True)
    with open(_grants_path(cwd), "w", encoding="utf-8") as f:
        json.dump(grants, f, ensure_ascii=False, indent=2)
    return grants


# ---------------------------------------------------------------------------
# M165.2b · 宿主侧 grants（assistant approve scope=always 持久化目标）
#
# 与项目级 <cwd>/.flipped/approvals.json 的区别：会话 cwd 可能是容器路径
# （/projects/x 或 /workspace），绝不能往那里写。宿主侧统一落
# data/approval_grants.json（相对项目根），结构 {"<cwd>": ["pattern1", ...]}，
# cwd 作为 key 原样存字符串；orchestrator approval_gate 用同一 cwd 字符串读取匹配。
# ---------------------------------------------------------------------------


def host_grants_path() -> str:
    """宿主侧 grants 文件路径：env FLIPPED_HOST_GRANTS 可覆盖，默认 data/approval_grants.json。"""
    return os.environ.get("FLIPPED_HOST_GRANTS", "data/approval_grants.json")


def load_host_grants(cwd: str) -> list:
    """读取宿主侧 grants 文件中该 cwd 的 pattern 列表。缺失/损坏/结构不对 → 空列表（fail-open）。"""
    try:
        with open(host_grants_path(), encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            patterns = data.get(cwd, [])
            if isinstance(patterns, list):
                return [p for p in patterns if isinstance(p, str)]
        return []
    except Exception:
        return []


def remember_host_grant(cwd: str, pattern: str) -> list:
    """把 pattern 持久化到宿主侧 grants 文件（按 cwd key 隔离，幂等去重），返回该 cwd 完整列表。

    整字典读出→改单 key→整字典写回，保留其他 cwd 的 grants；损坏文件自愈重写。
    """
    try:
        with open(host_grants_path(), encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            data = {}
    except Exception:
        data = {}
    grants = data.get(cwd)
    if not isinstance(grants, list):
        grants = []
    grants = [p for p in grants if isinstance(p, str)]
    if pattern not in grants:
        grants.append(pattern)
    data[cwd] = grants
    parent = os.path.dirname(host_grants_path())
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(host_grants_path(), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return grants


def evaluate_permission(
    action: str,
    *,
    cwd: str | None = None,
    mode: str = "default",
    rules: list | None = None,
    hooks: list | None = None,
) -> PermissionVerdict:
    """五级权限管线，纯函数。严格按 L1→L5 顺序，首个出结论的级别短路。

    rules=None 用 DEFAULT_RULES（传 [] 表示无规则）；hooks=None 表示无 hook。
    未知 mode fail-open 到 default 策略。
    """
    a = (action or "").strip()

    # L1 hooks：任一 deny 即否决；hook 抛异常 fail-open 忽略
    for hook in (hooks or []):
        try:
            if hook(a) == "deny":
                name = getattr(hook, "__name__", repr(hook))
                return PermissionVerdict("deny", "L1", f"hook {name} 否决")
        except Exception:
            continue

    # L2 规则表：glob 命中多条时 deny > ask > allow
    matched = [
        r for r in (DEFAULT_RULES if rules is None else rules)
        if fnmatch.fnmatchcase(a, str(r.get("pattern", "")))
    ]
    if matched:
        best = min(matched, key=lambda r: _RULE_PRECEDENCE.get(r.get("decision"), 3))
        decision = best.get("decision")
        if decision not in ("allow", "deny", "ask"):
            decision = "ask"  # 未知 decision 保守降级为 ask
        return PermissionVerdict(decision, "L2", f"规则 {best.get('pattern')!r} → {decision}")

    # L3 记忆放行（per-project）
    if cwd:
        for pat in load_grants(cwd):
            if fnmatch.fnmatchcase(a, pat):
                return PermissionVerdict("allow", "L3", f"命中已记住的放行 {pat!r}")

    # L4 只读自动放行
    if _is_read_only(a):
        return PermissionVerdict("allow", "L4", "只读命令白名单自动放行")

    # L5 模式策略
    if mode == "dontAsk":
        return PermissionVerdict("allow", "L5", "dontAsk 模式：全部放行")
    if mode == "plan":
        return PermissionVerdict("ask", "L5", "plan 模式：非只读动作需审批")
    # default（未知 mode 也走这里，fail-open 到 default 策略）
    if classify_risk(a) == "high":
        return PermissionVerdict("ask", "L5", "default 模式：高风险动作需审批")
    return PermissionVerdict("allow", "L5", "default 模式：低风险自动放行")


# 链式拆分：&& / || / ; / |。已知局限：不尊重引号，引号内的分隔符也会被拆开。
_CHAIN_SPLIT = re.compile(r"&&|\|\||[;|]")


def evaluate_command(cmd: str, **kw) -> PermissionVerdict:
    """先按 shell 连接符拆成段，每段走 L1–L5；合并：任一 deny → deny（reason 点名分段），
    否则任一 ask → ask，否则 allow。kw 透传给 evaluate_permission。"""
    segments = [s.strip() for s in _CHAIN_SPLIT.split(cmd or "")]
    segments = [s for s in segments if s]
    if not segments:
        return PermissionVerdict("allow", "combined", "空命令")
    verdicts = [evaluate_permission(seg, **kw) for seg in segments]
    for seg, v in zip(segments, verdicts):
        if v.decision == "deny":
            return PermissionVerdict("deny", v.level, f"分段 {seg!r} 被否决（{v.reason}）")
    for seg, v in zip(segments, verdicts):
        if v.decision == "ask":
            return PermissionVerdict("ask", v.level, f"分段 {seg!r} 需审批（{v.reason}）")
    if len(verdicts) == 1:
        return verdicts[0]
    return PermissionVerdict("allow", "combined", f"{len(verdicts)} 个分段全部放行")


def build_approval_graph(checkpointer):
    """审批门控图：classify → gate(高风险则 interrupt) → END。需 checkpointer 支持 interrupt。

    M136-E：classify 节点额外跑五级权限管线并把 verdict 记入 state["verdict"]；
    gate 的 interrupt/放行/否决契约完全不变。
    """

    def classify(state: GateState) -> GateState:
        action = state.get("action", "")
        verdict = evaluate_permission(
            action, cwd=state.get("cwd"), mode=state.get("mode", "default")
        )
        return {"risk": classify_risk(action), "verdict": verdict.to_dict()}

    def gate(state: GateState) -> GateState:
        if state.get("risk") == "high":
            decision = interrupt({
                "action": state.get("action"),
                "reason": "高风险动作，逸出沙箱/不可逆，需人工放行（§7）",
            })
            ok = str(decision).strip().lower() in APPROVE_WORDS
            return {"approved": ok, "decided": "approved" if ok else "rejected"}
        return {"approved": True, "decided": "auto"}

    g = StateGraph(GateState)
    g.add_node("classify", classify)
    g.add_node("gate", gate)
    g.add_edge(START, "classify")
    g.add_edge("classify", "gate")
    g.add_edge("gate", END)
    return g.compile(checkpointer=checkpointer)
