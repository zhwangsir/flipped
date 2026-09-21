"""测量 GLM-5.2-fp8 在不同 prompt 规模下的首 token 延迟（直连 exo, stream）。"""
import json
import sys
import time
import urllib.request

# M192: 主机名漂移跟进——dgmt-studio01mac-studio（旧名 studio01-1 已失效）
EXO = "http://dgmt-studio01mac-studio:52415/v1/chat/completions"

n_repeat = int(sys.argv[1]) if len(sys.argv) > 1 else 100  # 100 ≈ 3k tokens
filler = (
    "You are an autonomous software engineer agent. You must use tools to "
    "complete tasks. Follow safety rules. Always verify your work. "
) * n_repeat

payload = {
    "model": "mlx-community/GLM-5.2-fp8",
    "messages": [
        {"role": "system", "content": filler},
        {"role": "user", "content": "Reply with exactly: OK"},
    ],
    "temperature": 0,
    "max_tokens": 4,
    "stream": True,
    "extra_body": {
        "enable_thinking": False,
        "chat_template_kwargs": {"enable_thinking": False},
    },
}

req = urllib.request.Request(EXO, data=json.dumps(payload).encode(),
                             headers={"Content-Type": "application/json"})
t0 = time.monotonic()
est_tokens = n_repeat * 30
print(f"[{time.strftime('%H:%M:%S')}] ~{est_tokens} tokens prompt 发送...", flush=True)
first = None
chunks = 0
try:
    with urllib.request.urlopen(req, timeout=600) as r:
        for raw in r:
            line = raw.decode("utf-8", "replace").strip()
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            chunks += 1
            if first is None:
                first = time.monotonic()
                print(f"[首 token] {first - t0:.1f}s  (≈{est_tokens / (first - t0):.0f} tok/s prefill)", flush=True)
            try:
                d = json.loads(data)
                piece = d["choices"][0].get("delta", {}).get("content") or ""
                if piece:
                    print(f"  content: {piece!r}", flush=True)
            except Exception:
                pass
    print(f"[完成] chunks={chunks} 总 {time.monotonic() - t0:.1f}s", flush=True)
except Exception as exc:
    print(f"[失败] {time.monotonic() - t0:.1f}s: {type(exc).__name__}: {exc}", flush=True)
