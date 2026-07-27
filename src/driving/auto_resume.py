"""M158.4 — heartbeat 自动恢复门控。

当 FLIPPED_HEARTBEAT_AUTO_RESUME=1 时，heartbeat 检测到 circuit_breaker_task
的工厂可自动调 resume_factory.py 恢复，无需人工介入。把 M158 的"检测→告警→人工恢复"
闭环升级为"检测→告警→可选自动恢复"。

安全设计（对齐 AGENTS.md §7 沙箱外动作要审批）：
- 默认关（FLIPPED_HEARTBEAT_AUTO_RESUME 默认 "" / "0"），需显式开启
- 只恢复有 circuit_breaker_task 信号的工厂（明确可恢复）
- done 状态不恢复（幂等，已完成）
- 纯 stale_updated_at 不自动恢复（可能是真崩溃，需人工检查进程/容器）
- 单次最多 N 个（FLIPPED_HEARTBEAT_AUTO_RESUME_MAX 默认 1，防风暴）
- subprocess 隔离（resume 崩溃不拖垮心跳进程）
- 超时保护（FLIPPED_HEARTBEAT_AUTO_RESUME_TIMEOUT 默认 300s）
- 结果写 reports/auto_resume_*.md 留痕

环境变量：
- FLIPPED_HEARTBEAT_AUTO_RESUME: "1" 启用，其他/未设 = 关
- FLIPPED_HEARTBEAT_AUTO_RESUME_MAX: 单次心跳最多恢复几个（默认 1）
- FLIPPED_HEARTBEAT_AUTO_RESUME_TIMEOUT: 单次 resume 超时秒数（默认 300）
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def _is_gate_enabled() -> bool:
    """FLIPPED_HEARTBEAT_AUTO_RESUME=1 才启用。"""
    return os.environ.get("FLIPPED_HEARTBEAT_AUTO_RESUME", "") == "1"


def _max_resumes() -> int:
    """单次心跳最多恢复几个工厂（防风暴）。"""
    try:
        return max(1, int(os.environ.get("FLIPPED_HEARTBEAT_AUTO_RESUME_MAX", "1")))
    except ValueError:
        return 1


def _timeout_seconds() -> int:
    """单次 resume 超时秒数。"""
    try:
        return max(30, int(os.environ.get("FLIPPED_HEARTBEAT_AUTO_RESUME_TIMEOUT", "300")))
    except ValueError:
        return 300


def _resume_factory_script() -> str:
    """定位 scripts/resume_factory.py 绝对路径。

    src/driving/auto_resume.py → parent.parent.parent = 项目根 → scripts/resume_factory.py
    """
    root = Path(__file__).resolve().parent.parent.parent
    return str(root / "scripts" / "resume_factory.py")


def _build_resume_args(factory_id: str) -> list[str]:
    """构造 resume_factory.py 的 subprocess 调用参数。

    FLIPPED_AUTO_RESUME_DRY_RUN=1 时加 --dry-run，用于 E2E 验证场景：
    验证完整调用链（detect→filter→subprocess→report）但不真正调 LLM 改 DB。
    """
    args = [sys.executable, _resume_factory_script(), factory_id]
    if os.environ.get("FLIPPED_AUTO_RESUME_DRY_RUN", "") == "1":
        args.append("--dry-run")
    return args


def _filter_resumable(stuck: list[dict]) -> list[dict]:
    """筛选可自动恢复的工厂：有 circuit_breaker_task 信号 且 非 done。

    纯 stale_updated_at 不在此列——那可能是进程真崩溃，需人工检查
    （ps/docker ps），自动 resume 一个崩溃的工厂无意义。
    """
    result = []
    for s in stuck:
        if s.get("status") == "done":
            continue  # 已完成，幂等跳过
        if "circuit_breaker_task" not in s.get("signals", []):
            continue  # 无 cb 信号，不自动恢复
        if not s.get("circuit_breaker_tasks"):
            continue  # cb 信号但无具体任务（防御性）
        result.append(s)
    return result


def maybe_auto_resume(
    stuck: list[dict],
    *,
    now_ts: str,
    now_human: str,
    reports_dir: str | None = None,
) -> list[dict]:
    """检查门控，对符合条件的工厂自动调 resume_factory.py。

    Args:
        stuck: detect_stuck_factories 返回的风险工厂列表
        now_ts: 时间戳字符串（如 "20260727_0100"）用于报告文件名
        now_human: 人类可读时间（如 "2026-07-27 01:00:00"）用于报告标题
        reports_dir: 报告输出目录，None 时不写报告

    Returns:
        恢复结果列表，每项：
        - factory_id: 工厂 ID
        - action: "resumed"（执行了）/ "timeout" / "error"
        - exit_code: subprocess 退出码（timeout/error 时为 None）
        - stdout / stderr: 截断的子进程输出（各 ≤500 字符）
    """
    if not _is_gate_enabled():
        return []

    resumable = _filter_resumable(stuck)
    if not resumable:
        return []

    # 防风暴限制
    max_n = _max_resumes()
    resumable = resumable[:max_n]

    timeout = _timeout_seconds()

    results = []
    for s in resumable:
        factory_id = s["factory_id"]
        try:
            cp = subprocess.run(
                _build_resume_args(factory_id),
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            results.append({
                "factory_id": factory_id,
                "action": "resumed",
                "exit_code": cp.returncode,
                "stdout": (cp.stdout or "")[:500],
                "stderr": (cp.stderr or "")[:500],
            })
        except subprocess.TimeoutExpired as e:
            results.append({
                "factory_id": factory_id,
                "action": "timeout",
                "exit_code": None,
                "stdout": "",
                "stderr": f"TimeoutExpired after {e.timeout}s",
            })
        except Exception as e:  # noqa: BLE001
            results.append({
                "factory_id": factory_id,
                "action": "error",
                "exit_code": None,
                "stdout": "",
                "stderr": f"{type(e).__name__}: {e}"[:500],
            })

    # 写报告（即使部分失败也写，留痕）
    if results and reports_dir:
        _write_report(results, now_ts, now_human, reports_dir)

    return results


def _write_report(
    results: list[dict],
    now_ts: str,
    now_human: str,
    reports_dir: str,
) -> None:
    """写 reports/auto_resume_{now_ts}.md 留痕。"""
    os.makedirs(reports_dir, exist_ok=True)
    path = os.path.join(reports_dir, f"auto_resume_{now_ts}.md")
    with open(path, "w") as f:
        f.write(f"# 自动恢复报告 · {now_human}\n\n")
        f.write(
            f"FLIPPED_HEARTBEAT_AUTO_RESUME=1 触发，"
            f"本次恢复 {len(results)} 个工厂：\n\n"
        )
        for r in results:
            f.write(f"## {r['factory_id']}\n\n")
            f.write(f"- **action**: {r['action']}\n")
            f.write(f"- **exit_code**: {r['exit_code']}\n")
            if r.get("stdout"):
                f.write(f"- **stdout**: `{r['stdout'][:200]}`\n")
            if r.get("stderr"):
                f.write(f"- **stderr**: `{r['stderr'][:200]}`\n")
            f.write("\n")
        f.write("## 安全说明\n\n")
        f.write("- 仅恢复有 circuit_breaker_task 信号的工厂（明确可恢复）\n")
        f.write("- 纯 stale_updated_at 未自动恢复（需人工检查进程/容器）\n")
        f.write("- 单次心跳最多恢复 FLIPPED_HEARTBEAT_AUTO_RESUME_MAX 个（防风暴）\n")
