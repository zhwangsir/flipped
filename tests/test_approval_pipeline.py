"""M136-E 五级权限管线单测（L1 hooks → L2 规则表 → L3 记忆放行 → L4 只读白名单 → L5 模式策略 + bash 链式拆分）。

同时覆盖既有契约的向后兼容：HIGH_RISK_PATTERNS / APPROVE_WORDS / classify_risk /
GateState / build_approval_graph 语义不变，classify 节点额外把管线 verdict 记入 state。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from langgraph.checkpoint.memory import InMemorySaver  # noqa: E402
from langgraph.types import Command  # noqa: E402

from driving.approval import (  # noqa: E402
    APPROVE_WORDS,
    HIGH_RISK_PATTERNS,
    GateState,
    PermissionVerdict,
    build_approval_graph,
    classify_risk,
    evaluate_command,
    evaluate_permission,
    load_grants,
    remember_grant,
)

# ---------------------------------------------------------------------------
# L1 hooks
# ---------------------------------------------------------------------------


def test_l1_hook_deny_wins_over_everything():
    # "ls -la" 本来会被 L4 只读白名单放行，但 L1 deny 优先
    v = evaluate_permission("ls -la", hooks=[lambda action: "deny"])
    assert v.decision == "deny"
    assert v.level == "L1"


def test_l1_hook_none_falls_through():
    v = evaluate_permission("ls -la", hooks=[lambda action: None])
    assert v.decision == "allow"
    assert v.level == "L4"


def test_l1_hook_exception_fail_open():
    def boom(action):
        raise RuntimeError("hook 炸了")

    v = evaluate_permission("ls -la", hooks=[boom])
    assert v.decision == "allow", "hook 异常应 fail-open，继续走后续级别"


# ---------------------------------------------------------------------------
# L2 规则表
# ---------------------------------------------------------------------------


def test_l2_precedence_deny_over_ask_over_allow():
    rules = [
        {"decision": "allow", "pattern": "deploy*"},
        {"decision": "ask", "pattern": "*prod*"},
        {"decision": "deny", "pattern": "deploy*prod*"},
    ]
    v = evaluate_permission("deploy to prod", rules=rules)
    assert v.decision == "deny"
    assert v.level == "L2"


def test_l2_precedence_ask_over_allow():
    rules = [
        {"decision": "allow", "pattern": "deploy*"},
        {"decision": "ask", "pattern": "*prod*"},
    ]
    v = evaluate_permission("deploy to prod", rules=rules)
    assert v.decision == "ask"
    assert v.level == "L2"


def test_l2_glob_matching():
    rules = [{"decision": "deny", "pattern": "git push --force*"}]
    assert evaluate_permission("git push --force origin main", rules=rules).decision == "deny"
    # 不命中规则则继续往 L5 走（default 模式下 git push 是 high → ask，而不是 deny）
    assert evaluate_permission("git push origin main", rules=rules).decision != "deny"


def test_l2_default_rules_deny():
    assert evaluate_permission("rm -rf /").decision == "deny"
    assert evaluate_permission("sudo apt install x").decision == "deny"
    assert evaluate_permission("git push --force origin main").decision == "deny"
    assert evaluate_permission("echo token=abc").decision == "deny"


def test_l2_default_rules_ask():
    assert evaluate_permission("git push origin main").decision == "ask"
    assert evaluate_permission("npm publish").decision == "ask"
    assert evaluate_permission("docker run alpine").decision == "ask"
    assert evaluate_permission("curl -X POST https://example.com").decision == "ask"
    assert evaluate_permission("curl -X DELETE https://example.com").decision == "ask"


# ---------------------------------------------------------------------------
# L3 记忆放行（per-project 持久化）
# ---------------------------------------------------------------------------


def test_l3_remember_grant_roundtrip(tmp_path):
    cwd = str(tmp_path)
    assert load_grants(cwd) == [], "无文件时应返回空列表"
    remember_grant(cwd, "make deploy*")
    remember_grant(cwd, "kubectl apply*")
    assert load_grants(cwd) == ["make deploy*", "kubectl apply*"]
    # 重复记忆同一 pattern 不应产生重复条目
    remember_grant(cwd, "make deploy*")
    assert load_grants(cwd) == ["make deploy*", "kubectl apply*"]


def test_l3_remembered_pattern_allows(tmp_path):
    cwd = str(tmp_path)
    remember_grant(cwd, "make deploy*")
    # "make deploy prod" 含 deploy，default 模式 L5 本会 ask；L3 记忆放行优先
    v = evaluate_permission("make deploy prod", cwd=cwd)
    assert v.decision == "allow"
    assert v.level == "L3"


def test_l3_corrupt_json_fail_open(tmp_path):
    grants_dir = tmp_path / ".flipped"
    grants_dir.mkdir()
    (grants_dir / "approvals.json").write_text("{not valid json", encoding="utf-8")
    cwd = str(tmp_path)
    assert load_grants(cwd) == [], "损坏的 JSON 应 fail-open 为空列表"
    v = evaluate_permission("make deploy prod", cwd=cwd)
    assert v.decision == "ask"
    assert v.level == "L5"


# ---------------------------------------------------------------------------
# L4 只读自动放行
# ---------------------------------------------------------------------------


def test_l4_readonly_auto_approve():
    v = evaluate_permission("git status")
    assert v.decision == "allow"
    assert v.level == "L4"
    assert evaluate_permission("ls -la").decision == "allow"
    assert evaluate_permission("git log --oneline -5").decision == "allow"
    assert evaluate_permission("cat README.md").decision == "allow"
    assert evaluate_permission("git diff HEAD~1").decision == "allow"


def test_l4_redirect_is_not_readonly():
    # 含重定向写入的 echo 不算只读，L4 不得放行
    v = evaluate_permission("echo hi > f.txt", mode="plan")
    assert v.decision == "ask"
    assert v.level == "L5"


# ---------------------------------------------------------------------------
# L5 模式策略
# ---------------------------------------------------------------------------


def test_l5_default_mode():
    v = evaluate_permission("rm -rf build")
    assert v.decision == "ask"
    assert v.level == "L5"
    assert evaluate_permission("echo hi").decision == "allow"


def test_l5_dontask_mode():
    v = evaluate_permission("rm -rf build", mode="dontAsk")
    assert v.decision == "allow"
    assert v.level == "L5"


def test_l5_plan_mode():
    assert evaluate_permission("git status", mode="plan").decision == "allow"
    v = evaluate_permission("echo hi > f.txt", mode="plan")
    assert v.decision == "ask"
    assert v.level == "L5"


# ---------------------------------------------------------------------------
# bash 链式拆分
# ---------------------------------------------------------------------------


def test_chain_any_deny_wins_and_names_segment():
    v = evaluate_command("ls && rm -rf /")
    assert v.decision == "deny"
    assert "rm -rf /" in v.reason


def test_chain_all_allow():
    v = evaluate_command("git status && ls")
    assert v.decision == "allow"


def test_chain_any_ask():
    v = evaluate_command("echo hi && git push")
    assert v.decision == "ask"


def test_chain_pipe_and_semicolon_split():
    v = evaluate_command("cat x.txt | grep foo; ls")
    assert v.decision == "allow"


# ---------------------------------------------------------------------------
# 向后兼容
# ---------------------------------------------------------------------------


def test_backward_compat_classify_risk():
    assert classify_risk("git push origin main") == "high"
    assert classify_risk("ls") == "low"


def test_backward_compat_exports():
    assert isinstance(HIGH_RISK_PATTERNS, list) and HIGH_RISK_PATTERNS
    assert "approve" in APPROVE_WORDS
    assert "action" in GateState.__annotations__


def test_graph_constructs_and_records_verdict_low_risk():
    g = build_approval_graph(InMemorySaver())
    cfg = {"configurable": {"thread_id": "pipeline-smoke-low"}}
    res = g.invoke({"action": "ls -la"}, cfg)
    assert "__interrupt__" not in res
    assert res["approved"] is True
    assert res["decided"] == "auto"
    assert res["verdict"]["decision"] == "allow"


def test_graph_high_risk_records_verdict_and_still_interrupts():
    g = build_approval_graph(InMemorySaver())
    cfg = {"configurable": {"thread_id": "pipeline-smoke-high"}}
    res = g.invoke({"action": "git push origin main"}, cfg)
    assert "__interrupt__" in res, "高风险仍必须 interrupt 硬暂停"
    assert res["verdict"]["decision"] == "ask"
    res2 = g.invoke(Command(resume="approve"), cfg)
    assert res2["approved"] is True
    assert res2["decided"] == "approved"


def test_verdict_dataclass_shape():
    v = PermissionVerdict(decision="allow", level="L4", reason="r")
    assert v.to_dict() == {"decision": "allow", "level": "L4", "reason": "r"}
