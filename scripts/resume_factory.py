#!/usr/bin/env python3
"""M5 产线化 · 恢复卡住/熔断的工厂（heartbeat 主动监护闭环）。

heartbeat.py 检测到 circuit_breaker_task 或 stale_updated_at 时会写
reports/stuck_*.md 建议跑本脚本。本脚本把"建议"变成"一键恢复"：

    python3 scripts/resume_factory.py <factory_id> [--dry-run] [--db-path PATH]

流程：
1. 预检：load_factory_state 确认工厂存在 + 当前状态
2. 幂等：status=done 直接退出 0，不重复执行
3. --dry-run：只打印预检信息（含可恢复任务），不调 resume_factory_loop
4. 实际恢复：调 resume_factory_loop，按最终 status 返回退出码
   - done → 0（成功）
   - failed/error/paused/running → 1（恢复了但未完成）

设计原则：
- 不自动批量恢复：每次只处理一个工厂，人工确认后再执行
- 默认走 default_db_path()，与 heartbeat.py / factory_loop 一致
- 失败可重试：resume_factory_loop 本身是幂等的（已 done 直接返回）

退出码：
- 0：已 done（含幂等跳过）或 dry-run
- 1：resume 后仍非 done（任务级失败）
- 2：工厂不存在 / 参数错误
"""
from __future__ import annotations

import argparse
import os
import sys
from typing import Sequence


def _setup_path() -> None:
    """把 src/ 加入 sys.path 以便 import driving.*。

    放在函数内而非模块顶层，避免 import 该脚本做测试时产生副作用。
    """
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src = os.path.join(root, "src")
    if src not in sys.path:
        sys.path.insert(0, src)


def build_parser() -> argparse.ArgumentParser:
    """构造 CLI 参数解析器。"""
    p = argparse.ArgumentParser(
        prog="resume_factory.py",
        description="恢复卡住/熔断的工厂（M5 产线化主动监护闭环）",
    )
    p.add_argument(
        "factory_id",
        help="要恢复的工厂 ID（如 fac-abc12345）",
    )
    p.add_argument(
        "--db-path",
        default=None,
        help="factory DB 路径（默认用 factory_loop.default_db_path()）",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="只打印预检信息，不实际执行 resume",
    )
    p.add_argument(
        "--max-tasks",
        type=int,
        default=None,
        help="覆盖 factory 的 max_tasks（不传用 DB 中已有的值）",
    )
    p.add_argument(
        "--max-rounds",
        type=int,
        default=None,
        help="覆盖 factory 的 max_rounds（不传用 DB 中已有的值）",
    )
    return p


def _print_preflight(state, *, dry_run: bool) -> None:
    """打印预检信息：factory_id / status / 可恢复任务。"""
    print(f"[resume] factory_id   = {state.factory_id}")
    print(f"[resume] status       = {state.status.value}")
    print(f"[resume] product_goal = {state.product_goal[:80]}")
    print(f"[resume] cwd          = {state.cwd}")
    print(f"[resume] completed    = {len(state.completed)}")
    print(f"[resume] failed       = {len(state.failed)}")
    # 列出 circuit_breaker 任务（如果有）
    cb_tasks = [
        r for r in state.failed if r.stop_reason == "circuit_breaker"
    ]
    if cb_tasks:
        print(f"[resume] 可恢复任务（circuit_breaker）: {len(cb_tasks)} 个")
        for r in cb_tasks:
            print(
                f"  - {r.task.id}  summary={r.summary[:60]}  "
                f"recorded_at={r.recorded_at}"
            )
    else:
        print("[resume] 无 circuit_breaker 任务（可能只是 stale_updated_at）")
    if dry_run:
        print("[resume] --dry-run：不执行 resume，仅打印预检信息")


def main(argv: Sequence[str] | None = None) -> int:
    """CLI 入口。返回退出码（0/1/2）。"""
    args = build_parser().parse_args(argv)

    _setup_path()
    from driving.factory_loop import (
        FactoryStatus,
        default_db_path,
        load_factory_state,
        resume_factory_loop,
    )

    db_path = args.db_path or default_db_path()

    # ---- 1. 预检：工厂必须存在 ----
    state = load_factory_state(args.factory_id, db_path)
    if state is None:
        print(
            f"[resume] ✗ 工厂 {args.factory_id} 不存在于 DB {db_path}",
            file=sys.stderr,
        )
        return 2

    # ---- 2. 幂等：已 done 直接返回 ----
    if state.status == FactoryStatus.done:
        print(
            f"[resume] 工厂 {args.factory_id} 已 done，无需恢复（幂等跳过）"
        )
        return 0

    # ---- 3. 打印预检信息 ----
    _print_preflight(state, dry_run=args.dry_run)

    if args.dry_run:
        print("[resume] dry-run 完成，未执行 resume_factory_loop")
        return 0

    # ---- 4. 实际恢复 ----
    kwargs: dict = {}
    if args.max_tasks is not None:
        kwargs["max_tasks"] = args.max_tasks
    if args.max_rounds is not None:
        kwargs["max_rounds"] = args.max_rounds

    print(
        f"[resume] 调用 resume_factory_loop(factory_id={args.factory_id}, "
        f"db_path={db_path}, **kwargs={kwargs}) ..."
    )
    try:
        final = resume_factory_loop(
            args.factory_id, db_path=db_path, **kwargs
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[resume] ✗ resume_factory_loop 抛异常: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    if final is None:
        # 理论上 load_factory_state 已确认存在，这里防御性处理
        print(f"[resume] ✗ resume_factory_loop 返回 None（工厂消失？）", file=sys.stderr)
        return 1

    print(
        f"[resume] 完成：status={final.status.value}  "
        f"completed={len(final.completed)}  failed={len(final.failed)}"
    )

    # ---- 5. 退出码：done=0，其他=1 ----
    if final.status == FactoryStatus.done:
        print(f"[resume] ✓ 工厂 {args.factory_id} 恢复成功（done）")
        return 0
    print(
        f"[resume] ⚠ 工厂 {args.factory_id} 恢复后状态非 done "
        f"（{final.status.value}），任务级失败，请检查 failed 列表",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
