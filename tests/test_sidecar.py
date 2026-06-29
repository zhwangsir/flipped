"""强制验证 + 循环检测 sidecar 单测（确定性，注入 stub，无需真 LLM）。"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from driving.sidecar import action_signature, build_graph  # noqa: E402


def _run(verifier_results, *, max_iter=3, loop_threshold=3, sig_seq=None):
    """sig_seq: 每轮 execute 产出的"动作签名种子"列表；None=每轮唯一(不触发循环)。"""
    calls = {"exec": 0, "tasks": []}

    def executor(task, cwd):
        i = calls["exec"]
        calls["exec"] += 1
        calls["tasks"].append(task)
        seed = sig_seq[i] if (sig_seq and i < len(sig_seq)) else f"uniq{i}"
        # 用一个 tool_call(input.path=seed) 让本轮签名取决于 seed
        return {"summary": {"tool_calls": 1},
                "records": [{"kind": "tool_call", "tool": "editor", "input": {"path": seed}}]}

    seq = list(verifier_results)

    def verifier(cmd, cwd):
        ok = seq.pop(0) if seq else False
        return ok, ("" if ok else "FAIL output")

    graph = build_graph(executor=executor, verifier=verifier, checkpointer=None)
    final = graph.invoke({
        "task": "do X", "cwd": "/tmp", "verify_cmd": ["true"],
        "max_iterations": max_iter, "loop_threshold": loop_threshold,
        "iteration": 0, "feedback": "", "verified": False, "stuck": False,
        "stop_reason": "", "signatures": [], "history": [],
    })
    return final, calls


def test_signature_same_action():
    s1 = action_signature([{"kind": "tool_call", "tool": "editor", "input": {"path": "a.py"}}])
    s2 = action_signature([{"kind": "tool_call", "tool": "editor", "input": {"path": "a.py"}}])
    s3 = action_signature([{"kind": "tool_call", "tool": "editor", "input": {"path": "b.py"}}])
    assert s1 == s2 and s1 != s3


def test_happy_path():
    final, calls = _run([True])
    assert final["verified"] is True
    assert final["iteration"] == 1
    assert final["stop_reason"] == "verified"
    assert calls["exec"] == 1


def test_forced_retry_until_pass():
    # 每轮不同签名 -> 不触发循环；前两次失败 -> 第三次过
    final, calls = _run([False, False, True], max_iter=5)
    assert final["verified"] is True
    assert final["iteration"] == 3
    assert calls["exec"] == 3
    assert "上一轮验收失败" in calls["tasks"][1]


def test_circuit_breaker():
    # 每轮不同签名(不循环) + 永远失败 -> 触顶 max_iterations 熔断
    final, calls = _run([False] * 10, max_iter=3)
    assert final["verified"] is False
    assert final["iteration"] == 3
    assert final["stop_reason"] == "circuit_breaker"
    assert not final.get("stuck")


def test_loop_detection():
    # 每轮相同签名 + 永远失败 -> 同动作重复达阈值即判定卡死(早于熔断)
    final, calls = _run([False] * 10, max_iter=10, loop_threshold=3, sig_seq=["X"] * 10)
    assert final["verified"] is False
    assert final.get("stuck") is True
    assert final["stop_reason"] == "loop_detected"
    assert final["iteration"] == 3, f"应在重复 3 次即中断, 实 {final['iteration']}"
    # 升级提示：第 3 次 execute 的任务里应带"换思路重规划"
    assert "换一个完全不同的思路" in calls["tasks"][2]


if __name__ == "__main__":
    test_signature_same_action()
    test_happy_path()
    test_forced_retry_until_pass()
    test_circuit_breaker()
    test_loop_detection()
    print("sidecar 单测: 全部通过 ✅（签名 + 强制验证 + 回灌重试 + 熔断 + 循环检测）")
