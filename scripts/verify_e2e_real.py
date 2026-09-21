"""M6.5 真实端到端验证器(非 mock)。

flipped OpenHandsWorker → 真实 OpenHands agent-server 沙盒 → 真实本地模型 → 真实文件 + 执行。
需要:agent-server 运行(默认 :8000)、exo 模型在线、Docker。本机真机跑(无 ISSUE-6 TCP 限制)。

用法:
  PYTHONPATH=src .venv/bin/python scripts/verify_e2e_real.py
环境变量(均有默认):
  OH_AGENT_HOST   agent-server 地址(默认 http://localhost:8000)
  OH_BASE_URL     模型端点(默认 exo 直连 http://dgmt-studio01mac-studio:52415/v1)
  OH_MODEL        模型 id(默认 mlx-community/GLM-5.2-fp8)
退出码 0=PASS,2=FAIL。
"""
import os
import sys

os.environ.setdefault("NO_PROXY", "dgmt-studio01mac-studio,.ts.net,localhost,127.0.0.1,::1")
os.environ["no_proxy"] = os.environ["NO_PROXY"]
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

AGENT_HOST = os.environ.get("OH_AGENT_HOST", "http://localhost:8000")
BASE_URL = os.environ.get("OH_BASE_URL", "http://dgmt-studio01mac-studio:52415/v1")
MODEL = os.environ.get("OH_MODEL", "mlx-community/GLM-5.2-fp8")


class _CollectingBus:
    def __init__(self):
        self.events = []

    def emit(self, sid, type_, agent, payload, parent_id=None):
        self.events.append((str(type_), payload))
        brief = (payload.get("note") or payload.get("summary") or payload.get("text")
                 or payload.get("command") or payload.get("path") or payload.get("message") or "")
        print(f"  · {str(type_):18} {str(agent):12} {str(brief)[:96]}", flush=True)

    def set_status(self, sid, status):
        print(f"  ===> session status: {status}", flush=True)


def main() -> int:
    from executor.openhands_worker import OpenHandsWorker

    key_file = os.path.expanduser("~/.openhands/agent-canvas/api-key.txt")
    api_key = open(key_file).read().strip() if os.path.exists(key_file) else os.environ.get("OPENHANDS_API_KEY", "")
    bus = _CollectingBus()
    print(f"== M6.5 real E2E · agent-server={AGENT_HOST} model={MODEL} @ {BASE_URL} ==", flush=True)
    worker = OpenHandsWorker(
        "e2e-sess", "e2e-task", bus,
        agent_host=AGENT_HOST, working_dir="/workspace",
        model_alias=MODEL, base_url=BASE_URL, api_key=api_key, timeout=280,
    )
    try:
        res = worker.run(
            "Create a file named hello.py in the current directory that defines a function add(a, b) "
            "returning a + b, and ends with: if __name__ == '__main__': print(add(2, 3)). "
            "Then run `python3 hello.py` and confirm the output is 5."
        )
    except Exception as exc:  # noqa: BLE001
        print(f"\n== FAIL == {type(exc).__name__}: {str(exc)[:300]}", flush=True)
        return 2

    finished = res.get("status", "").endswith("FINISHED")
    # M199 跟进：agent 可能用 terminal  heredoc/printf 建文件（无 file_change 事件），
    # 此时以「terminal 命令写 hello.py」作为创建证据；file editor 路径仍认 file_change。
    made_file = any(
        t.endswith("file_change") and "hello" in (p.get("path") or "") for t, p in bus.events
    ) or any(
        t.endswith("terminal") and "hello.py" in (p.get("command") or "")
        and (">" in (p.get("command") or "") or "tee" in (p.get("command") or ""))
        for t, p in bus.events
    )
    ran_ok = any(t.endswith("tool_result") and p.get("tool") == "terminal" and p.get("status") == "ok"
                 for t, p in bus.events)
    ok = finished and made_file and ran_ok
    print(f"\n== RESULT == {res}", flush=True)
    print(f"finished={finished} hello.py_created={made_file} terminal_ok={ran_ok}", flush=True)
    print("VERDICT:", "PASS" if ok else "FAIL", flush=True)
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())
