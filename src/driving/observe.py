"""驾驭层 · 可观测（D9 / M3.2）。

解析 Cline CLI `--json` 事件流，抽取结构化轨迹（每步工具调用：名/入参/输出/耗时）。

为何走流解析而非文件 hook：实测 cline CLI v3.0.33 的 `--hooks-dir` **不执行**外部文件 hook
（虽内部 emit hook_event）。但 `--json` 流里 content_start/content_end(contentType=tool)
带 toolName/input/output/durationMs，是可靠的可观测来源；C 侧(LangGraph)驱动 cline headless
时本就读这个流。详见 docs/research-cline-hooks-driving-layer.md。

parse_events 是纯函数（可单测）；run_and_observe 包一次 cline 运行（C 侧驱动用）。
"""
from __future__ import annotations

import json
import os
import subprocess


def parse_events(lines) -> list[dict]:
    """从 cline --json 输出(可迭代的行)抽取结构化记录。

    返回 [{kind, ...}]，kind ∈ tool_call/tool_result/iteration/usage/done。
    """
    out: list[dict] = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            d = json.loads(line)
        except Exception:
            continue
        if d.get("type") != "agent_event":
            continue
        ev = d.get("event", {}) or {}
        t = ev.get("type")
        ts = d.get("ts")
        ctype = ev.get("contentType")
        if t == "content_start" and ctype == "tool":
            out.append({"kind": "tool_call", "ts": ts, "tool": ev.get("toolName"),
                        "id": ev.get("toolCallId"), "input": ev.get("input")})
        elif t == "content_end" and ctype == "tool":
            out.append({"kind": "tool_result", "ts": ts, "tool": ev.get("toolName"),
                        "id": ev.get("toolCallId"), "output": ev.get("output"),
                        "durationMs": ev.get("durationMs")})
        elif t == "iteration_end":
            out.append({"kind": "iteration", "ts": ts, "iteration": ev.get("iteration"),
                        "toolCallCount": ev.get("toolCallCount"), "hadToolCalls": ev.get("hadToolCalls")})
        elif t == "usage":
            out.append({"kind": "usage", "ts": ts, "inputTokens": ev.get("inputTokens"),
                        "outputTokens": ev.get("outputTokens"), "totalCost": ev.get("totalCost")})
        elif t == "done":
            out.append({"kind": "done", "ts": ts, "reason": ev.get("reason"),
                        "iterations": ev.get("iterations"), "text": (ev.get("text") or "")[:1000]})
    return out


def summarize(records: list[dict]) -> dict:
    """把结构化记录汇总成一行概览。"""
    calls = [r for r in records if r["kind"] == "tool_call"]
    done = next((r for r in records if r["kind"] == "done"), None)
    return {
        "tool_calls": len(calls),
        "tools_used": sorted({r["tool"] for r in calls if r.get("tool")}),
        "iterations": done.get("iterations") if done else None,
        "reason": done.get("reason") if done else None,
    }


def write_audit(records: list[dict], path: str) -> None:
    """结构化轨迹落 JSONL（可观测归档；C 侧可再入 checkpoint）。"""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def run_and_observe(task: str, cwd: str, *, model: str = "coder",
                    data_dir: str | None = None, timeout: int = 280,
                    audit_path: str | None = None, compaction: str = "agentic") -> dict:
    """驱动一次 cline headless 并解析其 --json 流，返回 {summary, records, ok}。

    C 侧 LangGraph 节点用它把 Cline 当执行器：跑任务 + 拿到可追溯轨迹。
    compaction：用 Cline 原生上下文压缩（Auto Compact，D9/D11，零自研）。agentic|basic|off。
    """
    cmd = ["cline", "--json", "--auto-approve", "true", "-P", "openai-compatible",
           "-m", model, "-c", cwd, "--timeout", str(timeout), "--compaction", compaction]
    if data_dir:
        cmd += ["--data-dir", data_dir]
    cmd.append(task)
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 60)
    records = parse_events(proc.stdout.splitlines())
    if audit_path:
        write_audit(records, audit_path)
    summary = summarize(records)
    summary["exit_code"] = proc.returncode
    return {"summary": summary, "records": records, "ok": proc.returncode == 0}


if __name__ == "__main__":
    import sys
    src = open(sys.argv[1]) if len(sys.argv) > 1 else sys.stdin
    recs = parse_events(src)
    print(json.dumps(summarize(recs), ensure_ascii=False))
    for r in recs:
        if r["kind"] in ("tool_call", "tool_result"):
            print(f"  {r['kind']:11s} {r.get('tool')} dur={r.get('durationMs','')}")
