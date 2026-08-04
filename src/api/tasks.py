"""M178.1 · 后台任务系统：任务注册表 + 定时计算（纯逻辑模块）。

「已安排」任务的后端地基：ScheduledTask 数据模型 + next_run 纯函数计算 +
TaskRegistry（JSON 持久化，原子写）。本模块零 FastAPI import、零 main import，
时钟全部经 now 参数注入（单测确定性，无 freezegun 依赖）。
端点与 scheduler 协程在 main.py；派发链复刻 assistant.send_assistant_message。
"""
from __future__ import annotations

import json
import os
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

TASK_KIND_ONCE = "once"
TASK_KIND_INTERVAL = "interval"


@dataclass
class ScheduledTask:
    """一条已安排任务（JSON 落盘形状 = asdict 原样）。"""

    id: str                       # "task-<8hex>"
    title: str                    # 用户可见标题
    prompt: str                   # 触发时派发的消息文本
    mode: str = "chat"            # chat|plan|agent|auto
    model: str = "coder"
    kind: str = TASK_KIND_ONCE    # once | interval
    run_at: str | None = None         # once：ISO 时间；interval：None
    every_minutes: int | None = None  # interval：>=1；once：None
    enabled: bool = True
    next_run_at: str | None = None    # 下次触发（disabled/once 跑完 → None）
    last_run_at: str | None = None
    last_status: str | None = None    # done | failed | skipped
    last_session_id: str | None = None
    run_count: int = 0
    created_at: str = ""


def _parse_dt(s: str, ref: datetime) -> datetime:
    """解析 ISO 时间为 datetime；naive/aware 与 ref 不一致时对齐 ref（防比较炸）。"""
    dt = datetime.fromisoformat(s)
    if (dt.tzinfo is None) != (ref.tzinfo is None):
        dt = dt.replace(tzinfo=ref.tzinfo) if ref.tzinfo is not None else dt.replace(tzinfo=None)
    return dt


def compute_next_run(task: ScheduledTask, now: datetime) -> str | None:
    """计算下次触发时刻（纯函数）。

    - enabled=False → None
    - once → run_at（已过期 <=now → None，原样返回 ISO 字符串）
    - interval → 基准 max(last_run_at, created_at)（都无 → now）+ every_minutes，
      若结果 <=now 则继续累加间隔直到首个 >now 的未来时刻
    """
    if not task.enabled:
        return None
    if task.kind == TASK_KIND_ONCE:
        if not task.run_at:
            return None
        return task.run_at if _parse_dt(task.run_at, now) > now else None
    if task.kind == TASK_KIND_INTERVAL:
        every = task.every_minutes or 0
        if every < 1:
            return None
        candidates = [d for d in (task.last_run_at, task.created_at) if d]
        base = max((_parse_dt(d, now) for d in candidates), default=now)
        step = timedelta(minutes=every)
        nxt = base + step
        while nxt <= now:
            nxt += step
        return nxt.isoformat()
    return None


def due_tasks(tasks: list[ScheduledTask], now: datetime) -> list[ScheduledTask]:
    """筛出到期任务：enabled 且 next_run_at 非空且 <= now，按 next_run_at 升序（纯函数）。"""
    due = [t for t in tasks
           if t.enabled and t.next_run_at and _parse_dt(t.next_run_at, now) <= now]
    return sorted(due, key=lambda t: _parse_dt(t.next_run_at or "", now))


class TaskRegistry:
    """任务注册表：内存 dict + JSON 持久化（tmp + os.replace 原子写，同 SessionStore 惯例）。

    文件不存在 → 空；JSON 损坏 → 空（不炸，防坏文件拖垮启动）。
    所有变更方法落盘后返回，构造时自动 load。
    """

    def __init__(self, path: Path):
        self._path = Path(path)
        self._tasks: dict[str, ScheduledTask] = {}
        self.load()

    def load(self) -> None:
        """从 JSON 文件加载任务表（不存在/损坏 → 保持空表）。"""
        if not self._path.exists():
            return
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001 坏文件不炸，回退空表
            return
        for raw in data.get("tasks", []):
            try:
                task = ScheduledTask(**raw)
            except TypeError:
                continue  # 字段漂移的脏条目跳过，不污染整表
            self._tasks[task.id] = task

    def save(self) -> None:
        """持久化到 JSON 文件（tmp + os.replace 原子写，防并发/崩溃写坏）。"""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        data = {"tasks": [asdict(t) for t in self._tasks.values()]}
        tmp = f"{self._path}.tmp"
        Path(tmp).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, self._path)

    def add(self, title: str, prompt: str, mode: str = "chat", model: str = "coder",
            kind: str = TASK_KIND_ONCE, run_at: str | None = None,
            every_minutes: int | None = None, now: datetime | None = None) -> ScheduledTask:
        """新建任务：id="task-<8hex>"，created_at=now，创建时即算 next_run_at。"""
        now = now or datetime.now(timezone.utc)
        task = ScheduledTask(
            id=f"task-{uuid.uuid4().hex[:8]}",
            title=title, prompt=prompt, mode=mode, model=model, kind=kind,
            run_at=run_at, every_minutes=every_minutes, created_at=now.isoformat(),
        )
        task.next_run_at = compute_next_run(task, now)
        self._tasks[task.id] = task
        self.save()
        return task

    def get(self, task_id: str) -> ScheduledTask | None:
        return self._tasks.get(task_id)

    def remove(self, task_id: str) -> bool:
        """删除任务；返回是否存在过。"""
        existed = task_id in self._tasks
        self._tasks.pop(task_id, None)
        if existed:
            self.save()
        return existed

    def list(self) -> list[ScheduledTask]:
        """全量任务：next_run_at 升序，None 沉底。"""
        return sorted(self._tasks.values(),
                      key=lambda t: (t.next_run_at is None, t.next_run_at or ""))

    def toggle(self, task_id: str, enabled: bool, now: datetime | None = None) -> ScheduledTask | None:
        """启停切换并重算 next_run_at（停用 → None；启用 → 按当前时刻重算）。"""
        now = now or datetime.now(timezone.utc)
        task = self._tasks.get(task_id)
        if task is None:
            return None
        task.enabled = enabled
        task.next_run_at = compute_next_run(task, now)
        self.save()
        return task

    def mark_run(self, task_id: str, status: str, session_id: str | None,
                 now: datetime | None = None) -> ScheduledTask | None:
        """记录一次触发：last_run_at/last_status/last_session_id/run_count+=1。

        once → 跑完即 enabled=False、next_run_at=None；interval → 以 last_run_at
        为基准重算 next_run_at（滚动到首个未来时刻）。
        """
        now = now or datetime.now(timezone.utc)
        task = self._tasks.get(task_id)
        if task is None:
            return None
        task.last_run_at = now.isoformat()
        task.last_status = status
        task.last_session_id = session_id
        task.run_count += 1
        if task.kind == TASK_KIND_ONCE:
            task.enabled = False
            task.next_run_at = None
        else:
            task.next_run_at = compute_next_run(task, now)
        self.save()
        return task
