"""M5 产线化真实验收 — factory 健康检测。

为 heartbeat.py 提供主动监护能力：识别产线上卡住/可恢复的工厂，
让心跳从"被动报告"升级为"主动健康检测"，补齐 M5.4 resume_orchestrated
缺少的"检测 → 触发建议"自动闭环（本模块只做只读检测，不自动 resume）。

两类产线风险信号：
1. stale_updated_at：status=running/paused 但 updated_at 超 stale_minutes
   （进程可能崩溃/僵死，需人工或 resume 恢复）
2. circuit_breaker_task：failed_json 含 stop_reason=circuit_breaker 的任务
   （verify 熔断，可触发 resume_orchestrated 重试）
3. running_task：roadmap_json 含 status=running 的 task（任务级卡住）

设计原则：纯只读，fail-open，不扰动产线。
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any

from driving import factory_loop


def _parse_iso(ts: str) -> datetime | None:
    """解析 ISO 时间字符串，失败返回 None。容忍带/不带时区。"""
    if not ts:
        return None
    try:
        # Python 3.11+ fromisoformat 支持 'Z' 后缀和大部分 ISO 变体
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def _minutes_since(ts: str, now: datetime | None = None) -> float | None:
    """计算 ts 距现在多少分钟，解析失败返回 None。"""
    dt = _parse_iso(ts)
    if dt is None:
        return None
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return round((now - dt).total_seconds() / 60.0, 1)


def _extract_circuit_breaker_tasks(failed_json: str) -> list[dict[str, Any]]:
    """从 failed_json 解析出 stop_reason=circuit_breaker 的 TaskResult 列表。

    failed_json = json.dumps([TaskResult.model_dump(), ...])
    返回精简结构：[{task_id, stop_reason, summary, recorded_at}, ...]
    """
    if not failed_json:
        return []
    try:
        results = json.loads(failed_json)
    except Exception:
        return []
    cb_tasks = []
    for r in results:
        if not isinstance(r, dict):
            continue
        if r.get("stop_reason") == "circuit_breaker":
            task = r.get("task") or {}
            cb_tasks.append(
                {
                    "task_id": task.get("id", "?"),
                    "stop_reason": r.get("stop_reason", ""),
                    "summary": r.get("summary", ""),
                    "recorded_at": r.get("recorded_at", ""),
                }
            )
    return cb_tasks


def _extract_running_tasks(roadmap_json: str) -> list[str]:
    """从 roadmap_json 解析出 status=running 的 task id 列表。

    roadmap_json = json.dumps([FactoryTask.model_dump(), ...])
    """
    if not roadmap_json:
        return []
    try:
        tasks = json.loads(roadmap_json)
    except Exception:
        return []
    running = []
    for t in tasks:
        if not isinstance(t, dict):
            continue
        if t.get("status") == "running":
            running.append(t.get("id", "?"))
    return running


def detect_stuck_factories(
    *,
    db_path: str | None = None,
    stale_minutes: int = 30,
) -> list[dict[str, Any]]:
    """检测卡住/可恢复的工厂。

    Args:
        db_path: factory DB 路径，None 时用 default_db_path()
        stale_minutes: running/paused 工厂 updated_at 超过此分钟数视为卡住

    Returns:
        有风险信号的工厂列表，每项含：
        - factory_id, product_goal, cwd, status, updated_at
        - minutes_since_update: 距上次更新分钟数（解析失败为 None）
        - signals: 风险信号列表（stale_updated_at / circuit_breaker_task / running_task）
        - circuit_breaker_tasks: 可恢复任务详情
        - running_tasks: 卡住的任务 id 列表

    fail-open：DB 异常或表不存在返回 []，不阻塞心跳。
    """
    db_path = db_path or factory_loop.default_db_path()
    try:
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            # 检查表是否存在（旧库可能未初始化 factory_states）
            try:
                cursor = conn.execute(
                    "SELECT factory_id, product_goal, cwd, status, roadmap_json, "
                    "failed_json, updated_at FROM factory_states"
                )
                rows = cursor.fetchall()
            except sqlite3.OperationalError:
                # 表不存在，fail-open
                return []
    except Exception:
        return []

    now = datetime.now(timezone.utc)
    result = []
    for row in rows:
        status = row["status"]
        updated_at = row["updated_at"]
        minutes = _minutes_since(updated_at, now)

        signals: list[str] = []
        circuit_breaker_tasks: list[dict[str, Any]] = []
        running_tasks: list[str] = []

        # 信号 1：running/paused 且 updated_at 超阈值（进程可能崩溃/僵死）
        # done/failed 状态已结束，即使 updated_at 很旧也不算卡住
        if status in ("running", "paused") and minutes is not None and minutes >= stale_minutes:
            signals.append("stale_updated_at")

        # 信号 2：failed_json 含 circuit_breaker 任务（可触发 resume）
        circuit_breaker_tasks = _extract_circuit_breaker_tasks(row["failed_json"])
        if circuit_breaker_tasks:
            signals.append("circuit_breaker_task")

        # 信号 3：roadmap 含 status=running 的 task（任务级卡住）
        running_tasks = _extract_running_tasks(row["roadmap_json"])
        if running_tasks:
            signals.append("running_task")

        # 只返回有信号的工厂
        if signals:
            result.append(
                {
                    "factory_id": row["factory_id"],
                    "product_goal": row["product_goal"],
                    "cwd": row["cwd"],
                    "status": status,
                    "updated_at": updated_at,
                    "minutes_since_update": minutes,
                    "signals": signals,
                    "circuit_breaker_tasks": circuit_breaker_tasks,
                    "running_tasks": running_tasks,
                }
            )
    return result
