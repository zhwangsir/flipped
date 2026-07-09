#!/usr/bin/env python3
"""盯 exo 集群从 502 恢复。

模型一旦可服务，就自动跑工具调用验证(M0.4)并把结果追加到 TEST_LOG.md。
两模型都验完或达到轮询上限即退出。设计为后台运行 (run_in_background)。
"""
import json
import os
import time
import datetime
import urllib.request

ENDPOINT = "http://100.64.201.37:52415/v1/chat/completions"
PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG = os.path.join(PROJECT, "TEST_LOG.md")

MODELS = [
    ("GLM-5.2 (编排者)", "mlx-community/GLM-5.2-fp8"),
    ("Kimi-K2.7-Code (执行者)", "mlx-community/Kimi-K2.7-Code-4bit"),
]
MAX_ITERS = int(os.environ.get("MONITOR_MAX_ITERS", "30"))   # 上限，防止失控空转 (AGENTS.md §6)
SLEEP_SECS = int(os.environ.get("MONITOR_SLEEP", "120"))


def now() -> str:
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def post(payload: dict, timeout: int = 240) -> dict:
    req = urllib.request.Request(
        ENDPOINT, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def is_serveable(model: str) -> bool:
    """轻量就绪探针：纯聊天。"""
    try:
        post({"model": model, "messages": [{"role": "user", "content": "hi"}],
              "max_tokens": 4, "temperature": 0})
        return True
    except Exception:
        return False


def toolcall_test(model: str):
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": "What is the weather in Tokyo? Use the get_weather tool."}],
        "tools": [{"type": "function", "function": {
            "name": "get_weather",
            "description": "Get current weather for a city",
            "parameters": {"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]},
        }}],
        "tool_choice": "auto", "max_tokens": 256, "temperature": 0,
    }
    try:
        data = post(payload)
        msg = data["choices"][0]["message"]
        tc = msg.get("tool_calls")
        if tc:
            fn = tc[0].get("function", {})
            return True, f"tool_calls OK -> {fn.get('name')}({fn.get('arguments')})"
        content = (msg.get("content") or "")[:200]
        leaked = ("get_weather" in content) or ("tool_call" in content.lower())
        suffix = "  ⚠ content 内疑似泄漏未解析的工具调用" if leaked else ""
        return False, f"无 tool_calls; content={content!r}{suffix}"
    except Exception as e:  # noqa: BLE001
        return False, f"请求失败 {type(e).__name__}: {e}"


def append_log(text: str) -> None:
    with open(LOG, "a") as f:
        f.write(text)


def main() -> None:
    append_log(f"\n## [{now()}] 集群恢复监控启动\n轮询 {ENDPOINT}，每 {SLEEP_SECS}s，最多 {MAX_ITERS} 次。\n")
    validated: dict[str, tuple[bool, str]] = {}

    for i in range(1, MAX_ITERS + 1):
        for label, model in MODELS:
            if model in validated:
                continue
            if is_serveable(model):
                ok, detail = toolcall_test(model)
                validated[model] = (ok, detail)
                status = "✅ 通过" if ok else "❌ 未通过"
                append_log(f"\n### [{now()}] 第{i}轮 — {label} 可服务，工具调用验证：{status}\n- {detail}\n")
        if len(validated) == len(MODELS):
            break
        time.sleep(SLEEP_SECS)

    if len(validated) == len(MODELS):
        all_ok = all(v[0] for v in validated.values())
        verdict = ("✅ 两模型工具调用均通过 — M0 架构验证成立 (M0.4 可标 done)"
                   if all_ok else
                   "❌ 有模型工具调用未通过 — 需在驾驭层加结构化输出约束与重试(见 M2)")
        append_log(f"\n### [{now()}] 监控结束：{verdict}\n")
    else:
        pending = [m for _, m in MODELS if m not in validated]
        append_log(f"\n### [{now()}] 监控结束：达 {MAX_ITERS} 次上限仍不可服务({pending})，集群未恢复，需人工介入。\n")


if __name__ == "__main__":
    main()
