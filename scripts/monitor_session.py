#!/usr/bin/env python3
"""M89 监控脚本:轮询会话事件,追加摘要到 TEST_LOG.md。
后台跑:python3 scripts/monitor_session.py sess-3dd52408 &
每 15 秒查一次,只追加新事件摘要,控制输出量。
"""
import json, sys, time, urllib.request, datetime

SESS = sys.argv[1] if len(sys.argv) > 1 else "sess-3dd52408"
BASE = "http://127.0.0.1:8011/api/v1"
LOG = "/Users/wangzhenyu/Desktop/ALLProject/flipped/TEST_LOG.md"
LAST_ID = None
seen = set()

def ts():
    return datetime.datetime.now().strftime("%H:%M:%S")

def fetch(path):
    try:
        with urllib.request.urlopen(f"{BASE}{path}", timeout=8) as r:
            return json.loads(r.read())
    except Exception as e:
        return {"_err": str(e)}

def summary(e):
    et = e.get("type", "?")
    ag = e.get("agent", "?")
    p = e.get("payload", {})
    if et == "status":
        return f"[{ts()}][status] {ag}: {p.get('note','')[:120]}"
    if et == "message":
        txt = p.get("text", "")[:160].replace("\n", " ")
        return f"[{ts()}][msg] {ag}: {txt}"
    if et == "plan":
        steps = p.get("steps", [])
        head = "; ".join(s.get("title", s.get("desc",""))[:40] for s in steps[:5])
        return f"[{ts()}][plan] {ag}: {len(steps)} steps | {head}"
    if et == "tool_call":
        return f"[{ts()}][tool] {ag}: {p.get('tool','?')[:80]}"
    if et == "tool_result":
        ok = p.get("ok", "?")
        out = str(p.get("output",""))[:80].replace("\n"," ")
        return f"[{ts()}][result] {ag}: ok={ok} {out}"
    if et == "checkpoint":
        return f"[{ts()}][ckpt] {ag}: {p.get('note','')[:60]}"
    if et == "error":
        return f"[{ts()}][ERROR] {ag}: {str(p)[:200]}"
    if et == "file_change":
        return f"[{ts()}][file] {ag}: {p.get('path','?')[:80]} {p.get('action','?')}"
    return f"[{ts()}][{et}] {ag}: {str(p)[:100]}"

with open(LOG, "a") as f:
    f.write(f"\n\n--- M89 监控启动 {ts()} session={SESS} ---\n")

rounds = 0
while rounds < 480:  # 最多 2 小时
    s = fetch(f"/sessions/{SESS}")
    if "_err" in s:
        with open(LOG, "a") as f:
            f.write(f"[{ts()}] 状态查询失败: {s['_err']}\n")
        time.sleep(20)
        rounds += 1
        continue
    status = s.get("status", "?")
    events = fetch(f"/sessions/{SESS}/events")
    if "_err" in events:
        time.sleep(20)
        rounds += 1
        continue
    new = [e for e in events if e["id"] not in seen]
    if new:
        with open(LOG, "a") as f:
            for e in new:
                seen.add(e["id"])
                f.write(summary(e) + "\n")
    # 状态变更标记
    if status in ("done", "error", "review", "idle") and rounds > 0:
        with open(LOG, "a") as f:
            f.write(f"[{ts()}] === 会话状态变为 {status},监控退出 ===\n")
        break
    time.sleep(15)
    rounds += 1

with open(LOG, "a") as f:
    f.write(f"[{ts()}] === 监控结束(rounds={rounds}) ===\n")
