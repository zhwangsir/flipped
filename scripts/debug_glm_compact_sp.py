"""M149.16 新配置探针：worker 精简 SP + 精简 tools（terminal/finish/think）
直发代理，验证第一轮输出干净且远快于超时。

用法: PYTHONPATH=src .venv/bin/python scripts/debug_glm_compact_sp.py
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

# 从 tap 捕获的真实 SDK schema 提取 terminal/finish/think
tap = json.loads(Path("/tmp/llm_tap_body_1784826671.json").read_text())
KEEP = {"terminal", "finish", "think"}
TOOLS = [t for t in tap["tools"] if t["function"]["name"] in KEEP]

payload = {
    "model": "coder",
    "messages": [
        {"role": "system", "content": SP},
        {"role": "user", "content": USER_MSG},
    ],
    "tools": TOOLS,
    "temperature": 0,
    "stream": False,
}
msg_chars = sum(len(json.dumps(m, ensure_ascii=False)) for m in payload["messages"])
tool_chars = len(json.dumps(TOOLS, ensure_ascii=False))
total = msg_chars + tool_chars
print(f"[probe] SP={len(SP)}ch user={len(USER_MSG)}ch tools({len(TOOLS)})={tool_chars}ch 总={total}ch "
      f"(窗口余量 ~{14500 - total}ch)", flush=True)

fails = 0
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
        fails += 1
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
    # M149.17 判定修正：content 为空 + tool_call JSON 有效 = 正常（纯工具调用无文本）。
    # 乱码的真实特征是有文本但 alpha 低 / think 泄漏 / tc JSON 破碎。
    text_ok = (alpha > 0.3) if content else True
    verdict = "OK" if (tcs and json_ok == len(tcs) and not think_leak and text_ok) else "GARBAGE"
    if verdict != "OK":
        fails += 1
    print(f"--- trial {trial}: {dt:.0f}s finish={ch.get('finish_reason')} "
          f"usage={usage.get('prompt_tokens')}->{usage.get('completion_tokens')} "
          f"tc={len(tcs)} json_ok={json_ok} alpha={alpha:.2f} think_leak={think_leak} [{verdict}]", flush=True)
    print(f"    content[:120]: {content[:120]!r}", flush=True)
    if tcs:
        print(f"    tc0: {tcs[0]['function']['name']} args[:100]: {tcs[0]['function']['arguments'][:100]!r}", flush=True)

print(f"[probe] 结果: {3 - fails}/3 通过", flush=True)
sys.exit(1 if fails else 0)
