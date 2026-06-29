"""驾驭层 · 多 Agent 监督编排（D15 / M3.6）。

Supervisor(GLM 调度) + Worker(Kimi via cline 执行) + Overseer(GLM 专属监督效率/方向)。
- **Supervisor**：把目标拆成"下一步子任务"（干净结构化任务，**不传全量历史**，避免上下文污染），或判定相信已完成。
- **Worker**：cline headless 执行该子任务，产出可观测轨迹 + 动作签名（复用 observe / sidecar.action_signature）。
- **Overseer**：分层监督——先**确定性预检**(复用动作签名: 同动作重复=低效/卡死)，再 **GLM 方向判断**(产出结构化 verdict)，
  条件路由 continue / replan(回 supervisor) / abort。worker=Kimi、overseer=GLM **跨模型族**避免自偏(D15)。
- **末端强制验证**(复用 sidecar 思路: 跑验收命令判定 done)。checkpointer 支持崩溃恢复/审批中断。

所有 LLM/worker 节点可注入 → 单测确定性、无需真 LLM；默认实现用 GLM/Kimi 经 LiteLLM:4000。
"""
from __future__ import annotations

import os
from typing import Callable, Literal, TypedDict

from langgraph.graph import END, START, StateGraph

from driving.observe import run_and_observe
from driving.sidecar import action_signature

DEFAULT_LOOP_THRESHOLD = 3


class OrchestratorState(TypedDict, total=False):
    goal: str
    cwd: str
    verify_cmd: list[str]
    data_dir: str
    max_iterations: int
    loop_threshold: int
    iteration: int
    current_subtask: str
    believe_done: bool
    signatures: list[str]
    last_obs: dict
    verdict: dict          # overseer 最近裁决
    feedback: str          # 回灌给 supervisor 的(验收失败/overseer 问题)
    verified: bool
    done: bool
    stop_reason: str       # verified / overseer_abort / loop_detected / circuit_breaker
    history: list[dict]


# 可注入节点：(state) -> state 增量
SupervisorFn = Callable[[OrchestratorState], dict]
WorkerFn = Callable[[OrchestratorState], dict]
OverseerFn = Callable[[OrchestratorState], dict]
VerifierFn = Callable[[list, str], "tuple[bool, str]"]


# ---------- 默认实现（GLM/Kimi 经 LiteLLM） ----------

def _make_llm(alias: str, temperature: float = 0):
    """构建指向 LiteLLM:4000 的 ChatOpenAI（alias=architect/coder）。"""
    from langchain_openai import ChatOpenAI

    base = os.environ.get("LITELLM_BASE_URL", "http://localhost:4000/v1")
    key = os.environ.get("LITELLM_MASTER_KEY", "dummy")
    return ChatOpenAI(model=alias, base_url=base, api_key=key, temperature=temperature, timeout=300)


def default_supervisor(state: OrchestratorState) -> dict:
    """GLM 调度：据目标 + 反馈，给出下一步子任务（干净结构化），或相信已完成。"""
    from pydantic import BaseModel, Field

    class Plan(BaseModel):
        believe_done: bool = Field(description="是否相信目标已达成(将由强制验证核对)")
        subtask: str = Field(description="给执行者(coder)的下一步具体子任务，自包含、含必要上下文，勿引用历史")
        rationale: str = Field(description="一句话理由")

    fb = state.get("feedback", "")
    msg = (f"目标：{state['goal']}\n工作目录：{state['cwd']}\n"
           f"{'反馈(上一轮验收失败/监督意见，必须据此调整)：' + fb if fb else '这是首轮。'}\n"
           "你是架构调度者。给出执行者下一步要做的【一个】自包含子任务；若相信目标已达成则 believe_done=true。")
    try:
        # method="function_calling"：GLM/exo 不支持 json_schema(langchain 默认)，但支持工具调用(M0.4)
        plan = _make_llm("architect").with_structured_output(Plan, method="function_calling").invoke(msg)
        sub, done, why = plan.subtask, plan.believe_done, plan.rationale
    except Exception as e:  # noqa: BLE001 失败兜底：直接把目标当子任务
        sub, done, why = state["goal"], False, f"(supervisor LLM 失败兜底: {e})"
    hist = state.get("history", []) + [{"step": "supervisor", "subtask": sub, "believe_done": done, "why": why}]
    return {"current_subtask": sub, "believe_done": done, "history": hist}


def default_worker(state: OrchestratorState) -> dict:
    """Kimi via cline 执行当前子任务（干净上下文：只给子任务字符串）。"""
    obs = run_and_observe(state["current_subtask"], state["cwd"],
                          model="coder", data_dir=state.get("data_dir"))
    sig = action_signature(obs.get("records") or [])
    sigs = state.get("signatures", []) + [sig]
    hist = state.get("history", []) + [{"step": "worker", "summary": obs.get("summary"), "signature": sig}]
    return {"last_obs": obs, "signatures": sigs, "history": hist}


def default_overseer(state: OrchestratorState) -> dict:
    """专属监督：确定性预检(效率) + GLM 方向判断 → 结构化 verdict + 路由动作。"""
    sigs = state.get("signatures", [])
    last = sigs[-1] if sigs else None
    repeats = sigs.count(last) if last else 0
    threshold = state.get("loop_threshold", DEFAULT_LOOP_THRESHOLD)

    # 1) 确定性预检：同一动作重复达阈值 = 低效/卡死 → 直接 replan（省一次 LLM）
    if last and repeats >= threshold:
        verdict = {"efficiency": 0.1, "direction": 0.5, "action": "replan",
                   "issues": [f"同一动作签名重复 {repeats} 次(低效/卡死)"],
                   "rationale": "确定性预检命中重复动作"}
        return _overseer_ret(state, verdict)

    # 2) GLM 方向判断（是否偏离目标 / 效率如何）
    from pydantic import BaseModel, Field

    class Verdict(BaseModel):
        efficiency: float = Field(description="0-1，worker 这步效率(是否绕路/低产)")
        direction: float = Field(description="0-1，是否朝目标正确方向推进")
        action: Literal["continue", "replan", "abort"] = Field(description="继续/回调度重规划/中止")
        issues: list[str] = Field(default_factory=list, description="发现的问题")
        rationale: str = Field(description="一句话理由")

    summary = (state.get("last_obs") or {}).get("summary", {})
    msg = (f"目标：{state['goal']}\n子任务：{state.get('current_subtask','')}\n"
           f"执行者本步轨迹概览：{summary}\n"
           "你是专属监督者：评估执行者这一步的【效率】(有无绕路/重复/低产)与【方向】(是否朝目标)。"
           "方向明显跑偏→replan；严重无望/危险→abort；正常→continue。")
    try:
        v = _make_llm("architect").with_structured_output(Verdict, method="function_calling").invoke(msg)
        verdict = {"efficiency": v.efficiency, "direction": v.direction, "action": v.action,
                   "issues": v.issues, "rationale": v.rationale}
    except Exception as e:  # noqa: BLE001 监督失败 fail-open: 不阻塞，交给强制验证兜底
        verdict = {"efficiency": 0.5, "direction": 0.5, "action": "continue",
                   "issues": [], "rationale": f"(overseer LLM 失败 fail-open: {e})"}
    return _overseer_ret(state, verdict)


def _overseer_ret(state: OrchestratorState, verdict: dict) -> dict:
    hist = state.get("history", []) + [{"step": "overseer", "verdict": verdict}]
    upd = {"verdict": verdict, "history": hist}
    if verdict["action"] != "continue":
        upd["feedback"] = f"监督意见: {verdict.get('rationale')} 问题: {verdict.get('issues')}"
    return upd


def _default_verifier(cmd: list, cwd: str) -> "tuple[bool, str]":
    import subprocess
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=300)
    return p.returncode == 0, (p.stdout + p.stderr)[-2000:]


# ---------- 图 ----------

def build_orchestrator(supervisor: SupervisorFn = default_supervisor,
                       worker: WorkerFn = default_worker,
                       overseer: OverseerFn = default_overseer,
                       verifier: VerifierFn = _default_verifier,
                       checkpointer=None):
    """编译 Supervisor→Worker→Overseer→(条件)→Verify 多 agent 监督图。节点可注入。"""

    def verify(state: OrchestratorState) -> dict:
        ok, output = verifier(state["verify_cmd"], state["cwd"])
        it = state.get("iteration", 0) + 1
        hist = state.get("history", []) + [{"step": "verify", "ok": ok, "iteration": it}]
        upd = {"iteration": it, "verified": ok, "history": hist}
        if ok:
            upd["done"] = True
            upd["stop_reason"] = "verified"
        else:
            upd["feedback"] = (state.get("feedback", "") + f"\n验收命令退出非0:\n{output}").strip()
        return upd

    def route_overseer(state: OrchestratorState) -> str:
        action = (state.get("verdict") or {}).get("action", "continue")
        if action == "abort":
            return "abort"
        if action == "replan":
            return "replan"
        return "verify"

    def mark_abort(state: OrchestratorState) -> dict:
        return {"done": True, "stop_reason": "overseer_abort"}

    def route_verify(state: OrchestratorState) -> str:
        if state.get("verified"):
            return END
        sigs = state.get("signatures", [])
        last = sigs[-1] if sigs else None
        if last and sigs.count(last) >= state.get("loop_threshold", DEFAULT_LOOP_THRESHOLD):
            return "loop"
        if state.get("iteration", 0) >= state.get("max_iterations", 3):
            return "breaker"
        return "supervisor"

    def mark_loop(state: OrchestratorState) -> dict:
        return {"done": True, "stop_reason": "loop_detected"}

    def mark_breaker(state: OrchestratorState) -> dict:
        return {"done": True, "stop_reason": "circuit_breaker"}

    g = StateGraph(OrchestratorState)
    g.add_node("supervisor", supervisor)
    g.add_node("worker", worker)
    g.add_node("overseer", overseer)
    g.add_node("verify", verify)
    g.add_node("abort", mark_abort)
    g.add_node("loop", mark_loop)
    g.add_node("breaker", mark_breaker)
    def _route_sup(state: OrchestratorState) -> str:
        # supervisor 相信已完成 → 直接强制验证（跳过冗余 worker 步）
        return "verify" if state.get("believe_done") else "worker"

    g.add_edge(START, "supervisor")
    g.add_conditional_edges("supervisor", _route_sup, {"worker": "worker", "verify": "verify"})
    g.add_edge("worker", "overseer")
    g.add_conditional_edges("overseer", route_overseer,
                            {"verify": "verify", "replan": "supervisor", "abort": "abort"})
    g.add_conditional_edges("verify", route_verify,
                            {"supervisor": "supervisor", "loop": "loop", "breaker": "breaker", END: END})
    g.add_edge("abort", END)
    g.add_edge("loop", END)
    g.add_edge("breaker", END)
    return g.compile(checkpointer=checkpointer)


def drive_orchestrated(goal: str, cwd: str, verify_cmd: list, *,
                       max_iterations: int = 4, loop_threshold: int = DEFAULT_LOOP_THRESHOLD,
                       thread_id: str = "default", db_path: str = ":memory:",
                       data_dir: str | None = None) -> OrchestratorState:
    """多 Agent 监督编排驱动一个目标到验收通过 / 监督中止 / 循环 / 熔断。"""
    from langgraph.checkpoint.sqlite import SqliteSaver

    initial: OrchestratorState = {
        "goal": goal, "cwd": cwd, "verify_cmd": verify_cmd, "data_dir": data_dir,
        "max_iterations": max_iterations, "loop_threshold": loop_threshold,
        "iteration": 0, "signatures": [], "feedback": "", "verified": False,
        "done": False, "stop_reason": "", "history": [],
    }
    with SqliteSaver.from_conn_string(db_path) as cp:
        graph = build_orchestrator(checkpointer=cp)
        return graph.invoke(initial, config={"configurable": {"thread_id": thread_id}},
                            )
