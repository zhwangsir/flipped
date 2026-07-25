"""M149.19 对照实验：think 工具是否是 arg_key/name 碎片触发器。

背景：实例重启后探针 3/3"通过"，但工具 name 字段仍含
`thought</arg_key><arg_value>` 模板碎片——且总是出现在 think 调用上，
terminal 调用始终干净。exo 侧 tool_call 解析器对 think schema 可能脆弱。

本脚本对同一 prompt 分别用 [terminal+finish+think] 与 [terminal+finish]
两组工具各打 3 轮，严格判定：name 必须 ∈ 工具白名单、args 必须是合法 JSON、
args 键 ⊆ schema properties、content 无 think 泄漏。

用法: PYTHONPATH=src .venv/bin/python scripts/debug_glm_think_bisect.py
"""
import json
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from executor.openhands_worker import OpenHandsWorker  # noqa: E402
from debug_glm_replay_oh_real import USER_MSG  # noqa: E402

for raw in (ROOT / ".env").read_text().splitlines():
    line = raw.strip()
    if line and not line.startswith("#") and "=" in line:
        k, _, v = line.partition("=")
        if k.strip() == "LITELLM_MASTER_KEY":
            KEY = v.strip().strip('"').strip("'")
            break

SP = OpenHandsWorker._COMPACT_SYSTEM_PROMPT

tap = json.loads(Path("/tmp/llm_tap_body_1784826671.json").read_text())
ALL = {t["function"]["name"]: t for t in tap["tools"]}

# 每个工具的合法参数键（从 schema properties 提取）
VALID_KEYS = {
    name: set(t["function"].get("parameters", {}).get("properties", {}).keys())
    for name, t in ALL.items()
}


def run_group(label: str, names: list[str]) -> int:
    tools = [ALL[n] for n in names]
    whitelist = set(names)
    payload = {
        "model": "coder",
        "messages": [
            {"role": "system", "content": SP},
            {"role": "user", "content": USER_MSG},
        ],
        "tools": tools,
        "temperature": 0,
        "stream": False,
    }
    tool_chars = len(json.dumps(tools, ensure_ascii=False))
    print(f"[group {label}] tools={names} schema={tool_chars}ch", flush=True)
    fails = 0
    for trial in range(1, 4):
        req = urllib.request.Request(
            "http://localhost:4000/v1/chat/completions",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {KEY}"},
            method="POST")
        t0 = time.monotonic()
        try:
            with urllib.request.urlopen(req, timeout=300) as resp:
                data = json.loads(resp.read())
        except Exception as exc:
            print(f"  t{trial}: TIMEOUT/ERR {type(exc).__name__} "
                  f"({time.monotonic()-t0:.0f}s)", flush=True)
            fails += 1
            continue
        dt = time.monotonic() - t0
        ch = data["choices"][0]
        msg = ch["message"]
        content = msg.get("content") or ""
        reasoning = msg.get("reasoning_content") or ""
        tcs = msg.get("tool_calls") or []
        problems = []
        for tc in tcs:
            fn = tc.get("function", {})
            name = fn.get("name", "")
            if name not in whitelist:
                problems.append(f"name!={name[:40]!r}")
            try:
                args = json.loads(fn.get("arguments", ""))
                bad = set(args.keys()) - VALID_KEYS.get(name, set())
                if bad:
                    problems.append(f"arg_keys{bad}")
            except Exception:
                problems.append("args_json_broken")
        if ("</think>" in content) or reasoning:
            problems.append("think_leak")
        if not tcs:
            problems.append("no_tool_call")
        verdict = "OK" if not problems else f"BAD({','.join(problems)})"
        if problems:
            fails += 1
        names_seen = [tc["function"]["name"][:30] for tc in tcs]
        print(f"  t{trial}: {dt:.0f}s tc={len(tcs)} names={names_seen} [{verdict}]",
              flush=True)
    return fails


f_a = run_group("with-think", ["terminal", "finish", "think"])
f_b = run_group("no-think", ["terminal", "finish"])
print(f"[result] with-think fails={f_a}/3  no-think fails={f_b}/3", flush=True)
sys.exit(0 if (f_a + f_b) == 0 else 1)
