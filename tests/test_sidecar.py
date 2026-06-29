"""强制验证 sidecar 单测（确定性，注入 stub，无需真 LLM）。"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from driving.sidecar import build_graph  # noqa: E402


def _run(verifier_results, max_iter=3):
    calls = {"exec": 0, "tasks": []}

    def executor(task, cwd):
        calls["exec"] += 1
        calls["tasks"].append(task)
        return {"summary": {"tool_calls": 1}}

    seq = list(verifier_results)

    def verifier(cmd, cwd):
        ok = seq.pop(0) if seq else False
        return ok, ("" if ok else "FAIL output")

    graph = build_graph(executor=executor, verifier=verifier, checkpointer=None)
    final = graph.invoke({
        "task": "do X", "cwd": "/tmp", "verify_cmd": ["true"],
        "max_iterations": max_iter, "iteration": 0,
        "feedback": "", "verified": False, "history": [],
    })
    return final, calls


def test_happy_path():
    final, calls = _run([True])
    assert final["verified"] is True
    assert final["iteration"] == 1
    assert calls["exec"] == 1


def test_forced_retry_until_pass():
    # 前两次验收失败 -> 强制回灌重做 -> 第三次过
    final, calls = _run([False, False, True], max_iter=5)
    assert final["verified"] is True, "第三次应通过"
    assert final["iteration"] == 3, f"应迭代 3 次, 实 {final['iteration']}"
    assert calls["exec"] == 3, "执行器应被调用 3 次(每次验收失败都重做)"
    assert "上一轮验收失败" in calls["tasks"][1], "重试时必须把失败详情回灌进任务"


def test_circuit_breaker():
    # 永远失败 -> 触顶熔断, 不无限循环(§6)
    final, calls = _run([False] * 10, max_iter=3)
    assert final["verified"] is False
    assert final["iteration"] == 3, "应在 max_iterations 触顶熔断"
    assert calls["exec"] == 3


if __name__ == "__main__":
    test_happy_path()
    test_forced_retry_until_pass()
    test_circuit_breaker()
    print("sidecar 单测: 全部通过 ✅（强制验证 + 回灌重试 + 熔断）")
