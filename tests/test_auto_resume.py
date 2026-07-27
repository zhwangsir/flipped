"""M158.4 — heartbeat 自动恢复门控测试（TDD）。

maybe_auto_resume 在 FLIPPED_HEARTBEAT_AUTO_RESUME=1 时，对有 circuit_breaker_task
信号的工厂自动调 resume_factory.py。安全设计：默认关、只恢复 cb 信号、done 跳过、
防风暴限制、subprocess 隔离 + 超时保护。

8 个核心用例覆盖门控、筛选、限流、异常隔离、报告写入。
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from driving.auto_resume import maybe_auto_resume


def _stuck_entry(
    *,
    factory_id: str = "fac-test",
    status: str = "paused",
    signals: list[str] | None = None,
    circuit_breaker_tasks: list[dict] | None = None,
    minutes_since_update: float = 90.0,
) -> dict:
    """构造 detect_stuck_factories 返回的单条夹具。"""
    if signals is None:
        signals = ["circuit_breaker_task"]
    if circuit_breaker_tasks is None:
        circuit_breaker_tasks = [
            {"task_id": "task-cb", "stop_reason": "circuit_breaker",
             "summary": "verify failed 3x", "recorded_at": "2026-07-27T00:00:00Z"}
        ]
    return {
        "factory_id": factory_id,
        "product_goal": "test goal",
        "cwd": "/tmp/test",
        "status": status,
        "updated_at": "2026-07-27T00:00:00Z",
        "minutes_since_update": minutes_since_update,
        "signals": signals,
        "circuit_breaker_tasks": circuit_breaker_tasks,
        "running_tasks": [],
    }


class _FakeCompletedProcess:
    """subprocess.CompletedProcess 替身。"""
    def __init__(self, returncode: int = 0, stdout: str = "", stderr: str = ""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


# --------------------------------------------------------------------
# 1. 门控关 → 不动作
# --------------------------------------------------------------------
def test_gate_off_no_action(monkeypatch, tmp_path):
    """FLIPPED_HEARTBEAT_AUTO_RESUME 未设/非 1 → 返回 []，不调 subprocess。"""
    monkeypatch.delenv("FLIPPED_HEARTBEAT_AUTO_RESUME", raising=False)
    called = {"n": 0}

    def _no_call(*a, **kw):
        called["n"] += 1
        return _FakeCompletedProcess()

    monkeypatch.setattr("driving.auto_resume.subprocess.run", _no_call)
    stuck = [_stuck_entry(factory_id="fac-cb")]
    result = maybe_auto_resume(stuck, now_ts="20260727_0100",
                               now_human="2026-07-27 01:00", reports_dir=str(tmp_path))
    assert result == []
    assert called["n"] == 0
    # 不写报告
    assert not list(tmp_path.glob("auto_resume_*.md"))


# --------------------------------------------------------------------
# 2. 门控开但无 circuit_breaker → 不动作
# --------------------------------------------------------------------
def test_gate_on_no_circuit_breaker_no_action(monkeypatch, tmp_path):
    """门控开但 signals 只有 stale_updated_at（无 cb）→ 不自动恢复。"""
    monkeypatch.setenv("FLIPPED_HEARTBEAT_AUTO_RESUME", "1")
    called = {"n": 0}

    def _no_call(*a, **kw):
        called["n"] += 1
        return _FakeCompletedProcess()

    monkeypatch.setattr("driving.auto_resume.subprocess.run", _no_call)
    stuck = [_stuck_entry(
        factory_id="fac-stale-only",
        signals=["stale_updated_at"],
        circuit_breaker_tasks=[],
    )]
    result = maybe_auto_resume(stuck, now_ts="20260727_0100",
                               now_human="2026-07-27 01:00", reports_dir=str(tmp_path))
    assert result == []
    assert called["n"] == 0


# --------------------------------------------------------------------
# 3. 门控开 + circuit_breaker → 触发 resume
# --------------------------------------------------------------------
def test_gate_on_with_circuit_breaker_triggers_resume(monkeypatch, tmp_path):
    """门控开 + cb 任务 → subprocess 调 resume_factory.py，返回结果。"""
    monkeypatch.setenv("FLIPPED_HEARTBEAT_AUTO_RESUME", "1")
    captured = {}

    def _fake_run(args, **kw):
        captured["args"] = args
        captured["timeout"] = kw.get("timeout")
        return _FakeCompletedProcess(returncode=0, stdout="[resume] ✓ done")

    monkeypatch.setattr("driving.auto_resume.subprocess.run", _fake_run)
    stuck = [_stuck_entry(factory_id="fac-cb-1")]
    result = maybe_auto_resume(stuck, now_ts="20260727_0100",
                               now_human="2026-07-27 01:00", reports_dir=str(tmp_path))
    assert len(result) == 1
    assert result[0]["factory_id"] == "fac-cb-1"
    assert result[0]["action"] == "resumed"
    assert result[0]["exit_code"] == 0
    # 验证 subprocess 调用参数
    assert "fac-cb-1" in captured["args"]
    # args 含完整路径 .../scripts/resume_factory.py，检查末尾匹配
    assert any(a.endswith("resume_factory.py") for a in captured["args"])
    assert captured["timeout"] is not None and captured["timeout"] > 0


# --------------------------------------------------------------------
# 4. done 状态即使有 cb 也不自动恢复（幂等）
# --------------------------------------------------------------------
def test_done_status_not_auto_resumed(monkeypatch, tmp_path):
    """status=done 的工厂即使有历史 cb 任务也不恢复（已完成）。"""
    monkeypatch.setenv("FLIPPED_HEARTBEAT_AUTO_RESUME", "1")
    called = {"n": 0}

    def _no_call(*a, **kw):
        called["n"] += 1
        return _FakeCompletedProcess()

    monkeypatch.setattr("driving.auto_resume.subprocess.run", _no_call)
    stuck = [_stuck_entry(factory_id="fac-done", status="done")]
    result = maybe_auto_resume(stuck, now_ts="20260727_0100",
                               now_human="2026-07-27 01:00", reports_dir=str(tmp_path))
    assert result == []
    assert called["n"] == 0


# --------------------------------------------------------------------
# 5. 防风暴：多个 cb 工厂只恢复 MAX 个
# --------------------------------------------------------------------
def test_max_limit_prevents_storm(monkeypatch, tmp_path):
    """FLIPPED_HEARTBEAT_AUTO_RESUME_MAX=2 时，3 个 cb 工厂只恢复 2 个。"""
    monkeypatch.setenv("FLIPPED_HEARTBEAT_AUTO_RESUME", "1")
    monkeypatch.setenv("FLIPPED_HEARTBEAT_AUTO_RESUME_MAX", "2")
    call_count = {"n": 0}

    def _fake_run(args, **kw):
        call_count["n"] += 1
        return _FakeCompletedProcess(returncode=0)

    monkeypatch.setattr("driving.auto_resume.subprocess.run", _fake_run)
    stuck = [
        _stuck_entry(factory_id=f"fac-cb-{i}") for i in range(3)
    ]
    result = maybe_auto_resume(stuck, now_ts="20260727_0100",
                               now_human="2026-07-27 01:00", reports_dir=str(tmp_path))
    assert len(result) == 2  # 只恢复 MAX=2 个
    assert call_count["n"] == 2
    resumed_ids = {r["factory_id"] for r in result}
    assert resumed_ids.issubset({"fac-cb-0", "fac-cb-1", "fac-cb-2"})


# --------------------------------------------------------------------
# 6. subprocess 超时不崩溃心跳
# --------------------------------------------------------------------
def test_subprocess_timeout_doesnt_crash(monkeypatch, tmp_path):
    """resume 超时 → 记录为 timeout，不抛异常，心跳继续。"""
    monkeypatch.setenv("FLIPPED_HEARTBEAT_AUTO_RESUME", "1")

    def _timeout(args, **kw):
        raise subprocess.TimeoutExpired(cmd=args, timeout=kw.get("timeout", 300))

    monkeypatch.setattr("driving.auto_resume.subprocess.run", _timeout)
    stuck = [_stuck_entry(factory_id="fac-slow")]
    result = maybe_auto_resume(stuck, now_ts="20260727_0100",
                               now_human="2026-07-27 01:00", reports_dir=str(tmp_path))
    assert len(result) == 1
    assert result[0]["action"] == "timeout"
    assert result[0]["factory_id"] == "fac-slow"


# --------------------------------------------------------------------
# 7. subprocess 非零退出码不崩溃（记录为 failed）
# --------------------------------------------------------------------
def test_subprocess_failure_recorded_not_raised(monkeypatch, tmp_path):
    """resume 返回非 0 → 记录 exit_code，不抛异常。"""
    monkeypatch.setenv("FLIPPED_HEARTBEAT_AUTO_RESUME", "1")

    def _fail(args, **kw):
        return _FakeCompletedProcess(returncode=1, stderr="[resume] ⚠ status=paused")

    monkeypatch.setattr("driving.auto_resume.subprocess.run", _fail)
    stuck = [_stuck_entry(factory_id="fac-fail")]
    result = maybe_auto_resume(stuck, now_ts="20260727_0100",
                               now_human="2026-07-27 01:00", reports_dir=str(tmp_path))
    assert len(result) == 1
    assert result[0]["exit_code"] == 1
    assert result[0]["action"] == "resumed"  # 执行了但退出码非 0


# --------------------------------------------------------------------
# 8. 报告写入 reports/auto_resume_*.md
# --------------------------------------------------------------------
def test_report_written(monkeypatch, tmp_path):
    """自动恢复后写 reports/auto_resume_{now_ts}.md，含工厂 + 结果。"""
    monkeypatch.setenv("FLIPPED_HEARTBEAT_AUTO_RESUME", "1")

    def _fake_run(args, **kw):
        return _FakeCompletedProcess(returncode=0, stdout="[resume] ✓ done")

    monkeypatch.setattr("driving.auto_resume.subprocess.run", _fake_run)
    stuck = [_stuck_entry(factory_id="fac-report")]
    maybe_auto_resume(stuck, now_ts="20260727_0100",
                      now_human="2026-07-27 01:00", reports_dir=str(tmp_path))
    reports = list(tmp_path.glob("auto_resume_20260727_0100.md"))
    assert len(reports) == 1
    content = reports[0].read_text()
    assert "fac-report" in content
    assert "exit_code" in content or "0" in content


# --------------------------------------------------------------------
# 9. FLIPPED_AUTO_RESUME_DRY_RUN=1 → subprocess 加 --dry-run
# --------------------------------------------------------------------
def test_dry_run_env_adds_dry_run_flag(monkeypatch, tmp_path):
    """FLIPPED_AUTO_RESUME_DRY_RUN=1 → subprocess args 含 --dry-run（E2E 验证用）。"""
    monkeypatch.setenv("FLIPPED_HEARTBEAT_AUTO_RESUME", "1")
    monkeypatch.setenv("FLIPPED_AUTO_RESUME_DRY_RUN", "1")
    captured = {}

    def _fake_run(args, **kw):
        captured["args"] = args
        return _FakeCompletedProcess(returncode=0)

    monkeypatch.setattr("driving.auto_resume.subprocess.run", _fake_run)
    stuck = [_stuck_entry(factory_id="fac-dry")]
    maybe_auto_resume(stuck, now_ts="20260727_0100",
                      now_human="2026-07-27 01:00", reports_dir=str(tmp_path))
    assert "--dry-run" in captured["args"]
    assert "fac-dry" in captured["args"]


# --------------------------------------------------------------------
# 10. 无 DRY_RUN 环境变量 → subprocess 不带 --dry-run（生产行为）
# --------------------------------------------------------------------
def test_no_dry_run_env_no_dry_run_flag(monkeypatch, tmp_path):
    """未设 FLIPPED_AUTO_RESUME_DRY_RUN → subprocess 不带 --dry-run（生产行为）。"""
    monkeypatch.setenv("FLIPPED_HEARTBEAT_AUTO_RESUME", "1")
    monkeypatch.delenv("FLIPPED_AUTO_RESUME_DRY_RUN", raising=False)
    captured = {}

    def _fake_run(args, **kw):
        captured["args"] = args
        return _FakeCompletedProcess(returncode=0)

    monkeypatch.setattr("driving.auto_resume.subprocess.run", _fake_run)
    stuck = [_stuck_entry(factory_id="fac-prod")]
    maybe_auto_resume(stuck, now_ts="20260727_0100",
                      now_human="2026-07-27 01:00", reports_dir=str(tmp_path))
    assert "--dry-run" not in captured["args"]
