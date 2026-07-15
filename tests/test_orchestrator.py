"""多 Agent 监督编排单测（确定性，注入 stub supervisor/worker/overseer/verifier，无需真 LLM）。"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from langgraph.checkpoint.memory import InMemorySaver  # noqa: E402
from langgraph.types import Command  # noqa: E402

from driving.orchestrator import build_orchestrator  # noqa: E402


def _run(*, sup_done=None, worker_sigs=None, overseer_actions=None, verify_results=None,
         max_iter=4, loop_threshold=3):
    c = {"sup": 0, "work": 0, "over": 0}

    def supervisor(state):
        i = c["sup"]; c["sup"] += 1
        # M89 verify 逻辑: verified = ok and believe_done。
        # 默认:verify 跑过至少一次(iteration>=1)且上次 verify 通过(feedback 不含"退出非0")
        # → believe_done=True 让整体 verified 结束。
        # verify 失败时 feedback 含"验收命令退出非0",保持 believe_done=False 让 worker 重试。
        if sup_done is not None:
            done = sup_done[i] if i < len(sup_done) else sup_done[-1]
        else:
            # M89 verify 逻辑:verify ok but believe_done=False 时 feedback 追加"已完成且验证通过"。
            # 检测到该标记 → 下一个 supervisor believe_done=True 让整体 verified 结束。
            # verify 失败时 feedback 含"退出非0",不含"已完成且验证通过" → 保持 done=False 让 worker 重试。
            fb = state.get("feedback", "")
            it = state.get("iteration", 0)
            done = it >= 1 and "已完成且验证通过" in fb
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
    final, c = _run(verify_results=[True, True])
    assert final["done"] is True and final["stop_reason"] == "verified"
    # M89 verify 逻辑:第一轮 verify ok 但 believe_done=False → 回 sup(2) believe_done=True → verify verified
    assert c["sup"] == 2 and c["work"] == 1 and c["over"] == 1  # sup 跑 2 次(拆任务+确认完成),worker/overseer 各 1 次


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
    # sup_done: 前两次 believe_done=False(拆子任务), 第三次 True(确认整体完成)
    final, c = _run(overseer_actions=["replan", "continue"], verify_results=[True, True],
                    sup_done=[False, False, True])
    assert final["stop_reason"] == "verified"
    assert c["sup"] == 3 and c["work"] == 2  # 重规划导致再调度一轮,sup 3 次(拆+重拆+确认)


def test_forced_verify_retry():
    # M89 verify 逻辑:verify 失败→sup believe_done=False 重试 → verify ok but believe_done=False → sup believe_done=True → verify verified
    final, c = _run(verify_results=[False, True, True])  # 不同签名(默认)→不循环
    assert final["stop_reason"] == "verified"
    assert final["iteration"] == 3  # 3 次 verify(1 fail + 1 ok but !done + 1 ok and done)


def test_circuit_breaker():
    final, _ = _run(verify_results=[False] * 9, max_iter=3)  # 不同签名→熔断而非循环
    assert final["stop_reason"] == "circuit_breaker"
    assert final["iteration"] == 3


def test_loop_detection():
    final, _ = _run(verify_results=[False] * 9, worker_sigs=["X"] * 9, loop_threshold=3, max_iter=10)
    assert final["stop_reason"] == "loop_detected"
    assert final["iteration"] == 3


def _approval_graph(supervisor):
    c = {"work": 0, "sup": 0}
    _wrapped = [supervisor]

    def supervisor_wrapped(state):
        c["sup"] += 1
        # M89 verify 逻辑:verify ok but believe_done=False 时 feedback 追加"已完成且验证通过"。
        # 检测到该标记 → supervisor believe_done=True 让整体 verified 结束。
        # reject 场景:sup(2) 时还没 verify → done=False → worker 执行 → verify → sup(3) done=True
        result = _wrapped[0](state)
        fb = state.get("feedback", "")
        if state.get("iteration", 0) >= 1 and "已完成且验证通过" in fb:
            result["believe_done"] = True
        return result

    def worker(state):
        c["work"] += 1
        return {"last_obs": {"summary": {}}, "signatures": state.get("signatures", []) + ["s"],
                "history": state.get("history", []) + [{"step": "worker"}]}

    def overseer(state):
        return {"verdict": {"action": "continue"}, "history": state.get("history", []) + [{"step": "overseer"}]}

    def verifier(cmd, cwd):
        return True, ""

    g = build_orchestrator(supervisor_wrapped, worker, overseer, verifier, checkpointer=InMemorySaver())
    init = {"goal": "G", "cwd": "/tmp", "verify_cmd": ["true"], "max_iterations": 3, "loop_threshold": 3,
            "require_approval": True, "iteration": 0, "signatures": [], "feedback": "", "verified": False,
            "done": False, "stop_reason": "", "history": []}
    return g, init, c


def test_approval_gate_high_risk_then_approve():
    def supervisor(state):
        return {"current_subtask": "git push origin main", "believe_done": False,
                "history": state.get("history", []) + [{"step": "supervisor"}]}
    g, init, c = _approval_graph(supervisor)
    cfg = {"configurable": {"thread_id": "appr"}}
    res = g.invoke(init, cfg)
    assert "__interrupt__" in res, "高风险子任务应 interrupt 等审批"
    assert c["work"] == 0, "审批前 worker 不应执行"
    res2 = g.invoke(Command(resume="approve"), cfg)
    assert res2.get("verified") is True and c["work"] == 1  # 放行后 worker 执行


def test_approval_gate_reject_then_replan_safe():
    def supervisor(state):
        # 被否决后(feedback 含'否决')改走安全方案
        sub = "ls -la" if "否决" in state.get("feedback", "") else "git push origin main"
        return {"current_subtask": sub, "believe_done": False,
                "history": state.get("history", []) + [{"step": "supervisor"}]}
    g, init, c = _approval_graph(supervisor)
    cfg = {"configurable": {"thread_id": "rej"}}
    g.invoke(init, cfg)
    res = g.invoke(Command(resume="reject"), cfg)  # 否决高风险 → 回 supervisor → 安全方案 → 直通
    assert res.get("verified") is True and c["work"] == 1


def test_worker_error_fast_fail():
    # M90 后:worker 永远失败 → relay 接力一次 → 再失败 → 终结 stop_reason="worker_error"
    # 接力后仍失败才判定为基础设施故障,快速失败不进 overseer/verify 空转
    c = {"over": 0, "work": 0}

    def supervisor(state):
        return {"current_subtask": "sub", "believe_done": False,
                "history": state.get("history", []) + [{"step": "supervisor"}]}

    def worker(state):
        c["work"] += 1
        return {"last_obs": {"ok": False, "summary": {"tool_calls": 0}}, "worker_error": True,
                "signatures": state.get("signatures", []) + ["x"],
                "history": state.get("history", []) + [{"step": "worker"}]}

    def overseer(state):
        c["over"] += 1
        return {"verdict": {"action": "continue"}, "history": state.get("history", [])}

    def verifier(cmd, cwd):
        return True, ""

    g = build_orchestrator(supervisor, worker, overseer, verifier, checkpointer=None)
    final = g.invoke({"goal": "G", "cwd": "/tmp", "verify_cmd": ["true"], "max_iterations": 4,
                      "loop_threshold": 3, "iteration": 0, "signatures": [], "feedback": "",
                      "verified": False, "done": False, "stop_reason": "", "history": [], "worker_error": False})
    assert final["stop_reason"] == "worker_error", f"应 worker_error, 实 {final['stop_reason']}"
    assert c["over"] == 0, "worker 报错应快速失败，不进 overseer"
    assert c["work"] == 2, f"M90 接力后 worker 应被调用 2 次(原试+接力重试), 实 {c['work']}"
    assert final.get("relay_attempted") is True, "应标记已接力"
    assert final.get("iteration", 0) == 0, "不应进 verify 计数"


# ---- M90 自动交替接力单测 ----

def test_worker_error_relay_then_success():
    # M90 核心场景:worker 第一次失败(coder)→ relay 切换 architect → 第二次成功 → 正常完成
    c = {"work": 0, "over": 0, "verify": 0, "sup": 0}
    worker_aliases: list[str] = []

    def supervisor(state):
        i = c["sup"]; c["sup"] += 1
        # 第二次 supervisor(接力成功后回拆):believe_done=True 让 verify 后整体完成
        done = True if i >= 1 else False
        return {"current_subtask": "sub", "believe_done": done,
                "history": state.get("history", []) + [{"step": "supervisor"}]}

    def worker(state):
        c["work"] += 1
        worker_aliases.append(state.get("worker_alias", "coder"))
        if c["work"] == 1:
            # 第一次:coder 卡死
            return {"last_obs": {"ok": False, "summary": {"tool_calls": 0}},
                    "worker_error": True,
                    "signatures": state.get("signatures", []) + ["fail"],
                    "history": state.get("history", []) + [{"step": "worker", "attempt": 1}]}
        # 第二次:architect 接力成功
        return {"last_obs": {"ok": True, "summary": {"tool_calls": 2}},
                "signatures": state.get("signatures", []) + ["ok"],
                "history": state.get("history", []) + [{"step": "worker", "attempt": 2}]}

    def overseer(state):
        c["over"] += 1
        return {"verdict": {"action": "continue", "efficiency": 0.8, "direction": 0.8,
                            "issues": [], "rationale": "接力后成功"}}

    def verifier(cmd, cwd):
        c["verify"] += 1
        return True, ""

    g = build_orchestrator(supervisor, worker, overseer, verifier, checkpointer=None)
    final = g.invoke({"goal": "G", "cwd": "/tmp", "verify_cmd": ["true"], "max_iterations": 4,
                      "loop_threshold": 3, "iteration": 0, "signatures": [], "feedback": "",
                      "verified": False, "done": False, "stop_reason": "", "history": [],
                      "worker_error": False})
    assert final["verified"] is True, "接力成功后应验收通过"
    assert final["stop_reason"] != "worker_error", "不应 worker_error 终结"
    assert c["work"] == 2, f"worker 应调用 2 次, 实 {c['work']}"
    assert worker_aliases == ["coder", "architect"], \
        f"接力应切换 alias coder→architect, 实 {worker_aliases}"
    assert final.get("relay_attempted") is True, "应标记已接力"


def test_relay_switches_alias_back_to_coder():
    # 验证双向切换:初始 architect 失败 → relay 切回 coder
    c = {"work": 0, "sup": 0}
    aliases: list[str] = []

    def supervisor(state):
        i = c["sup"]; c["sup"] += 1
        done = True if i >= 1 else False
        return {"current_subtask": "sub", "believe_done": done,
                "history": state.get("history", []) + [{"step": "supervisor"}]}

    def worker(state):
        c["work"] += 1
        aliases.append(state.get("worker_alias", "coder"))
        if c["work"] == 1:
            return {"last_obs": {"ok": False, "summary": {"tool_calls": 0}},
                    "worker_error": True,
                    "signatures": [], "history": state.get("history", [])}
        return {"last_obs": {"ok": True, "summary": {"tool_calls": 1}},
                "signatures": [], "history": state.get("history", [])}

    def overseer(state):
        return {"verdict": {"action": "continue"}}

    def verifier(cmd, cwd):
        return True, ""

    g = build_orchestrator(supervisor, worker, overseer, verifier, checkpointer=None)
    final = g.invoke({"goal": "G", "cwd": "/tmp", "verify_cmd": ["true"], "max_iterations": 4,
                      "loop_threshold": 3, "iteration": 0, "signatures": [], "feedback": "",
                      "verified": False, "done": False, "stop_reason": "", "history": [],
                      "worker_error": False, "worker_alias": "architect"})
    assert aliases == ["architect", "coder"], \
        f"初始 architect 失败应切回 coder, 实 {aliases}"
    assert final["verified"] is True


def test_relay_only_once_no_infinite_loop():
    # 防无限接力:worker 永远失败,最多 relay 一次,第二次失败直接终结
    c = {"work": 0}

    def supervisor(state):
        return {"current_subtask": "sub", "believe_done": False,
                "history": state.get("history", []) + [{"step": "supervisor"}]}

    def worker(state):
        c["work"] += 1
        return {"last_obs": {"ok": False, "summary": {"tool_calls": 0}},
                "worker_error": True,
                "signatures": [], "history": state.get("history", [])}

    def overseer(state):
        return {"verdict": {"action": "continue"}}

    def verifier(cmd, cwd):
        return True, ""

    g = build_orchestrator(supervisor, worker, overseer, verifier, checkpointer=None)
    final = g.invoke({"goal": "G", "cwd": "/tmp", "verify_cmd": ["true"], "max_iterations": 4,
                      "loop_threshold": 3, "iteration": 0, "signatures": [], "feedback": "",
                      "verified": False, "done": False, "stop_reason": "", "history": [],
                      "worker_error": False})
    assert final["stop_reason"] == "worker_error", "两次失败后应终结"
    assert c["work"] == 2, f"最多 worker 2 次(原试+1次接力), 实 {c['work']}"
    assert final.get("relay_attempted") is True


# ---- GLM function calling 容错加固单测 ----

class _FakeStructured:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0

    def invoke(self, prompt):
        resp = self.responses[self.calls]
        self.calls += 1
        if isinstance(resp, Exception):
            raise resp
        return resp


class _FakeLLM:
    def __init__(self, responses):
        self.responses = responses

    def with_structured_output(self, schema_cls, method, include_raw):
        return _FakeStructured(self.responses)


def test_overseer_parses_string_issues_from_tool_call_args(monkeypatch):
    # 这两个测试专门验证 langchain 路径的 _parse_raw_response 对 raw 的解析。
    # _invoke_structured 默认走 _direct_glm_tool_call（绕过 langchain），
    # 这里显式启用 langchain 路径才能命中 with_structured_output → raw 兜底解析。
    monkeypatch.setenv("FLIPPED_USE_LANGCHAIN", "1")
    from types import SimpleNamespace

    raw = SimpleNamespace(
        content="",
        tool_calls=[{
            "name": "Verdict",
            "args": {
                "efficiency": 0.7,
                "direction": 0.8,
                "action": "continue",
                "issues": "单字符串问题",
                "rationale": "方向对",
            },
            "id": "1",
            "type": "tool_call",
        }],
    )

    def fake_make_llm(alias, callbacks=None):
        return _FakeLLM([{"parsed": None, "raw": raw}])

    monkeypatch.setattr("driving.orchestrator._make_llm", fake_make_llm)

    from driving.orchestrator import default_overseer
    state = {"goal": "G", "current_subtask": "s", "signatures": ["a"], "history": [], "last_obs": {"summary": {}}}
    upd = default_overseer(state)
    assert upd["verdict"]["action"] == "continue"
    assert upd["verdict"]["issues"] == ["单字符串问题"]


def test_overseer_parses_raw_json_content_when_parsed_none(monkeypatch):
    monkeypatch.setenv("FLIPPED_USE_LANGCHAIN", "1")
    from types import SimpleNamespace

    raw = SimpleNamespace(
        content='思考中...\n{"efficiency":0.9,"direction":1.0,"action":"replan","issues":["绕路"],"rationale":"从JSON解析"}',
        tool_calls=[],
    )

    def fake_make_llm(alias, callbacks=None):
        return _FakeLLM([{"parsed": None, "raw": raw}])

    monkeypatch.setattr("driving.orchestrator._make_llm", fake_make_llm)

    from driving.orchestrator import default_overseer
    state = {"goal": "G", "current_subtask": "s", "signatures": ["a"], "history": [], "last_obs": {"summary": {}}}
    upd = default_overseer(state)
    assert upd["verdict"]["action"] == "replan"
    assert upd["verdict"]["rationale"] == "从JSON解析"


def test_overseer_fail_open_on_empty_response(monkeypatch):
    def fake_make_llm(alias, callbacks=None):
        return _FakeLLM([Exception("GLM 返回空响应")])

    monkeypatch.setattr("driving.orchestrator._make_llm", fake_make_llm)

    from driving.orchestrator import default_overseer
    state = {"goal": "G", "current_subtask": "s", "signatures": ["a"], "history": [], "last_obs": {"summary": {}}}
    upd = default_overseer(state)
    assert upd["verdict"]["action"] == "continue"
    assert "fail-open" in upd["verdict"]["rationale"]


def test_supervisor_prompt_forbids_rebuild_on_verify_failure():
    from driving.orchestrator import _build_supervisor_prompt
    state = {
        "goal": "写服务",
        "cwd": "/tmp",
        "feedback": "验收命令退出非0:\nImportError: No module named 'foo'",
        "project_rules": "",
        "repo_map": "",
        "context_summary": None,
    }
    prompt = _build_supervisor_prompt(state)
    assert "最小精确修复" in prompt
    assert "严禁删除" in prompt or "禁止" in prompt


if __name__ == "__main__":
    for fn in (test_happy_dispatch_work_oversee_verify, test_supervisor_believe_done_skips_worker,
               test_overseer_abort, test_overseer_replan_then_pass, test_forced_verify_retry,
               test_circuit_breaker, test_loop_detection,
               test_approval_gate_high_risk_then_approve, test_approval_gate_reject_then_replan_safe,
               test_worker_error_fast_fail,
               test_worker_error_relay_then_success,
               test_relay_switches_alias_back_to_coder,
               test_relay_only_once_no_infinite_loop):
        fn()
    print("orchestrator 单测: 全部通过 ✅（Supervisor+Worker+Overseer 监督编排：调度/跳过/中止/重规划/验证/熔断/循环/M90 自动交替接力）")
