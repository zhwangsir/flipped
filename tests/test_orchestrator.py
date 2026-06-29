"""多 Agent 监督编排单测（确定性，注入 stub supervisor/worker/overseer/verifier，无需真 LLM）。"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from driving.orchestrator import build_orchestrator  # noqa: E402


def _run(*, sup_done=None, worker_sigs=None, overseer_actions=None, verify_results=None,
         max_iter=4, loop_threshold=3):
    c = {"sup": 0, "work": 0, "over": 0}

    def supervisor(state):
        i = c["sup"]; c["sup"] += 1
        done = sup_done[i] if (sup_done and i < len(sup_done)) else False
        return {"current_subtask": f"sub{i}", "believe_done": done,
                "history": state.get("history", []) + [{"step": "supervisor"}]}

    def worker(state):
        i = c["work"]; c["work"] += 1
        sig = worker_sigs[i] if (worker_sigs and i < len(worker_sigs)) else f"sig{i}"
        return {"last_obs": {"summary": {"tool_calls": 1}},
                "signatures": state.get("signatures", []) + [sig],
                "history": state.get("history", []) + [{"step": "worker", "signature": sig}]}

    def overseer(state):
        i = c["over"]; c["over"] += 1
        act = overseer_actions[i] if (overseer_actions and i < len(overseer_actions)) else "continue"
        v = {"action": act, "efficiency": 0.8, "direction": 0.8, "issues": [], "rationale": "stub"}
        upd = {"verdict": v, "history": state.get("history", []) + [{"step": "overseer", "verdict": v}]}
        if act != "continue":
            upd["feedback"] = "overseer:" + act
        return upd

    vseq = list(verify_results or [])

    def verifier(cmd, cwd):
        ok = vseq.pop(0) if vseq else False
        return ok, ("" if ok else "FAIL")

    g = build_orchestrator(supervisor, worker, overseer, verifier, checkpointer=None)
    final = g.invoke({
        "goal": "G", "cwd": "/tmp", "verify_cmd": ["true"],
        "max_iterations": max_iter, "loop_threshold": loop_threshold,
        "iteration": 0, "signatures": [], "feedback": "", "verified": False,
        "done": False, "stop_reason": "", "history": [],
    })
    return final, c


def test_happy_dispatch_work_oversee_verify():
    final, c = _run(verify_results=[True])
    assert final["done"] is True and final["stop_reason"] == "verified"
    assert c["sup"] == 1 and c["work"] == 1 and c["over"] == 1  # 三 agent 各跑一次


def test_supervisor_believe_done_skips_worker():
    # supervisor 相信完成 → 跳过 worker 直接强制验证
    final, c = _run(sup_done=[True], verify_results=[True])
    assert final["done"] is True and final["stop_reason"] == "verified"
    assert c["work"] == 0, "believe_done 应跳过 worker"


def test_overseer_abort():
    final, c = _run(overseer_actions=["abort"], verify_results=[True])
    assert final["stop_reason"] == "overseer_abort"
    assert c["over"] == 1


def test_overseer_replan_then_pass():
    # overseer 先判定 replan(回 supervisor 重规划) → 再 continue → 验收过
    final, c = _run(overseer_actions=["replan", "continue"], verify_results=[True])
    assert final["stop_reason"] == "verified"
    assert c["sup"] == 2 and c["work"] == 2  # 重规划导致再调度一轮


def test_forced_verify_retry():
    final, c = _run(verify_results=[False, True])  # 不同签名(默认)→不循环
    assert final["stop_reason"] == "verified"
    assert final["iteration"] == 2


def test_circuit_breaker():
    final, _ = _run(verify_results=[False] * 9, max_iter=3)  # 不同签名→熔断而非循环
    assert final["stop_reason"] == "circuit_breaker"
    assert final["iteration"] == 3


def test_loop_detection():
    final, _ = _run(verify_results=[False] * 9, worker_sigs=["X"] * 9, loop_threshold=3, max_iter=10)
    assert final["stop_reason"] == "loop_detected"
    assert final["iteration"] == 3


if __name__ == "__main__":
    for fn in (test_happy_dispatch_work_oversee_verify, test_supervisor_believe_done_skips_worker,
               test_overseer_abort, test_overseer_replan_then_pass, test_forced_verify_retry,
               test_circuit_breaker, test_loop_detection):
        fn()
    print("orchestrator 单测: 全部通过 ✅（Supervisor+Worker+Overseer 监督编排：调度/跳过/中止/重规划/验证/熔断/循环）")
