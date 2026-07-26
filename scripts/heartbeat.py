#!/usr/bin/env python3
"""heartbeat.py · 开发进度心跳监控（每 10 分钟触发）。

扫描维度：
1. STATE.json 当前里程碑 + 子任务状态
2. git 状态（最近 commit 年龄、未提交改动、当前分支）
3. 模型就绪探针（GLM-5.2-fp8 / Kimi-K2.7-Code-4bit，只读 ping）
4. 测试基线（最近 quality_metrics.json）
5. 进度偏差（计划 vs 实际）

产出：
- reports/heartbeat_YYYYMMDD_HHMM.md（单次报告）
- reports/heartbeat.log（追加摘要行）
- reports/heartbeat_history.jsonl（结构化历史，供趋势分析）

不改动任何代码/配置/模型——纯只读监控。
"""
from __future__ import annotations
import json
import os
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)

# 让 scripts/ 入口能 import src/driving 业务模块（factory_health 等）
sys.path.insert(0, os.path.join(ROOT, "src"))

from driving.factory_health import detect_stuck_factories  # noqa: E402
from driving.auto_resume import maybe_auto_resume  # noqa: E402

REPORTS_DIR = os.path.join(ROOT, "reports")
os.makedirs(REPORTS_DIR, exist_ok=True)

# 加载 .env（模型探针用）
ENV_PATH = os.path.join(ROOT, ".env")
if os.path.exists(ENV_PATH):
    for line in open(ENV_PATH):
        line = line.strip()
        if line.startswith("EXO_API_KEY="):
            os.environ["EXO_API_KEY"] = line.split("=", 1)[1]
os.environ["NO_PROXY"] = f"studio01-1,localhost,127.0.0.1,::1,.local,{os.environ.get('NO_PROXY','')}"

EXO_URL = "http://studio01-1:52415/v1/chat/completions"
EXO_KEY = os.environ.get("EXO_API_KEY", "")


def ts() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M")


def ts_human() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def scan_state() -> dict:
    """扫描 STATE.json 提取当前里程碑 + 阻塞项。"""
    try:
        d = json.load(open("STATE.json"))
    except Exception as e:
        return {"error": f"读 STATE.json 失败: {e}"}
    ms = d.get("milestones", {})
    doing = []
    blocked = []
    done_count = 0
    todo_count = 0
    for mid, m in ms.items():
        if isinstance(m, dict):
            st = m.get("status", "?")
        else:
            st = str(m)
        if st == "doing":
            doing.append({"id": mid, "title": m.get("title", "")[:100] if isinstance(m, dict) else ""})
        elif st == "blocked":
            blocked.append({"id": mid, "title": m.get("title", "")[:80] if isinstance(m, dict) else ""})
        elif st == "done":
            done_count += 1
        elif st == "todo":
            todo_count += 1
    ki = d.get("known_issues", [])
    open_issues = [i for i in ki if isinstance(i, dict) and i.get("status") != "resolved"]
    return {
        "current_milestone": d.get("current_milestone", "")[:200],
        "doing": doing,
        "blocked": blocked,
        "done_count": done_count,
        "todo_count": todo_count,
        "total": len(ms),
        "open_issues": len(open_issues),
        "open_issue_ids": [i.get("id", "?") for i in open_issues],
    }


def scan_git() -> dict:
    """扫描 git 状态。"""
    def run(args):
        try:
            r = subprocess.run(args, capture_output=True, text=True, timeout=10, cwd=ROOT)
            return r.stdout.strip() if r.returncode == 0 else None
        except Exception:
            return None
    branch = run(["git", "rev-parse", "--abbrev-ref", "HEAD"])
    last_commit_ts = run(["git", "log", "-1", "--format=%ct"])
    last_commit_msg = run(["git", "log", "-1", "--format=%s"])
    status = run(["git", "status", "--porcelain"])
    dirty_count = len([l for l in status.split("\n") if l.strip()]) if status else 0
    commit_age_min = None
    if last_commit_ts:
        try:
            commit_age_min = int((time.time() - int(last_commit_ts)) / 60)
        except Exception:
            pass
    return {
        "branch": branch or "?",
        "last_commit": last_commit_msg[:80] if last_commit_msg else "?",
        "commit_age_min": commit_age_min,
        "dirty_files": dirty_count,
    }


def probe_model(model_id: str) -> dict:
    """只读探针模型就绪状态（max_tokens=1，最小开销，不扰动模型）。"""
    body = json.dumps({
        "model": model_id,
        "messages": [{"role": "user", "content": "1"}],
        "max_tokens": 1,
        "temperature": 0.0,
    }).encode()
    if "GLM-5.2" in model_id:
        body = json.dumps({
            "model": model_id,
            "messages": [{"role": "user", "content": "1"}],
            "max_tokens": 1,
            "temperature": 0.0,
            "enable_thinking": False,
            "chat_template_kwargs": {"enable_thinking": False},
        }).encode()
    req = urllib.request.Request(EXO_URL, data=body,
        headers={"Authorization": f"Bearer {EXO_KEY}", "Content-Type": "application/json"},
        method="POST")
    start = time.time()
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
        elapsed = time.time() - start
        return {"ready": True, "latency_s": round(elapsed, 1), "error": None}
    except Exception as e:
        err = str(e)[:80]
        # 区分 404（未加载）vs 超时（可能冷启动）vs 其他
        if "404" in err:
            return {"ready": False, "latency_s": round(time.time() - start, 1), "error": "404 未加载"}
        return {"ready": False, "latency_s": round(time.time() - start, 1), "error": err}


def scan_tests() -> dict:
    """读最近 quality_metrics.json + 历史趋势。"""
    metrics = {}
    if os.path.exists("quality_metrics.json"):
        try:
            metrics = json.load(open("quality_metrics.json"))
        except Exception:
            pass
    # 历史最近 3 轮
    history = []
    if os.path.exists("quality_metrics_history.jsonl"):
        for line in open("quality_metrics_history.jsonl").readlines()[-3:]:
            try:
                history.append(json.loads(line))
            except Exception:
                pass
    return {"latest": metrics, "recent_rounds": len(history)}


def compute_deviation(state: dict) -> dict:
    """计算进度偏差。"""
    total = state.get("total", 0)
    done = state.get("done_count", 0)
    doing = len(state.get("doing", []))
    blocked = len(state.get("blocked", []))
    # 简单偏差：如果 doing > 0 且 blocked > 0 → 高风险
    # 如果 doing > 0 且 0 blocked → 正常推进
    # 如果 doing == 0 → 可能需要选新里程碑
    risk = "low"
    notes = []
    if blocked > 0:
        risk = "high"
        notes.append(f"{blocked} 个里程碑阻塞")
    if doing == 0 and total > 0:
        risk = "medium" if risk == "low" else risk
        notes.append("无进行中里程碑，需选下一个")
    if state.get("open_issues", 0) > 0:
        notes.append(f"{state['open_issues']} 个未解决 known_issue")
    completion = round(done / max(1, total) * 100, 1)
    return {
        "completion_pct": completion,
        "risk_level": risk,
        "notes": notes or ["正常推进中"],
    }


def load_prev_model_state() -> dict:
    """读上一次心跳的模型状态（从 heartbeat_history.jsonl 最后一行）。
    M154.2：用于检测 Kimi 从 not ready → ready 的恢复事件。"""
    hist_path = os.path.join(REPORTS_DIR, "heartbeat_history.jsonl")
    if not os.path.exists(hist_path):
        return {}
    try:
        # 读最后几行（避免大文件全读）
        with open(hist_path, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - 8192))
            tail = f.read().decode("utf-8", errors="ignore").strip().split("\n")
        for line in reversed(tail):
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                if "models" in entry:
                    return entry["models"]
            except Exception:
                continue
    except Exception:
        pass
    return {}


def detect_recovery(models: dict, prev_models: dict) -> list:
    """M154.2：检测模型恢复事件（not ready → ready）。
    返回恢复事件列表，每个事件是 (model_id, prev_error, curr_latency)。
    首次运行（prev_models 为空）不触发恢复通知——无对比基准。"""
    if not prev_models:
        return []
    recoveries = []
    for mid, curr in models.items():
        prev = prev_models.get(mid, {})
        was_ready = prev.get("ready", False)
        is_ready = curr.get("ready", False)
        if not was_ready and is_ready:
            recoveries.append({
                "model": mid,
                "prev_error": prev.get("error", "未知"),
                "curr_latency_s": curr.get("latency_s"),
            })
    return recoveries


def write_recovery_notice(recoveries: list, now_ts: str, now_human: str) -> None:
    """M154.2：写模型恢复通知到 reports/recovery_*.md。"""
    if not recoveries:
        return
    notice_path = os.path.join(REPORTS_DIR, f"recovery_{now_ts}.md")
    with open(notice_path, "w") as f:
        f.write(f"# 模型恢复通知 · {now_human}\n\n")
        f.write(f"检测到以下模型从不可用转为可用（M154.2 自动检测）：\n\n")
        for r in recoveries:
            f.write(f"## ✅ {r['model']}\n\n")
            f.write(f"- **先前错误**: {r['prev_error']}\n")
            f.write(f"- **当前延迟**: {r['curr_latency_s']}s\n")
            f.write(f"- **恢复时间**: {now_human}\n\n")
        f.write(f"## 建议动作\n\n")
        f.write(f"- 如果是 Kimi-K2.7-Code-4bit 恢复：可考虑切回双模型架构（GLM 编排 + Kimi 执行），解除 M147/M149.3 阻塞\n")
        f.write(f"- 跑 `bash scripts/quality_gate.sh` 验证 tool-calling 契约\n")
        f.write(f"- 跑 `python3 scripts/e2e_m147_10tasks.py` 重试 E2E 10-task\n")
    # 控制台高亮输出
    print(f"  📢 检测到模型恢复事件 → {notice_path}")
    for r in recoveries:
        print(f"     ✅ {r['model']}: {r['prev_error']} → ready ({r['curr_latency_s']}s)")


def write_stuck_notice(stuck: list, now_ts: str, now_human: str) -> None:
    """M5 产线化 — 检测到卡住/可恢复工厂时写通知到 reports/stuck_*.md。

    只写建议动作，不自动执行 resume（安全：不扰动产线）。
    自动 resume 需 FLIPPED_HEARTBEAT_AUTO_RESUME=1 门控，另作实现。
    """
    if not stuck:
        return
    notice_path = os.path.join(REPORTS_DIR, f"stuck_{now_ts}.md")
    with open(notice_path, "w") as f:
        f.write(f"# 长任务健康告警 · {now_human}\n\n")
        f.write(f"检测到 {len(stuck)} 个工厂有风险信号（M5 主动监护）：\n\n")
        for s in stuck:
            f.write(f"## ⚠️ {s['factory_id']}\n\n")
            f.write(f"- **状态**: {s['status']}\n")
            f.write(f"- **目标**: {s.get('product_goal', '?')[:80]}\n")
            f.write(f"- **工作目录**: {s.get('cwd', '?')}\n")
            if s.get("minutes_since_update") is not None:
                f.write(f"- **上次更新**: {s['minutes_since_update']} 分钟前\n")
            f.write(f"- **信号**: {', '.join(s['signals'])}\n")
            if s.get("circuit_breaker_tasks"):
                f.write(f"- **可恢复任务**:\n")
                for cb in s["circuit_breaker_tasks"]:
                    f.write(f"  - `{cb['task_id']}` stop_reason={cb['stop_reason']} summary={cb.get('summary','')[:60]}\n")
            if s.get("running_tasks"):
                f.write(f"- **卡住的任务**: {', '.join(s['running_tasks'])}\n")
            f.write(f"\n")
        f.write(f"## 建议动作\n\n")
        f.write(f"- 检查对应 factory 的进程是否存活（`ps aux | grep factory`）\n")
        f.write(f"- 如有 circuit_breaker_task：可跑 `python3 scripts/resume_factory.py <factory_id>` 尝试恢复\n")
        f.write(f"- 如 stale_updated_at：检查是否有崩溃的 OpenHands 容器（`docker ps -a | grep flipped-oh`）\n")
        auto_on = os.environ.get("FLIPPED_HEARTBEAT_AUTO_RESUME", "") == "1"
        if auto_on:
            f.write(f"- ✅ 自动恢复已启用（FLIPPED_HEARTBEAT_AUTO_RESUME=1）：有 circuit_breaker_task 的工厂会被自动恢复\n")
        else:
            f.write(f"- 自动恢复未启用（FLIPPED_HEARTBEAT_AUTO_RESUME 默认关），需人工介入\n")
    # 控制台高亮输出
    print(f"  ⚠️ 检测到 {len(stuck)} 个卡住/可恢复工厂 → {notice_path}")
    for s in stuck:
        print(f"     ⚠️ {s['factory_id']}: {', '.join(s['signals'])}")


def main():
    now_ts = ts()
    now_human = ts_human()

    state = scan_state()
    git = scan_git()
    tests = scan_tests()
    deviation = compute_deviation(state)

    # M154.2：读上一次心跳的模型状态，用于恢复检测
    prev_models = load_prev_model_state()

    # 模型探针（只读，不扰动）
    models = {
        "GLM-5.2-fp8": probe_model("mlx-community/GLM-5.2-fp8"),
        "Kimi-K2.7-Code-4bit": probe_model("mlx-community/Kimi-K2.7-Code-4bit"),
    }

    # M154.2：检测恢复事件并写通知
    recoveries = detect_recovery(models, prev_models)
    write_recovery_notice(recoveries, now_ts, now_human)

    # M5 产线化：检测卡住/可恢复的工厂（主动监护）
    stuck = detect_stuck_factories(stale_minutes=30)
    write_stuck_notice(stuck, now_ts, now_human)

    # M158.4：门控自动恢复（FLIPPED_HEARTBEAT_AUTO_RESUME=1 时对 cb 工厂自动调 resume）
    auto_resume_results = maybe_auto_resume(
        stuck, now_ts=now_ts, now_human=now_human, reports_dir=REPORTS_DIR,
    )
    if auto_resume_results:
        print(f"  🔄 自动恢复 {len(auto_resume_results)} 个工厂（M158.4 门控）")
        for r in auto_resume_results:
            mark = "✓" if r.get("exit_code") == 0 else "⚠"
            print(f"     {mark} {r['factory_id']}: action={r['action']} exit={r.get('exit_code')}")

    report = {
        "timestamp": now_human,
        "state": state,
        "git": git,
        "models": models,
        "tests": tests,
        "deviation": deviation,
        "stuck_factories": stuck,
        "auto_resume": auto_resume_results,
    }

    # 写单次报告
    report_path = os.path.join(REPORTS_DIR, f"heartbeat_{now_ts}.md")
    with open(report_path, "w") as f:
        f.write(f"# 开发进度心跳报告 · {now_human}\n\n")
        f.write(f"## 1. 当前里程碑\n\n")
        f.write(f"- **current_milestone**: {state.get('current_milestone', '?')[:200]}\n")
        f.write(f"- **进行中 (doing)**: {len(state.get('doing', []))} 个\n")
        for d in state.get("doing", []):
            f.write(f"  - {d['id']}: {d['title']}\n")
        f.write(f"- **阻塞 (blocked)**: {len(state.get('blocked', []))} 个\n")
        for b in state.get("blocked", []):
            f.write(f"  - {b['id']}: {b['title']}\n")
        f.write(f"- **完成度**: {deviation['completion_pct']}% ({state.get('done_count',0)}/{state.get('total',0)})\n")
        f.write(f"- **未解决 known_issues**: {state.get('open_issues', 0)}\n")
        f.write(f"\n## 2. 进度偏差分析\n\n")
        f.write(f"- **风险等级**: {deviation['risk_level']}\n")
        for n in deviation['notes']:
            f.write(f"  - {n}\n")
        f.write(f"\n## 3. Git 状态\n\n")
        f.write(f"- 分支: {git.get('branch','?')}\n")
        f.write(f"- 最近 commit: {git.get('last_commit','?')}\n")
        age = git.get('commit_age_min')
        if age is not None:
            f.write(f"- commit 年龄: {age} 分钟{'（⚠️ 超过 30 分钟未提交）' if age > 30 else ''}\n")
        f.write(f"- 未提交改动: {git.get('dirty_files',0)} 个文件\n")
        f.write(f"\n## 4. 模型就绪状态\n\n")
        f.write(f"| 模型 | 就绪 | 延迟 | 错误 |\n|---|---|---|---|\n")
        for mid, m in models.items():
            mark = "✅" if m["ready"] else "❌"
            f.write(f"| {mid} | {mark} | {m['latency_s']}s | {m.get('error','') or '-'} |\n")
        f.write(f"\n## 5. 测试基线（最近 quality_metrics）\n\n")
        latest = tests.get("latest", {})
        if latest:
            for k in ["py_passed", "py_failed", "py_coverage", "fe_passed", "fe_failed", "fe_lines_cov", "tsc_errors", "build_ok"]:
                if k in latest:
                    f.write(f"- {k}: {latest[k]}\n")
        else:
            f.write("- （无 quality_metrics.json，跑 `bash scripts/quality_gate.sh` 生成）\n")
        f.write(f"\n## 6. 潜在阻碍因素\n\n")
        blockers = []
        if not all(m["ready"] for m in models.values()):
            blockers.append("模型未全部就绪")
        if git.get("dirty_files", 0) > 10:
            blockers.append(f"未提交改动较多（{git['dirty_files']} 文件）")
        if age and age > 60:
            blockers.append(f"长时间未 commit（{age} 分钟）")
        if state.get("open_issues", 0) > 0:
            blockers.append(f"{state['open_issues']} 个未解决 known_issue")
        if deviation['risk_level'] == "high":
            blockers.append("存在阻塞里程碑")
        if not blockers:
            f.write("- 无明显阻碍，正常推进中\n")
        else:
            for b in blockers:
                f.write(f"- ⚠️ {b}\n")

        # M158.4：自动恢复结果章节（仅当有结果时）
        if auto_resume_results:
            f.write(f"\n## 7. 自动恢复结果（M158.4）\n\n")
            f.write(f"FLIPPED_HEARTBEAT_AUTO_RESUME=1，本次恢复 {len(auto_resume_results)} 个工厂：\n\n")
            for r in auto_resume_results:
                mark = "✅" if r.get("exit_code") == 0 else "⚠️"
                f.write(f"- {mark} **{r['factory_id']}**: action={r['action']} exit_code={r.get('exit_code')}\n")
                if r.get("stderr"):
                    f.write(f"  - stderr: `{r['stderr'][:150]}`\n")

    # 追加摘要到 log
    log_path = os.path.join(REPORTS_DIR, "heartbeat.log")
    with open(log_path, "a") as f:
        ready_count = sum(1 for m in models.values() if m["ready"])
        # M154.2：恢复事件高亮标记
        recovery_mark = f" | 📢 RECOVERY={','.join(r['model'].split('-')[0] for r in recoveries)}" if recoveries else ""
        # M158.4：自动恢复标记
        auto_mark = f" | 🔄 AUTO_RESUME={len(auto_resume_results)}" if auto_resume_results else ""
        f.write(f"[{now_human}] risk={deviation['risk_level']} | completion={deviation['completion_pct']}% | doing={len(state.get('doing',[]))} blocked={len(state.get('blocked',[]))} | models={ready_count}/2 ready | git_dirty={git.get('dirty_files',0)} commit_age={git.get('commit_age_min','?')}min{recovery_mark}{auto_mark}\n")

    # 追加结构化历史
    hist_path = os.path.join(REPORTS_DIR, "heartbeat_history.jsonl")
    with open(hist_path, "a") as f:
        f.write(json.dumps(report, ensure_ascii=False) + "\n")

    # 控制台摘要
    print(f"[{now_human}] 心跳完成 → {report_path}")
    print(f"  风险: {deviation['risk_level']} | 完成度: {deviation['completion_pct']}% | 模型: {sum(1 for m in models.values() if m['ready'])}/2 就绪 | git_dirty: {git.get('dirty_files',0)}")


if __name__ == "__main__":
    main()
