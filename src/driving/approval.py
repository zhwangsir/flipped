"""驾驭层 · 人工审批硬断点（D11 / M3.5）。

高风险动作前用 LangGraph `interrupt()` **确定性硬暂停**，等人放行/否决（AGENTS.md §7「沙箱外要审批」）。
不靠 agent 自觉（Cline auto-approve 是模型自分类、不可靠，D13）——由状态机强制。
配 checkpointer 后：interrupt 暂停 → `Command(resume=决定)` 续跑。
"""
from __future__ import annotations

import re
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


def build_approval_graph(checkpointer):
    """审批门控图：classify → gate(高风险则 interrupt) → END。需 checkpointer 支持 interrupt。"""

    def classify(state: GateState) -> GateState:
        return {"risk": classify_risk(state.get("action", ""))}

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
