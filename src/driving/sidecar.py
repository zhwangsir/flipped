"""驾驭层 · 强制验证 sidecar（D11 / M3.3）。

LangGraph 状态机把 Cline 当执行器：跑任务 → **强制**跑验收命令判定 done（不靠 agent 自报）。
不过 → 回灌失败详情重做；触顶 → 熔断退出（AGENTS.md §6）。SqliteSaver 做 checkpoint（崩溃恢复地基）。

设计为可测：executor / verifier 可注入，单测用 stub 即可确定性验证"强制验证 + 循环 + 熔断"逻辑，无需真 LLM。
"""
from __future__ import annotations

import subprocess
from typing import Callable, TypedDict

from langgraph.graph import END, START, StateGraph

from driving.observe import run_and_observe

DEFAULT_VERIFY_TIMEOUT = 300


class DriveState(TypedDict, total=False):
    task: str
    cwd: str
    verify_cmd: list[str]
    max_iterations: int
    iteration: int
    feedback: str
    verified: bool
    history: list[dict]


# (effective_task, cwd) -> observe 结果 dict
Executor = Callable[[str, str], dict]
# (verify_cmd, cwd) -> (ok, 输出尾部)
Verifier = Callable[[list[str], str], "tuple[bool, str]"]


def _default_executor(task: str, cwd: str) -> dict:
    return run_and_observe(task, cwd)


def _default_verifier(cmd: list[str], cwd: str) -> "tuple[bool, str]":
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                          timeout=DEFAULT_VERIFY_TIMEOUT)
    return proc.returncode == 0, (proc.stdout + proc.stderr)[-2000:]


def build_graph(executor: Executor = _default_executor,
                verifier: Verifier = _default_verifier,
                checkpointer=None):
    """编译强制验证状态机。executor/verifier 可注入以便单测。"""

    def execute(state: DriveState) -> DriveState:
        fb = state.get("feedback", "")
        eff = state["task"] if not fb else (
            f"{state['task']}\n\n[上一轮验收失败，必须修复后再完成]:\n{fb}"
        )
        obs = executor(eff, state["cwd"])
        hist = state.get("history", []) + [{"step": "execute", "summary": obs.get("summary")}]
        return {"history": hist}

    def verify(state: DriveState) -> DriveState:
        ok, output = verifier(state["verify_cmd"], state["cwd"])
        it = state.get("iteration", 0) + 1
        hist = state.get("history", []) + [{"step": "verify", "ok": ok, "iteration": it}]
        upd: DriveState = {"iteration": it, "verified": ok, "history": hist}
        if not ok:
            upd["feedback"] = f"验收命令 {' '.join(state['verify_cmd'])} 退出非 0：\n{output}"
        return upd

    def route(state: DriveState) -> str:
        if state.get("verified"):
            return END
        if state.get("iteration", 0) >= state.get("max_iterations", 3):
            return END  # 熔断（§6）：修 N 次仍不过则停止上报
        return "execute"

    g = StateGraph(DriveState)
    g.add_node("execute", execute)
    g.add_node("verify", verify)
    g.add_edge(START, "execute")
    g.add_edge("execute", "verify")
    g.add_conditional_edges("verify", route, {"execute": "execute", END: END})
    return g.compile(checkpointer=checkpointer)


def drive(task: str, cwd: str, verify_cmd: list[str], *,
          max_iterations: int = 3, thread_id: str = "default",
          db_path: str = ":memory:", data_dir: str | None = None) -> DriveState:
    """强制验证地驱动一个任务到验收通过或熔断，返回最终 state。

    用 SqliteSaver（db_path 给文件路径则可崩溃恢复：同 thread_id 重跑续上）。
    data_dir：cline 的隔离配置目录（含 OpenAI-Compatible provider 鉴权）。
    """
    from langgraph.checkpoint.sqlite import SqliteSaver

    executor: Executor = (
        (lambda t, c: run_and_observe(t, c, data_dir=data_dir)) if data_dir else _default_executor
    )
    initial: DriveState = {
        "task": task, "cwd": cwd, "verify_cmd": verify_cmd,
        "max_iterations": max_iterations, "iteration": 0,
        "feedback": "", "verified": False, "history": [],
    }
    with SqliteSaver.from_conn_string(db_path) as cp:
        graph = build_graph(executor=executor, checkpointer=cp)
        return graph.invoke(initial, config={"configurable": {"thread_id": thread_id}})


if __name__ == "__main__":
    import json
    import sys

    if len(sys.argv) < 4:
        print("用法: python -m driving.sidecar <cwd> <task> <verify_cmd...>")
        sys.exit(2)
    cwd_arg, task_arg, vcmd = sys.argv[1], sys.argv[2], sys.argv[3:]
    final = drive(task_arg, cwd_arg, vcmd)
    print(json.dumps({"verified": final.get("verified"),
                      "iteration": final.get("iteration"),
                      "history": final.get("history")}, ensure_ascii=False, indent=2))
