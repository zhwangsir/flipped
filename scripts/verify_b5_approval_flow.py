import asyncio
import json
import os
import sys

import httpx
import websockets


API_URL = os.environ.get("API_URL", "http://127.0.0.1:8001")
WS_URL = API_URL.replace("http://", "ws://")


def http(path, method="GET", json=None):
    r = httpx.request(method, f"{API_URL}{path}", json=json, timeout=10)
    r.raise_for_status()
    return r.json()


async def run_approval_flow(decision: str, expected_status: str, expect_error: bool):
    sess = http("/api/v1/sessions?title=B5%20Approval", "POST")
    sid = sess["id"]
    http(f"/api/v1/sessions/{sid}/tasks", "POST", {"description": "create app.py and test it"})

    events = []
    async with websockets.connect(f"{WS_URL}/api/v1/sessions/{sid}/events", proxy=None) as ws:
        got_approval = False
        deadline = asyncio.get_event_loop().time() + 15.0
        while asyncio.get_event_loop().time() < deadline:
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=1.0)
                ev = json.loads(msg)
                events.append(ev)
                if ev.get("type") == "approval_request":
                    got_approval = True
                    break
            except asyncio.TimeoutError:
                pass

        if not got_approval:
            print(f"FAIL ({decision}): did not receive approval_request", file=sys.stderr)
            print("events:", events, file=sys.stderr)
            sys.exit(2)

        await ws.send(json.dumps({"type": "approval_result", "decision": decision, "reason": "fallback e2e"}))

        done = False
        deadline = asyncio.get_event_loop().time() + 20.0
        while asyncio.get_event_loop().time() < deadline:
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=1.0)
                ev = json.loads(msg)
                events.append(ev)
                if ev.get("type") == "status" and ev.get("payload", {}).get("status") == expected_status:
                    done = True
                    break
            except asyncio.TimeoutError:
                pass

        if not done:
            print(f"FAIL ({decision}): did not reach status {expected_status}", file=sys.stderr)
            print("events:", events, file=sys.stderr)
            sys.exit(3)

    error_events = [e for e in events if e.get("type") == "error"]
    if expect_error and not error_events:
        print(f"FAIL ({decision}): expected error event but got none", file=sys.stderr)
        sys.exit(4)
    if not expect_error and error_events:
        print(f"FAIL ({decision}): unexpected error events", error_events, file=sys.stderr)
        sys.exit(5)

    print(f"OK ({decision}): status={expected_status}, events={len(events)}, error_events={len(error_events)}")


async def main():
    await run_approval_flow("approve", "done", expect_error=False)
    await run_approval_flow("reject", "review", expect_error=True)
    print("PASS: B5 approval flow backend E2E")


if __name__ == "__main__":
    asyncio.run(main())
