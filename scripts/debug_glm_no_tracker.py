"""M149.16 快速探针：用 tap 捕获的真实 worker payload，删 task_tracker 后直发代理，
验证第一轮输出是否干净（不跑完整 worker，30-60s 出结果）。

用法: .venv/bin/python scripts/debug_glm_no_tracker.py
"""
import json
import time
import urllib.request
from pathlib import Path

TAP_BODY = Path("/tmp/llm_tap_body_1784826671.json")

# 读 .env 的 LITELLM_MASTER_KEY
for raw in Path(".env").read_text().splitlines():
    line = raw.strip()
    if line and not line.startswith("#") and "=" in line:
        k, _, v = line.partition("=")
        if k.strip() == "LITELLM_MASTER_KEY":
            KEY = v.strip().strip('"').strip("'")
            break

payload = json.loads(TAP_BODY.read_text())
tools_before = [t["function"]["name"] for t in payload["tools"]]
payload["tools"] = [t for t in payload["tools"] if t["function"]["name"] != "task_tracker"]
tools_after = [t["function"]["name"] for t in payload["tools"]]

msg_chars = sum(len(json.dumps(m, ensure_ascii=False)) for m in payload["messages"])
tool_chars = len(json.dumps(payload["tools"], ensure_ascii=False))
print(f"[probe] tools: {tools_before} -> {tools_after}", flush=True)
print(f"[probe] messages={msg_chars}ch tools={tool_chars}ch 总={msg_chars + tool_chars}ch", flush=True)

for trial in range(1, 4):
    req = urllib.request.Request(
        "http://localhost:4000/v1/chat/completions",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {KEY}"},
        method="POST")
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            data = json.loads(resp.read())
    except Exception as exc:
        print(f"--- trial {trial}: TIMEOUT/ERR {type(exc).__name__} ({time.monotonic()-t0:.0f}s)", flush=True)
        continue
    dt = time.monotonic() - t0
    ch = data["choices"][0]
    msg = ch["message"]
    content = msg.get("content") or ""
    reasoning = msg.get("reasoning_content") or ""
    tcs = msg.get("tool_calls") or []
    usage = data.get("usage") or {}
    alpha = sum(c.isalpha() for c in content) / max(len(content), 1)
    json_ok = 0
    for tc in tcs:
        try:
            json.loads(tc["function"]["arguments"])
            json_ok += 1
        except Exception:
            pass
    think_leak = ("</think>" in content) or bool(reasoning)
    verdict = "OK" if (tcs and json_ok == len(tcs) and not think_leak and alpha > 0.3) else "GARBAGE"
    print(f"--- trial {trial}: {dt:.0f}s finish={ch.get('finish_reason')} "
          f"usage={usage.get('prompt_tokens')}->{usage.get('completion_tokens')} "
          f"tc={len(tcs)} json_ok={json_ok} alpha={alpha:.2f} think_leak={think_leak} [{verdict}]", flush=True)
    print(f"    content[:120]: {content[:120]!r}", flush=True)
    if tcs:
        print(f"    tc0: {tc['function']['name']} args[:100]: {tcs[0]['function']['arguments'][:100]!r}", flush=True)
