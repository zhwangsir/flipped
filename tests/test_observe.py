"""observe.parse_events / summarize 单测（纯函数，无需 cline 运行）。

样本取自真实 cline CLI --json 输出形状（content_start/content_end contentType=tool 等）。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from driving.observe import parse_events, summarize  # noqa: E402

SAMPLE = """
{"ts":"t1","type":"agent_event","event":{"type":"iteration_start","iteration":1}}
{"ts":"t2","type":"agent_event","event":{"type":"content_start","contentType":"reasoning","reasoning":"thinking"}}
{"ts":"t3","type":"agent_event","event":{"type":"content_start","contentType":"tool","toolName":"editor","toolCallId":"functions.editor:0","input":{"path":"/tmp/x/greeting.txt","new_text":"hello"}}}
{"ts":"t4","type":"agent_event","event":{"type":"content_start","contentType":"tool","toolName":"run_commands","toolCallId":"functions.run_commands:1","input":{"commands":[{"command":"cat","args":["/tmp/x/greeting.txt"]}]}}}
{"ts":"t5","type":"agent_event","event":{"type":"content_end","contentType":"tool","toolName":"run_commands","toolCallId":"functions.run_commands:1","output":[{"query":"cat","result":"hello","success":true}],"durationMs":3}}
{"ts":"t6","type":"agent_event","event":{"type":"iteration_end","iteration":1,"hadToolCalls":true,"toolCallCount":2}}
{"ts":"t7","type":"agent_event","event":{"type":"usage","inputTokens":100,"outputTokens":20,"totalCost":0}}
{"ts":"t8","type":"hook_event","hookEventName":"tool_call"}
{"ts":"t9","type":"agent_event","event":{"type":"done","reason":"completed","iterations":1,"text":"Done!"}}
"""


def test_parse_tool_events():
    recs = parse_events(SAMPLE.splitlines())
    calls = [r for r in recs if r["kind"] == "tool_call"]
    results = [r for r in recs if r["kind"] == "tool_result"]
    assert [c["tool"] for c in calls] == ["editor", "run_commands"], "应抽到两个工具调用(按序)"
    assert calls[0]["input"]["path"].endswith("greeting.txt"), "editor 入参 path 应保留"
    assert results and results[0]["durationMs"] == 3, "tool_result 应带 durationMs"
    assert results[0]["output"][0]["success"] is True, "tool_result output 保留"


def test_ignores_non_agent_events():
    recs = parse_events(SAMPLE.splitlines())
    assert all(r["kind"] != "hook_event" for r in recs), "hook_event(非 agent_event)应被忽略"
    assert any(r["kind"] == "done" and r["reason"] == "completed" for r in recs)


def test_summarize():
    s = summarize(parse_events(SAMPLE.splitlines()))
    assert s["tool_calls"] == 2
    assert s["tools_used"] == ["editor", "run_commands"]
    assert s["iterations"] == 1 and s["reason"] == "completed"


def test_empty():
    assert parse_events([]) == []
    assert summarize([]) == {"tool_calls": 0, "tools_used": [], "iterations": None, "reason": None}


if __name__ == "__main__":
    test_parse_tool_events()
    test_ignores_non_agent_events()
    test_summarize()
    test_empty()
    print("observe 单测: 全部通过 ✅")
