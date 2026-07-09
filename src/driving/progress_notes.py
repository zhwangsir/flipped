"""工厂进展笔记与功能清单（M10.4-B）。

让无限迭代循环有"长期记忆"：每轮工厂循环自动维护
- FEATURE_CHECKLIST.json：已完成功能清单（机器可读，供演进者参考避免重复劳动）
- PROGRESS.md：人类可读的进展笔记（任务流水）

集成点：
- factory_loop.py：每个 task 完成/失败时调 record_task_*
- infinite_loop.py：每轮结束时调 record_round，并把 PROGRESS.md 注入下一轮 evolve

这就是"只需要给出方向就可以自行无限迭代"的"记忆"层——
不让演进者只看上一轮摘要（短视），而是看从开始到现在的完整进展（远视）。
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

CHECKLIST_FILE = "FEATURE_CHECKLIST.json"
PROGRESS_FILE = "PROGRESS.md"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _local_time() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def init_progress(cwd: str | Path, direction: str, design_style: str = "auto") -> None:
    """初始化（幂等） FEATURE_CHECKLIST.json + PROGRESS.md。"""
    cwd = Path(cwd)
    cwd.mkdir(parents=True, exist_ok=True)
    checklist_path = cwd / CHECKLIST_FILE
    progress_path = cwd / PROGRESS_FILE

    if not checklist_path.exists():
        checklist_path.write_text(
            json.dumps(
                {
                    "direction": direction,
                    "design_style": design_style,
                    "started_at": _now(),
                    "features": [],
                    "rounds_completed": 0,
                    "last_updated": _now(),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    if not progress_path.exists():
        progress_path.write_text(
            f"""# Flipped 工厂进展笔记

> 自主无限迭代生成。本文件由系统自动维护，请勿手动编辑。

## 方向
{direction}

## 设计风格
{design_style}

## 进展流水
""",
            encoding="utf-8",
        )


def load_checklist(cwd: str | Path) -> dict[str, Any]:
    """读取功能清单；不存在返回空结构。"""
    p = Path(cwd) / CHECKLIST_FILE
    if not p.exists():
        return {"direction": "", "features": [], "rounds_completed": 0}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"direction": "", "features": [], "rounds_completed": 0}


def load_progress_text(cwd: str | Path) -> str:
    """读取 PROGRESS.md 全文；不存在返回空串。"""
    p = Path(cwd) / PROGRESS_FILE
    if not p.exists():
        return ""
    try:
        return p.read_text(encoding="utf-8")
    except OSError:
        return ""


def _extract_feature_name(description: str) -> str:
    """从任务描述里提取人类可读的功能名（取首行或前 80 字符）。"""
    first_line = description.strip().split("\n")[0].strip()
    # 去掉常见前缀
    first_line = re.sub(r"^(实现|创建|构建|添加|修复|完成|开发|feat(?:ure)?[:：]\s*)\s*", "", first_line, flags=re.IGNORECASE)
    return first_line[:80] if first_line else "(未命名)"


def record_task_done(
    cwd: str | Path,
    task_id: str,
    description: str,
    summary: str = "",
    round_num: int | None = None,
) -> None:
    """记录一个任务完成 → 更新 FEATURE_CHECKLIST.json + 追加 PROGRESS.md。"""
    cwd = Path(cwd)
    init_progress(cwd, direction="", design_style="auto")  # 幂等初始化

    # 更新 checklist
    checklist = load_checklist(cwd)
    feature_name = _extract_feature_name(description)
    checklist["features"].append({
        "id": f"feat-{task_id}",
        "name": feature_name,
        "task_id": task_id,
        "status": "done",
        "summary": summary[:200] if summary else "",
        "round": round_num,
        "completed_at": _now(),
    })
    checklist["last_updated"] = _now()
    (cwd / CHECKLIST_FILE).write_text(
        json.dumps(checklist, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # 追加 PROGRESS.md
    progress_path = cwd / PROGRESS_FILE
    line = f"- [{'R'+str(round_num) if round_num else '✓'}] ✅ {task_id}: {feature_name}"
    if summary:
        line += f" — {summary[:120]}"
    line += f" ({_local_time()})\n"
    with progress_path.open("a", encoding="utf-8") as f:
        f.write(line)


def record_task_failed(
    cwd: str | Path,
    task_id: str,
    description: str,
    reason: str,
    round_num: int | None = None,
) -> None:
    """记录一个任务失败。"""
    cwd = Path(cwd)
    init_progress(cwd, direction="", design_style="auto")

    # checklist 也记录失败功能（status=failed）
    checklist = load_checklist(cwd)
    feature_name = _extract_feature_name(description)
    checklist["features"].append({
        "id": f"feat-{task_id}",
        "name": feature_name,
        "task_id": task_id,
        "status": "failed",
        "summary": reason[:200] if reason else "",
        "round": round_num,
        "failed_at": _now(),
    })
    checklist["last_updated"] = _now()
    (cwd / CHECKLIST_FILE).write_text(
        json.dumps(checklist, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    progress_path = cwd / PROGRESS_FILE
    line = f"- [{'R'+str(round_num) if round_num else '✗'}] ❌ {task_id}: {feature_name} — 失败: {reason[:120]} ({_local_time()})\n"
    with progress_path.open("a", encoding="utf-8") as f:
        f.write(line)


def record_round(
    cwd: str | Path,
    round_num: int,
    goal: str,
    tasks_completed: int,
    tasks_failed: int,
    summary: str = "",
) -> None:
    """记录一轮工厂循环完成 → PROGRESS.md 追加章节 + 更新 checklist 的 rounds_completed。"""
    cwd = Path(cwd)
    init_progress(cwd, direction="", design_style="auto")

    # 更新 checklist 的轮次计数
    checklist = load_checklist(cwd)
    checklist["rounds_completed"] = max(checklist.get("rounds_completed", 0), round_num)
    checklist["last_updated"] = _now()
    (cwd / CHECKLIST_FILE).write_text(
        json.dumps(checklist, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # PROGRESS.md 追加轮次章节
    progress_path = cwd / PROGRESS_FILE
    block = f"""
## 第 {round_num} 轮 ({_local_time()})
**目标**：{goal}
**结果**：完成 {tasks_completed} 个任务，失败 {tasks_failed} 个
"""
    if summary:
        block += f"**摘要**：{summary}\n"
    block += "\n"
    with progress_path.open("a", encoding="utf-8") as f:
        f.write(block)


def summarize_for_evolution(cwd: str | Path, max_features: int = 30) -> str:
    """生成给 _evolve_goal 的紧凑摘要：已完成功能清单 + 失败项 + 轮次。

    这让 GLM 演进者不只是看上一轮摘要，而是看完整的进展历史，避免重复劳动。
    """
    cwd = Path(cwd)
    checklist = load_checklist(cwd)
    features = checklist.get("features", [])[:max_features]
    done = [f["name"] for f in features if f.get("status") == "done"]
    failed = [f["name"] for f in features if f.get("status") == "failed"]
    rounds = checklist.get("rounds_completed", 0)

    parts = [
        f"已完成轮次: {rounds}",
        f"已完成功能 ({len(done)}): {', '.join(done) if done else '无'}",
    ]
    if failed:
        parts.append(f"失败的功能 ({len(failed)}): {', '.join(failed)}")
    return "\n".join(parts)


def design_brief_from_progress(cwd: str | Path) -> str | None:
    """从 PROGRESS.md 提取已沉淀的设计约束（DESIGN.md 等价物）。

    工厂可能在第一轮已经固化了 CSS variables / design tokens；
    后续轮次应继承这些约束，避免风格漂移。
    """
    text = load_progress_text(cwd)
    if not text:
        return None
    # 提取所有 hex 值、字体名等，作为设计契约
    hexes = sorted(set(re.findall(r"#[0-9a-fA-F]{6}\b", text)))
    if not hexes:
        return None
    return f"已沉淀的设计契约（从 PROGRESS.md 提取，必须保持一致）：\n颜色: {', '.join(hexes[:10])}"
