"""M136-D · 结构化工具错误（retryable + suggestion）与输出截断单测（确定性，无需真 LLM）。"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from driving.orchestrator import (  # noqa: E402
    _classify_tool_error,
    _trim_output,
    build_orchestrator,
)


# ---------- _classify_tool_error ----------


def test_classify_timeout_is_retryable():
    meta = _classify_tool_error("command timed out after 300s")
    assert meta["retryable"] is True
    assert meta["suggestion"]


def test_classify_transient_patterns_retryable():
    for msg in (
        "httpx.ConnectTimeout: timed out",
        "ConnectionRefusedError: [Errno 61] Connection refused",
        "429 Too Many Requests: rate limit exceeded",
        "502 Bad Gateway",
        "503 Service Unavailable",
        "resource temporarily unavailable",
        "database is busy",
    ):
        assert _classify_tool_error(msg)["retryable"] is True, msg


def test_classify_syntax_error_not_retryable_with_suggestion():
    meta = _classify_tool_error(
        '  File "app.py", line 3\n    def f(:\n           ^\nSyntaxError: invalid syntax')
    assert meta["retryable"] is False
    assert "语法" in meta["suggestion"]


def test_classify_file_not_found_suggests_path_check():
    meta = _classify_tool_error("python: can't open file 'x.py': [Errno 2] No such file or directory")
    assert meta["retryable"] is False
    assert "路径" in meta["suggestion"]


def test_classify_permission_denied():
    meta = _classify_tool_error("PermissionError: [Errno 13] Permission denied: '/etc/x'")
    assert meta["retryable"] is False
    assert "权限" in meta["suggestion"]


def test_classify_verify_failure_suggests_reading_output():
    meta = _classify_tool_error("AssertionError: assert add(1, 2) == 3, 1 failed")
    assert meta["retryable"] is False
    assert meta["suggestion"]


def test_classify_unknown_default():
    meta = _classify_tool_error("some weird failure nobody saw before")
    assert meta["retryable"] is False
    assert meta["suggestion"]  # 有兜底建议


def test_classify_empty_message_default():
    meta = _classify_tool_error("")
    assert meta["retryable"] is False
    assert meta["suggestion"]


# ---------- _trim_output ----------


def test_trim_output_short_text_unchanged():
    text = "short output"
    assert _trim_output(text) == text
    assert _trim_output(text, budget=100) == text
    assert _trim_output("") == ""


def test_trim_output_long_text_truncated_with_marker():
    text = "HEAD" + "A" * 5000 + "TAIL" + "B" * 5000
    out = _trim_output(text, budget=1000)
    assert len(out) <= 1000
    assert "[... truncated" in out
    assert "chars ...]" in out
    # 头保留
    assert out.startswith("HEAD")
    # 尾保留
    assert out.endswith("B" * 100)


def test_trim_output_preserves_head_and_tail_content():
    text = "BEGINNING-" + "m" * 10000 + "-ENDING"
    out = _trim_output(text, budget=500)
    assert "BEGINNING-" in out
    assert "-ENDING" in out
    assert len(out) <= 500


def test_trim_output_tiny_budget_still_bounded():
    text = "x" * 1000
    out = _trim_output(text, budget=20)
    assert len(out) <= 20


def test_trim_output_exact_budget_boundary_unchanged():
    text = "y" * 4000
    assert _trim_output(text, budget=4000) == text


# ---------- 集成：verify 失败反馈带结构化错误元数据 ----------


def _run_graph(verifier, *, max_iter=1):
    """最小编排图：supervisor 直接 believe_done → verify。"""
    def supervisor(state):
        return {"current_subtask": "sub", "believe_done": True,
                "history": state.get("history", []) + [{"step": "supervisor"}]}

    def worker(state):  # 不会被走到（believe_done 跳过 worker），占位
        return {"last_obs": {"summary": {}}, "signatures": ["s"],
                "history": state.get("history", [])}

    def overseer(state):
        return {"verdict": {"action": "continue"}, "history": state.get("history", [])}

    g = build_orchestrator(supervisor, worker, overseer, verifier, checkpointer=None)
    return g.invoke({
        "goal": "G", "cwd": "/tmp", "verify_cmd": ["false"],
        "max_iterations": max_iter, "loop_threshold": 3,
        "iteration": 0, "signatures": [], "feedback": "", "verified": False,
        "done": False, "stop_reason": "", "history": [],
    })


def test_failing_verify_feedback_contains_error_meta_retryable():
    def verifier(cmd, cwd):
        return False, "httpx.ReadTimeout: timed out while verifying"

    final = _run_graph(verifier)
    fb = final["feedback"]
    assert "验收命令退出非0" in fb  # 旧字符串消费者不破坏
    assert "[error_meta]" in fb
    assert "retryable=true" in fb
    assert "suggestion=" in fb


def test_failing_verify_feedback_contains_error_meta_deterministic():
    def verifier(cmd, cwd):
        return False, "SyntaxError: invalid syntax (index.html, line 42)"

    final = _run_graph(verifier)
    fb = final["feedback"]
    assert "[error_meta]" in fb
    assert "retryable=false" in fb
    assert "语法" in fb


def test_failing_verify_feedback_trims_huge_output():
    big_output = "E" * 20000

    def verifier(cmd, cwd):
        return False, big_output

    final = _run_graph(verifier)
    fb = final["feedback"]
    assert "[... truncated" in fb
    assert len(fb) < len(big_output)
    assert "[error_meta]" in fb


if __name__ == "__main__":
    test_classify_timeout_is_retryable()
    test_trim_output_long_text_truncated_with_marker()
    test_failing_verify_feedback_contains_error_meta_retryable()
    print("tool_result_structured 单测: 通过 ✅")
