"""驾驭层 · 强制验证 + 循环检测 sidecar（D11 / M3.3 + M3.4）。

LangGraph 状态机把 Cline 当执行器：跑任务 → **强制**跑验收命令判定 done（不靠 agent 自报）。
- 不过 → 回灌失败详情重做；
- **循环检测**：跨步记录每轮"动作签名"，同一签名重复 ≥ loop_threshold → 判定卡死、中断（先升级"换思路重规划"提示）；
- 触顶 max_iterations → 熔断（AGENTS.md §6）。
SqliteSaver 做 checkpoint（崩溃恢复地基）。executor / verifier 可注入，单测无需真 LLM。
"""
from __future__ import annotations

import json
import subprocess
from typing import Callable, TypedDict

from langgraph.graph import END, START, StateGraph

from driving.observe import run_and_observe

DEFAULT_VERIFY_TIMEOUT = 300
DEFAULT_LOOP_THRESHOLD = 3


class DriveState(TypedDict, total=False):
    task: str
    cwd: str
    verify_cmd: list[str]
    max_iterations: int
    loop_threshold: int
    iteration: int
    feedback: str
    verified: bool
    stuck: bool
    stop_reason: str          # verified / loop_detected / circuit_breaker
    signatures: list[str]
    history: list[dict]


# (effective_task, cwd) -> observe 结果 dict（含 records）
Executor = Callable[[str, str], dict]
# (verify_cmd, cwd) -> (ok, 输出尾部)
Verifier = Callable[[list[str], str], "tuple[bool, str]"]


def action_signature(records: list[dict]) -> str:
    """从一轮的工具轨迹算"动作签名"：工具名 + 规范化目标(文件/命令)的有序集合。

    同文件/同命令/同动作的一轮会得到相同签名 → 供循环检测比对。
    """
    parts = set()
    for r in records or []:
        if r.get("kind") != "tool_call":
            continue
        inp = r.get("input")
        if isinstance(inp, dict):
            target = inp.get("path") or inp.get("file") or inp.get("command") or json.dumps(inp, sort_keys=True, ensure_ascii=False)
        else:
            target = str(inp)
        parts.add(f"{r.get('tool')}:{str(target)[:80]}")
    return "|".join(sorted(parts))


def _default_executor(task: str, cwd: str) -> dict:
    return run_and_observe(task, cwd)


def _default_verifier(cmd: list[str], cwd: str) -> "tuple[bool, str]":
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                          timeout=DEFAULT_VERIFY_TIMEOUT)
    return proc.returncode == 0, (proc.stdout + proc.stderr)[-2000:]


def build_graph(executor: Executor = _default_executor,
                verifier: Verifier = _default_verifier,
                checkpointer=None):
    """编译"强制验证 + 循环检测"状态机。executor/verifier 可注入以便单测。"""

    def execute(state: DriveState) -> DriveState:
        fb = state.get("feedback", "")
        eff = state["task"] if not fb else (
            f"{state['task']}\n\n[上一轮验收失败，必须修复后再完成]:\n{fb}"
        )
        obs = executor(eff, state["cwd"])
        sig = action_signature(obs.get("records") or [])
        sigs = state.get("signatures", []) + [sig]
        hist = state.get("history", []) + [
            {"step": "execute", "summary": obs.get("summary"), "signature": sig}
        ]
        return {"signatures": sigs, "history": hist}

    def verify(state: DriveState) -> DriveState:
        ok, output = verifier(state["verify_cmd"], state["cwd"])
        it = state.get("iteration", 0) + 1
        sigs = state.get("signatures", [])
        last = sigs[-1] if sigs else None
        repeats = sigs.count(last) if last is not None else 0
        threshold = state.get("loop_threshold", DEFAULT_LOOP_THRESHOLD)
        looping = bool(last) and repeats >= threshold

        upd: DriveState = {"iteration": it, "verified": ok,
                           "history": state.get("history", []) + [
                               {"step": "verify", "ok": ok, "iteration": it, "repeats": repeats}]}
        if ok:
            upd["stop_reason"] = "verified"
        elif looping:
            upd["stuck"] = True
            upd["stop_reason"] = "loop_detected"
        elif it >= state.get("max_iterations", 3):
            upd["stop_reason"] = "circuit_breaker"
        else:
            # 普通重试；若同一动作已重复（≥2 次）则升级为"换思路重规划"提示
            hint = ("⚠ 你已重复同一动作多次仍未通过验收，停止重复，"
                    "请换一个完全不同的思路重新分析根因。\n") if (last and repeats >= 2) else ""
            upd["feedback"] = hint + f"验收命令 {' '.join(state['verify_cmd'])} 退出非 0：\n{output}"
        return upd

    def route(state: DriveState) -> str:
        if state.get("verified") or state.get("stuck"):
            return END
        if state.get("iteration", 0) >= state.get("max_iterations", 3):
            return END  # 熔断（§6）
        return "execute"

    g = StateGraph(DriveState)
    g.add_node("execute", execute)
    g.add_node("verify", verify)
    g.add_edge(START, "execute")
    g.add_edge("execute", "verify")
    g.add_conditional_edges("verify", route, {"execute": "execute", END: END})
    return g.compile(checkpointer=checkpointer)


def drive(task: str, cwd: str, verify_cmd: list[str], *,
          max_iterations: int = 3, loop_threshold: int = DEFAULT_LOOP_THRESHOLD,
          thread_id: str = "default", db_path: str = ":memory:",
          data_dir: str | None = None) -> DriveState:
    """强制验证地驱动一个任务到验收通过 / 循环卡死 / 熔断，返回最终 state。

    用 SqliteSaver（db_path 给文件路径则可崩溃恢复：同 thread_id 重跑续上）。
    data_dir：cline 的隔离配置目录（含 OpenAI-Compatible provider 鉴权）。
    """
    from langgraph.checkpoint.sqlite import SqliteSaver

    executor: Executor = (
        (lambda t, c: run_and_observe(t, c, data_dir=data_dir)) if data_dir else _default_executor
    )
    initial: DriveState = {
        "task": task, "cwd": cwd, "verify_cmd": verify_cmd,
        "max_iterations": max_iterations, "loop_threshold": loop_threshold,
        "iteration": 0, "feedback": "", "verified": False, "stuck": False,
        "stop_reason": "", "signatures": [], "history": [],
    }
    with SqliteSaver.from_conn_string(db_path) as cp:
        graph = build_graph(executor=executor, checkpointer=cp)
        return graph.invoke(initial, config={"configurable": {"thread_id": thread_id}})


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 4:
        print("用法: python -m driving.sidecar <cwd> <task> <verify_cmd...>")
        sys.exit(2)
    cwd_arg, task_arg, vcmd = sys.argv[1], sys.argv[2], sys.argv[3:]
    final = drive(task_arg, cwd_arg, vcmd)
    print(json.dumps({"verified": final.get("verified"), "stop_reason": final.get("stop_reason"),
                      "iteration": final.get("iteration"), "history": final.get("history")},
                     ensure_ascii=False, indent=2))
