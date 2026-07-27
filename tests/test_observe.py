"""observe.parse_events / summarize 单测（纯函数，无需 cline 运行）。

样本取自真实 cline CLI --json 输出形状（content_start/content_end contentType=tool 等）。
"""
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from driving.observe import parse_events, summarize, write_audit, run_and_observe  # noqa: E402

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


def test_parse_events_skips_invalid_json_lines():
    """非 JSON 行 / 解析失败行应被静默跳过（覆盖 except 分支）。"""
    lines = [
        "not a json line at all",
        '{"broken": ',  # 截断的 JSON
        '{"ts":"ok","type":"agent_event","event":{"type":"done","reason":"completed","iterations":0}}',
        "",
        "   ",
    ]
    recs = parse_events(lines)
    assert len(recs) == 1
    assert recs[0]["kind"] == "done"
    assert recs[0]["reason"] == "completed"


def test_parse_events_strips_whitespace_and_skips_blank():
    """带前后空白的行 / 纯空行不应让解析器崩。"""
    recs = parse_events(["  {\"ts\":\"t\",\"type\":\"agent_event\",\"event\":{\"type\":\"done\"}}  ", ""])
    assert len(recs) == 1
    assert recs[0]["kind"] == "done"


def test_write_audit_writes_jsonl(tmp_path: Path):
    """write_audit 应建目录、按 JSONL 落盘。"""
    records = [
        {"kind": "tool_call", "ts": "t1", "tool": "editor"},
        {"kind": "done", "ts": "t2", "reason": "completed"},
    ]
    target = tmp_path / "nested" / "deeper" / "audit.jsonl"
    write_audit(records, str(target))
    assert target.exists()
    lines = target.read_text().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["kind"] == "tool_call"
    assert json.loads(lines[1])["reason"] == "completed"


def test_write_audit_handles_path_without_dirname(tmp_path: Path, monkeypatch):
    """os.path.dirname(path) 返回空串时应回退到 '.'。"""
    monkeypatch.chdir(tmp_path)
    records = [{"kind": "done", "ts": "t", "reason": "completed"}]
    # 文件名无目录前缀——触发 `or "."` 分支
    write_audit(records, "audit_flat.jsonl")
    assert (tmp_path / "audit_flat.jsonl").exists()


def _fake_completed_process(stdout: str, returncode: int = 0) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=["cline"], returncode=returncode, stdout=stdout, stderr="")


def test_run_and_observe_parses_cline_stdout(monkeypatch, tmp_path: Path):
    """run_and_observe 应构造 cline 命令、解析其 --json 输出、汇总返回。"""
    captured = {}

    def fake_run(cmd, capture_output, text, timeout):
        captured["cmd"] = cmd
        captured["timeout"] = timeout
        stdout = "\n".join([
            '{"ts":"t1","type":"agent_event","event":{"type":"content_start","contentType":"tool","toolName":"editor","toolCallId":"e:0","input":{"path":"/tmp/x"}}}',
            '{"ts":"t2","type":"agent_event","event":{"type":"content_end","contentType":"tool","toolName":"editor","toolCallId":"e:0","output":"ok","durationMs":5}}',
            '{"ts":"t3","type":"agent_event","event":{"type":"done","reason":"completed","iterations":1}}',
        ])
        return _fake_completed_process(stdout, returncode=0)

    monkeypatch.setattr("driving.observe.subprocess.run", fake_run)

    result = run_and_observe("fix the bug", str(tmp_path), model="coder", timeout=10)

    # 命令构造正确
    assert captured["cmd"][0] == "cline"
    assert "--json" in captured["cmd"]
    assert "--auto-approve" in captured["cmd"]
    assert "-P" in captured["cmd"]
    assert "openai-compatible" in captured["cmd"]
    assert "-m" in captured["cmd"]
    assert "coder" in captured["cmd"]
    assert "--compaction" in captured["cmd"]
    assert "agentic" in captured["cmd"]
    # data_dir 默认 None → 不应加 --data-dir
    assert "--data-dir" not in captured["cmd"]
    # 任务串追加在末尾
    assert captured["cmd"][-1] == "fix the bug"
    # subprocess timeout = timeout + 60
    assert captured["timeout"] == 70

    # 返回结构
    assert result["ok"] is True
    assert result["summary"]["tool_calls"] == 1
    assert result["summary"]["tools_used"] == ["editor"]
    assert result["summary"]["iterations"] == 1
    assert result["summary"]["reason"] == "completed"
    assert result["summary"]["exit_code"] == 0
    assert len(result["records"]) == 3  # tool_call + tool_result + done


def test_run_and_observe_with_data_dir_and_audit_path(monkeypatch, tmp_path: Path):
    """data_dir + audit_path 双参路径都应被走通。"""
    captured = {}

    def fake_run(cmd, capture_output, text, timeout):
        captured["cmd"] = cmd
        return _fake_completed_process(
            '{"ts":"t","type":"agent_event","event":{"type":"done","reason":"completed","iterations":0}}',
            returncode=0,
        )

    monkeypatch.setattr("driving.observe.subprocess.run", fake_run)
    audit = tmp_path / "audit" / "trail.jsonl"

    result = run_and_observe(
        "do thing",
        str(tmp_path),
        model="architect",
        data_dir="/tmp/cline-data",
        timeout=5,
        audit_path=str(audit),
        compaction="basic",
    )

    # data_dir 注入命令
    assert "--data-dir" in captured["cmd"]
    assert "/tmp/cline-data" in captured["cmd"]
    # compaction 透传
    idx_comp = captured["cmd"].index("--compaction")
    assert captured["cmd"][idx_comp + 1] == "basic"
    # model 透传
    idx_m = captured["cmd"].index("-m")
    assert captured["cmd"][idx_m + 1] == "architect"
    # audit 文件落盘
    assert audit.exists()
    assert "done" in audit.read_text()
    # 返回 ok
    assert result["ok"] is True
    assert result["summary"]["exit_code"] == 0


def test_run_and_observe_nonzero_returncode_marks_not_ok(monkeypatch, tmp_path: Path):
    """cline 退出码非 0 时 ok 应为 False，exit_code 透传到 summary。"""
    monkeypatch.setattr(
        "driving.observe.subprocess.run",
        lambda cmd, capture_output, text, timeout: _fake_completed_process("", returncode=2),
    )
    result = run_and_observe("broken task", str(tmp_path), timeout=5)
    assert result["ok"] is False
    assert result["summary"]["exit_code"] == 2


if __name__ == "__main__":
    test_parse_tool_events()
    test_ignores_non_agent_events()
    test_summarize()
    test_empty()
    print("observe 单测: 全部通过 ✅")
