"""M127 · Agent 状态 hook 模块。

借鉴 Orca 的三态模型（Active/Waiting/Finished），扩展为五态以覆盖完整生命周期：
- active:   正在执行任务
- waiting:  等待人类介入（审批/澄清）
- finished: 已完成
- failed:   执行失败
- idle:     空闲（已注册但尚未开始）

通过 hook 机制感知 Agent 状态变化，并提供两种 relay 通道把状态实时推送出去：
1. subscribe(callback) —— 进程内订阅（同步回调，fail-open）
2. relay_to_webhook(url) —— 跨进程 Webhook 回调（HTTP POST，fail-open）

设计要点：
- fail-open：webhook 失败、订阅者抛异常都绝不阻塞状态更新主流程。
- 线程安全：内部加锁，支持多 Agent 并发追踪。
- 全程用 structured_logger 留下审计轨迹。
"""
from __future__ import annotations

import json
import threading
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable

from driving.structured_logger import StructuredLogger, LogLevel


class AgentStatus(str, Enum):
    """Agent 生命周期状态。

    三态核心（Orca 模型）：active / waiting / finished；
    failed / idle 为扩展态，用于失败与空闲场景。
    """
    active = "active"
    waiting = "waiting"
    finished = "finished"
    failed = "failed"
    idle = "idle"


@dataclass
class AgentState:
    """单个 Agent 的状态快照。"""
    agent_id: str
    status: AgentStatus
    task_id: str = ""
    worktree_path: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """序列化为可 JSON 化的字典。"""
        return {
            "agent_id": self.agent_id,
            "status": self.status.value,
            "task_id": self.task_id,
            "worktree_path": self.worktree_path,
            "timestamp": self.timestamp,
            "metadata": dict(self.metadata),
        }


# 订阅回调签名：(agent_id, old_state | None, new_state) -> None
StatusChangeCallback = Callable[[str, "AgentState | None", "AgentState"], None]


class StatusHook:
    """Agent 状态追踪与分发器。

    职责：
    - 维护每个 agent 的当前状态（register/update/get_state）。
    - 按状态聚合查询（list_active/list_waiting/list_finished）。
    - 状态变化时通知订阅者与 webhook（subscribe/unsubscribe/relay_to_webhook）。
    - 暴露统计信息（stats）。

    Args:
        logger: 结构化日志记录器，默认自建一个 info 级别实例。
    """

    def __init__(self, *, logger: StructuredLogger | None = None) -> None:
        self.logger = logger or StructuredLogger(
            module_name="agent_status_hook",
            min_level=LogLevel.info,
        )
        self._states: dict[str, AgentState] = {}
        self._subscribers: list[StatusChangeCallback] = []
        self._webhooks: list[str] = []
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ 注册

    def register(
        self,
        agent_id: str,
        *,
        task_id: str = "",
        worktree_path: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> AgentState:
        """注册一个 Agent 进行追踪。

        幂等：若已注册则返回当前状态（不重置）。
        新注册的 Agent 初始状态为 idle。

        Args:
            agent_id: Agent 唯一标识。
            task_id: 关联任务标识。
            worktree_path: Agent 工作目录（worktree 路径）。
            metadata: 任意附加元数据。
        """
        with self._lock:
            existing = self._states.get(agent_id)
            if existing is not None:
                self.logger.debug("agent_already_registered", {"agent_id": agent_id})
                return existing

            state = AgentState(
                agent_id=agent_id,
                status=AgentStatus.idle,
                task_id=task_id,
                worktree_path=worktree_path,
                metadata=dict(metadata or {}),
            )
            self._states[agent_id] = state

        self.logger.info("agent_registered", {
            "agent_id": agent_id,
            "task_id": task_id,
            "worktree_path": worktree_path,
        })
        # 注册本身不视为状态变化，不触发订阅者/webhook
        return state

    # ------------------------------------------------------------------ 更新

    def update(
        self,
        agent_id: str,
        status: AgentStatus,
        metadata: dict[str, Any] | None = None,
    ) -> AgentState | None:
        """更新 Agent 状态并分发通知。

        若 Agent 未注册，自动以新状态注册（fail-open，便于 hook 直接驱动）。
        状态未变化时不触发通知（避免冗余 webhook）。

        Args:
            agent_id: Agent 标识。
            status: 新状态。
            metadata: 附加/合并元数据（浅合并到既有 metadata）。

        Returns:
            更新后的 AgentState；理论上不会返回 None（自动注册保证存在）。
        """
        with self._lock:
            old_state = self._states.get(agent_id)
            if old_state is None:
                # 未注册则自动注册并直接落到目标状态
                new_state = AgentState(
                    agent_id=agent_id,
                    status=status,
                    metadata=dict(metadata or {}),
                )
                self._states[agent_id] = new_state
                self.logger.warn("agent_auto_registered_on_update", {
                    "agent_id": agent_id,
                    "status": status.value,
                })
            else:
                if old_state.status == status and not metadata:
                    # 状态未变且无新元数据：无操作
                    self.logger.debug("agent_status_unchanged", {
                        "agent_id": agent_id,
                        "status": status.value,
                    })
                    return old_state

                new_state = AgentState(
                    agent_id=agent_id,
                    status=status,
                    task_id=old_state.task_id,
                    worktree_path=old_state.worktree_path,
                    metadata={**old_state.metadata, **(metadata or {})},
                )
                self._states[agent_id] = new_state

            # 在锁外分发会更复杂，这里在锁内收集快照、锁外分发；
            # 为简化并保证一致性，先在锁内拷贝需要分发的数据。
            old_snapshot = old_state
            new_snapshot = new_state

        self.logger.info("agent_status_changed", {
            "agent_id": agent_id,
            "old_status": old_snapshot.status.value if old_snapshot else None,
            "new_status": new_snapshot.status.value,
        })

        self._notify(agent_id, old_snapshot, new_snapshot)
        return new_snapshot

    # ------------------------------------------------------------------ 查询

    def get_state(self, agent_id: str) -> AgentState | None:
        """获取 Agent 当前状态；未注册返回 None。"""
        with self._lock:
            return self._states.get(agent_id)

    def list_active(self) -> list[AgentState]:
        """列出所有 active 状态的 Agent。"""
        return self._list_by_status(AgentStatus.active)

    def list_waiting(self) -> list[AgentState]:
        """列出所有 waiting 状态的 Agent（等待人类介入）。"""
        return self._list_by_status(AgentStatus.waiting)

    def list_finished(self) -> list[AgentState]:
        """列出所有 finished 状态的 Agent。"""
        return self._list_by_status(AgentStatus.finished)

    def _list_by_status(self, status: AgentStatus) -> list[AgentState]:
        with self._lock:
            return [s for s in self._states.values() if s.status == status]

    # ------------------------------------------------------------------ 订阅

    def subscribe(self, callback: StatusChangeCallback) -> None:
        """订阅状态变化。回调签名：callback(agent_id, old_state, new_state)。

        fail-open：回调抛异常会被捕获并记录，不影响其他订阅者与主流程。
        """
        with self._lock:
            if callback not in self._subscribers:
                self._subscribers.append(callback)
        self.logger.info("subscriber_added", {"total": len(self._subscribers)})

    def unsubscribe(self, callback: StatusChangeCallback) -> bool:
        """取消订阅。返回是否成功移除。"""
        with self._lock:
            if callback in self._subscribers:
                self._subscribers.remove(callback)
                removed = True
            else:
                removed = False
        if removed:
            self.logger.info("subscriber_removed", {"total": len(self._subscribers)})
        return removed

    # ------------------------------------------------------------------ webhook

    def relay_to_webhook(self, url: str) -> None:
        """注册一个 Webhook URL，状态变化时回调（HTTP POST JSON）。

        fail-open：Webhook 请求失败不阻塞状态更新，仅记录错误日志。
        """
        with self._lock:
            if url not in self._webhooks:
                self._webhooks.append(url)
        self.logger.info("webhook_registered", {"url": url, "total": len(self._webhooks)})

    def clear_webhooks(self) -> None:
        """清空所有已注册的 webhook（测试/重置用）。"""
        with self._lock:
            self._webhooks.clear()

    # ------------------------------------------------------------------ 分发

    def _notify(
        self,
        agent_id: str,
        old_state: AgentState | None,
        new_state: AgentState,
    ) -> None:
        """通知所有订阅者与 webhook。fail-open：任何异常都被吞掉。"""
        # 1) 进程内订阅者
        with self._lock:
            subscribers = list(self._subscribers)
            webhooks = list(self._webhooks)

        for cb in subscribers:
            try:
                cb(agent_id, old_state, new_state)
            except Exception as e:  # noqa: BLE001 —— fail-open，不能因订阅者崩溃阻塞
                self.logger.error("subscriber_callback_failed", {
                    "agent_id": agent_id,
                    "error": str(e),
                })

        # 2) webhook relay
        for url in webhooks:
            self._post_webhook(url, agent_id, old_state, new_state)

    def _post_webhook(
        self,
        url: str,
        agent_id: str,
        old_state: AgentState | None,
        new_state: AgentState,
    ) -> None:
        """向单个 webhook POST 状态变化事件。fail-open。"""
        payload = {
            "event": "agent_status_changed",
            "agent_id": agent_id,
            "old_status": old_state.status.value if old_state else None,
            "new_status": new_state.status.value,
            "state": new_state.to_dict(),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        try:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            req = urllib.request.Request(
                url,
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                resp.read()
                status_code = resp.status
            self.logger.debug("webhook_delivered", {
                "url": url,
                "agent_id": agent_id,
                "status_code": status_code,
            })
        except Exception as e:  # noqa: BLE001 —— fail-open，webhook 失败不阻塞
            self.logger.error("webhook_delivery_failed", {
                "url": url,
                "agent_id": agent_id,
                "error": str(e),
            })

    # ------------------------------------------------------------------ 统计

    def stats(self) -> dict[str, Any]:
        """返回按状态分桶的统计信息。"""
        with self._lock:
            states = list(self._states.values())
            n_subscribers = len(self._subscribers)
            n_webhooks = len(self._webhooks)
        counts: dict[str, int] = {s.value: 0 for s in AgentStatus}
        for st in states:
            counts[st.status.value] = counts.get(st.status.value, 0) + 1
        return {
            "total": len(states),
            "active": counts.get("active", 0),
            "waiting": counts.get("waiting", 0),
            "finished": counts.get("finished", 0),
            "failed": counts.get("failed", 0),
            "idle": counts.get("idle", 0),
            "subscribers": n_subscribers,
            "webhooks": n_webhooks,
        }
