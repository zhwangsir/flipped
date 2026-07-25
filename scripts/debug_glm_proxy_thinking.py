"""M149.15 决定性探针：请求体不带 extra_body，验证 LiteLLM config 的
extra_body(enable_thinking=false) 是否真正注入到 exo 上游。

- 若代理注入生效 → 输出干净（无 think 碎片、JSON tool_calls 有效）
- 若注入失效 → thinking 模板默认开启 → 乱码（M149.6 结论：thinking on 必乱码）

用法: .venv/bin/python scripts/debug_glm_proxy_thinking.py
"""
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

# 复用真实 SP 捕获文件（debug_glm_replay_oh_real.py 同款来源）
sys.path.insert(0, str(Path(__file__).parent))
from debug_glm_replay_oh_real import SP, TOOLS, USER_MSG, LITELLM, KEY  # noqa: E402

# 关键差异：payload 不带 extra_body —— 唯一思考控制来源是代理 config 注入
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
total_chars = sum(len(json.dumps(m, ensure_ascii=False)) for m in payload["messages"])
print(f"[probe] total_context={total_chars}ch, extra_body=ABSENT (仅依赖代理注入)", flush=True)

for trial in range(1, 4):
    req = urllib.request.Request(
        LITELLM, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {KEY}"},
        method="POST")
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
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
    alpha = sum(c.isalpha() for c in content) / max(len(content), 1)
    json_ok = 0
    for tc in tcs:
        try:
            json.loads(tc["function"]["arguments"])
            json_ok += 1
        except Exception:
            pass
    think_leak = ("</think>" in content) or ("<think>" in content) or bool(reasoning)
    verdict = "OK" if (tcs and json_ok == len(tcs) and not think_leak and alpha > 0.3) else "GARBAGE/THINK"
    print(f"--- trial {trial}: {dt:.1f}s finish={ch.get('finish_reason')} "
          f"tc={len(tcs)} json_ok={json_ok} content_len={len(content)} "
          f"reasoning_len={len(reasoning)} alpha={alpha:.2f} think_leak={think_leak} [{verdict}]", flush=True)
    if verdict != "OK":
        print(f"    content[:160]: {content[:160]!r}", flush=True)
        if tcs:
            print(f"    tc0 args[:160]: {tcs[0]['function']['arguments'][:160]!r}", flush=True)
