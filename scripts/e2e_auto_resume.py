#!/usr/bin/env python3
"""M158.4 · auto_resume 真实端到端验证。

在临时 DB 中构造 paused + circuit_breaker 工厂，验证完整自动恢复链路：
  detect_stuck_factories → maybe_auto_resume → subprocess(resume_factory.py)
  → 报告生成 → 数据一致性校验

设计要点：
- 临时 DB 隔离，不污染真实 data/flipped.db
- subprocess 调 resume_factory.py --dry-run（验证调用链但不真正改 DB）
- 覆盖 5 个关键环节：检测、筛选、调用、报告、数据一致性
- 覆盖异常处理：门控关、无 cb、done 跳过

退出码：全部断言通过 0，否则 1。
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# M164 · venv 自举：若 .venv 存在且当前不是 venv Python，自动重启自己。
# 否则用系统 Python 跑会因缺 langgraph 等依赖崩溃（scripts 设计为可 cron/直接跑，不能假设 venv 已激活）。
_VENV_PY = str(ROOT / ".venv" / "bin" / "python3")
if os.path.exists(_VENV_PY) and os.path.realpath(sys.executable) != os.path.realpath(_VENV_PY):
    os.execv(_VENV_PY, [_VENV_PY] + sys.argv)

sys.path.insert(0, str(ROOT / "src"))

from driving.factory_health import detect_stuck_factories  # noqa: E402
from driving.auto_resume import maybe_auto_resume  # noqa: E402


def _ensure_factory_table(conn: sqlite3.Connection) -> None:
    """建 factory_states 表（与 factory_loop._TABLE_SQL 一致的最小子集）。"""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS factory_states (
            factory_id TEXT PRIMARY KEY,
            product_goal TEXT NOT NULL,
            cwd TEXT NOT NULL,
            status TEXT NOT NULL,
            roadmap_json TEXT NOT NULL,
            completed_json TEXT NOT NULL,
            failed_json TEXT NOT NULL,
            current_task_id TEXT,
            context_summary TEXT NOT NULL,
            iteration_count INTEGER NOT NULL,
            max_tasks INTEGER NOT NULL,
            design_style TEXT NOT NULL DEFAULT 'auto',
            design_context TEXT NOT NULL DEFAULT '',
            rca_history_json TEXT NOT NULL DEFAULT '[]',
            current_worktree_id TEXT,
            cli_enabled INTEGER NOT NULL DEFAULT 1,
            cli_stats_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )


def _insert_factory(
    conn: sqlite3.Connection,
    *,
    factory_id: str,
    product_goal: str = "E2E 测试工厂",
    cwd: str = "/tmp/e2e_test",
    status: str = "paused",
    failed_json: str = "[]",
    updated_at: str = "2026-07-20T00:00:00+00:00",
) -> None:
    conn.execute(
        """
        INSERT INTO factory_states (
            factory_id, product_goal, cwd, status, roadmap_json, completed_json,
            failed_json, current_task_id, context_summary, iteration_count,
            max_tasks, design_style, design_context, rca_history_json,
            current_worktree_id, cli_enabled, cli_stats_json,
            created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, NULL, '', 0, 1, 'auto', '', '[]', NULL, 1, '{}', ?, ?)
        """,
        (factory_id, product_goal, cwd, status, "[]", "[]", failed_json,
         updated_at, updated_at),
    )
    conn.commit()


def _failed_json_with_circuit_breaker(task_id: str = "task-cb-e2e") -> str:
    """构造含 circuit_breaker 任务的 failed_json。"""
    return json.dumps([
        {
            "task": {
                "id": task_id,
                "description": "E2E cb task",
                "verify_cmd": ["true"],
                "status": "failed",
                "attempts": 3,
                "max_attempts": 3,
                "depends_on": [],
                "artifacts": [],
                "feedback": "",
            },
            "verified": False,
            "stop_reason": "circuit_breaker",
            "iteration": 3,
            "summary": "E2E: verify failed 3x, circuit breaker triggered",
            "recorded_at": "2026-07-20T00:00:00+00:00",
        }
    ])


def _snapshot_factory(db_path: str, factory_id: str) -> dict | None:
    """读取工厂当前状态快照（用于数据一致性校验）。"""
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.execute(
            "SELECT factory_id, status, failed_json, updated_at "
            "FROM factory_states WHERE factory_id = ?",
            (factory_id,),
        )
        row = cur.fetchone()
        if row is None:
            return None
        return {
            "factory_id": row["factory_id"],
            "status": row["status"],
            "failed_json": row["failed_json"],
            "updated_at": row["updated_at"],
        }


def main() -> int:
    failures: list[str] = []
    results_log: list[str] = []

    def log(msg: str) -> None:
        print(msg, flush=True)
        results_log.append(msg)

    log("=" * 60)
    log("[E2E] M158.4 auto_resume 真实端到端验证")
    log("=" * 60)

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        db_path = str(tmp_path / "e2e_auto_resume.db")
        reports_dir = str(tmp_path / "reports")
        os.makedirs(reports_dir, exist_ok=True)

        # ---- 阶段 1：构造测试数据 ----
        log("\n[E2E] 阶段 1：构造临时 DB + 测试工厂")
        with sqlite3.connect(db_path) as conn:
            _ensure_factory_table(conn)
            # 工厂 A：paused + circuit_breaker（应被自动恢复）
            _insert_factory(
                conn,
                factory_id="fac-e2e-cb",
                status="paused",
                failed_json=_failed_json_with_circuit_breaker("task-cb-e2e"),
                updated_at="2026-07-20T00:00:00+00:00",  # 很旧，触发 stale
            )
            # 工厂 B：paused 无 cb（不应被自动恢复，纯 stale 需人工）
            _insert_factory(
                conn,
                factory_id="fac-e2e-stale",
                status="paused",
                failed_json="[]",
                updated_at="2026-07-20T00:00:00+00:00",
            )
            # 工厂 C：done + cb（不应被恢复，幂等跳过）
            _insert_factory(
                conn,
                factory_id="fac-e2e-done",
                status="done",
                failed_json=_failed_json_with_circuit_breaker("task-cb-done"),
                updated_at="2026-07-20T00:00:00+00:00",
            )
        log(f"[E2E] 插入 3 个工厂：fac-e2e-cb(paused+cb) / fac-e2e-stale(paused) / fac-e2e-done(done+cb)")
        log(f"[E2E] DB: {db_path}")

        # ---- 阶段 2：detect_stuck_factories 检测 ----
        log("\n[E2E] 阶段 2：detect_stuck_factories 检测")
        stuck = detect_stuck_factories(db_path=db_path, stale_minutes=30)
        log(f"[E2E] 检测到 {len(stuck)} 个有信号工厂")
        for s in stuck:
            log(f"  {s['factory_id']}: status={s['status']} signals={s['signals']}")
        if len(stuck) != 3:
            failures.append(f"阶段2: 预期 3 个有信号工厂，实际 {len(stuck)}")
        # 验证 fac-e2e-cb 有 circuit_breaker_task 信号
        cb_factory = next((s for s in stuck if s["factory_id"] == "fac-e2e-cb"), None)
        if cb_factory is None:
            failures.append("阶段2: fac-e2e-cb 未被检测到")
        elif "circuit_breaker_task" not in cb_factory["signals"]:
            failures.append(f"阶段2: fac-e2e-cb 缺 circuit_breaker_task 信号，实际 {cb_factory['signals']}")

        # ---- 阶段 3：门控关 → 不动作 ----
        log("\n[E2E] 阶段 3：门控关（FLIPPED_HEARTBEAT_AUTO_RESUME 未设）")
        os.environ.pop("FLIPPED_HEARTBEAT_AUTO_RESUME", None)
        result_off = maybe_auto_resume(
            stuck, now_ts="20260727_e2e_off", now_human="2026-07-27 E2E-off",
            reports_dir=reports_dir,
        )
        log(f"[E2E] 门控关结果: {len(result_off)} 个恢复（预期 0）")
        if result_off != []:
            failures.append(f"阶段3: 门控关时不应有恢复，实际 {len(result_off)}")

        # ---- 阶段 4：门控开 → 自动恢复 cb 工厂（--dry-run）----
        log("\n[E2E] 阶段 4：门控开（FLIPPED_HEARTBEAT_AUTO_RESUME=1）")
        os.environ["FLIPPED_HEARTBEAT_AUTO_RESUME"] = "1"
        # 关键：dry-run 模式验证调用链但不调 LLM 改 DB
        # - FLIPPED_AUTO_RESUME_DRY_RUN=1 → auto_resume 给 subprocess 加 --dry-run
        # - FLIPPED_DB=db_path → resume_factory.py 用临时 DB
        os.environ["FLIPPED_AUTO_RESUME_DRY_RUN"] = "1"
        os.environ["FLIPPED_DB"] = db_path

        # 数据一致性快照（恢复前）
        snapshot_before = _snapshot_factory(db_path, "fac-e2e-cb")
        log(f"[E2E] 恢复前快照: status={snapshot_before['status']}")

        result_on = maybe_auto_resume(
            stuck, now_ts="20260727_e2e_on", now_human="2026-07-27 E2E-on",
            reports_dir=reports_dir,
        )
        log(f"[E2E] 门控开结果: {len(result_on)} 个恢复")
        for r in result_on:
            log(f"  {r['factory_id']}: action={r['action']} exit_code={r.get('exit_code')}")

        # 验证：只恢复了 fac-e2e-cb（cb 信号 + 非 done）
        if len(result_on) != 1:
            failures.append(f"阶段4: 预期恢复 1 个（fac-e2e-cb），实际 {len(result_on)}")
        elif result_on[0]["factory_id"] != "fac-e2e-cb":
            failures.append(f"阶段4: 恢复了 {result_on[0]['factory_id']}，预期 fac-e2e-cb")
        elif result_on[0]["action"] != "resumed":
            failures.append(f"阶段4: action={result_on[0]['action']}，预期 resumed")

        # ---- 阶段 5：报告生成校验 ----
        log("\n[E2E] 阶段 5：报告生成校验")
        report_files = list(Path(reports_dir).glob("auto_resume_*.md"))
        log(f"[E2E] 报告文件: {[f.name for f in report_files]}")
        if len(report_files) != 1:
            failures.append(f"阶段5: 预期 1 个报告，实际 {len(report_files)}")
        else:
            content = report_files[0].read_text()
            if "fac-e2e-cb" not in content:
                failures.append("阶段5: 报告未含 fac-e2e-cb")
            if "exit_code" not in content:
                failures.append("阶段5: 报告未含 exit_code")
            log(f"[E2E] 报告内容前 200 字符:\n{content[:200]}")

        # ---- 阶段 6：数据一致性校验（dry-run 不应改 DB）----
        log("\n[E2E] 阶段 6：数据一致性校验（--dry-run 不改 DB）")
        snapshot_after = _snapshot_factory(db_path, "fac-e2e-cb")
        log(f"[E2E] 恢复后快照: status={snapshot_after['status']}")
        if snapshot_before != snapshot_after:
            failures.append(
                f"阶段6: dry-run 改了 DB！before={snapshot_before} after={snapshot_after}"
            )
        else:
            log("[E2E] ✓ 数据一致性通过（dry-run 未改 DB）")

        # ---- 阶段 7：防风暴限制校验 ----
        log("\n[E2E] 阶段 7：防风暴限制（MAX=1）")
        # 插入 3 个 paused+cb 工厂，MAX=1 时只恢复 1 个
        with sqlite3.connect(db_path) as conn:
            for i in range(3):
                _insert_factory(
                    conn,
                    factory_id=f"fac-e2e-storm-{i}",
                    status="paused",
                    failed_json=_failed_json_with_circuit_breaker(f"task-cb-{i}"),
                )
        stuck_storm = detect_stuck_factories(db_path=db_path, stale_minutes=30)
        os.environ["FLIPPED_HEARTBEAT_AUTO_RESUME_MAX"] = "1"
        result_storm = maybe_auto_resume(
            stuck_storm, now_ts="20260727_e2e_storm", now_human="2026-07-27 E2E-storm",
            reports_dir=reports_dir,
        )
        log(f"[E2E] 防风暴结果: {len(result_storm)} 个恢复（MAX=1，预期 ≤1）")
        if len(result_storm) > 1:
            failures.append(f"阶段7: 防风暴失败，恢复了 {len(result_storm)} 个，MAX=1")
        os.environ.pop("FLIPPED_HEARTBEAT_AUTO_RESUME_MAX", None)

        # 清理环境
        os.environ.pop("FLIPPED_HEARTBEAT_AUTO_RESUME", None)
        os.environ.pop("FLIPPED_AUTO_RESUME_DRY_RUN", None)
        os.environ.pop("FLIPPED_DB", None)

    # ---- 总结 ----
    log("\n" + "=" * 60)
    if failures:
        log("[E2E] ✗ FAIL:")
        for f in failures:
            log(f"  - {f}")
        # 写报告
        report_path = ROOT / "reports" / "e2e_auto_resume_fail.md"
        report_path.parent.mkdir(exist_ok=True)
        report_path.write_text("\n".join(results_log))
        log(f"[E2E] 失败报告: {report_path}")
        return 1
    log("[E2E] ✓ PASS: auto_resume 完整调用链验证通过")
    log("[E2E]   - 检测：detect_stuck_factories 正确识别 cb 信号")
    log("[E2E]   - 筛选：只恢复 cb+非done，stale 和 done 跳过")
    log("[E2E]   - 门控：关时不动作，开时触发")
    log("[E2E]   - 调用：subprocess 调 resume_factory.py 成功")
    log("[E2E]   - 报告：reports/auto_resume_*.md 生成")
    log("[E2E]   - 一致性：dry-run 未改 DB")
    log("[E2E]   - 防风暴：MAX=1 时只恢复 1 个")
    # 写成功报告
    report_path = ROOT / "reports" / "e2e_auto_resume_pass.md"
    report_path.parent.mkdir(exist_ok=True)
    report_path.write_text("\n".join(results_log))
    log(f"[E2E] 成功报告: {report_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
