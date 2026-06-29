"""人工审批硬断点单测（确定性：风险分类 + interrupt 暂停/放行/否决）。"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from langgraph.checkpoint.memory import InMemorySaver  # noqa: E402
from langgraph.types import Command  # noqa: E402

from driving.approval import build_approval_graph, classify_risk  # noqa: E402


def test_classify_risk():
    assert classify_risk("git push origin main") == "high"
    assert classify_risk("rm -rf /tmp/x") == "high"
    assert classify_risk("kubectl apply -f x.yaml") == "high"
    assert classify_risk("echo hello && ls -la") == "low"
    assert classify_risk("python3 test_math.py") == "low"


def _graph(tid):
    return build_approval_graph(InMemorySaver()), {"configurable": {"thread_id": tid}}


def test_high_risk_pauses_then_approve():
    g, cfg = _graph("approve")
    res = g.invoke({"action": "git push origin main"}, cfg)
    assert "__interrupt__" in res, "高风险动作应 interrupt 暂停"
    res2 = g.invoke(Command(resume="approve"), cfg)
    assert res2["approved"] is True
    assert res2["decided"] == "approved"


def test_high_risk_pauses_then_reject():
    g, cfg = _graph("reject")
    g.invoke({"action": "rm -rf build"}, cfg)
    res = g.invoke(Command(resume="reject"), cfg)
    assert res["approved"] is False
    assert res["decided"] == "rejected"


def test_low_risk_auto_proceeds():
    g, cfg = _graph("auto")
    res = g.invoke({"action": "ls -la"}, cfg)
    assert "__interrupt__" not in res, "低风险不应暂停"
    assert res["approved"] is True
    assert res["decided"] == "auto"


if __name__ == "__main__":
    test_classify_risk()
    test_high_risk_pauses_then_approve()
    test_high_risk_pauses_then_reject()
    test_low_risk_auto_proceeds()
    print("approval 单测: 全部通过 ✅（风险分类 + interrupt 暂停/放行/否决）")
