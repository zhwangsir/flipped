"""M117 · 任务 DAG 依赖图 + 并行调度。

DAG = Directed Acyclic Graph，任务间有依赖关系的有向无环图。
- 拓扑排序：确定执行顺序
- 并行分组：无依赖的任务可以同时执行
- 关键路径：决定总时长的最长路径

fail-open: 异常时返回空列表或保守估计。
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any


@dataclass
class DAGNode:
    """DAG 节点 = 一个任务。"""
    id: str
    name: str
    duration: float = 1.0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class TaskDAG:
    """任务依赖图。"""
    nodes: dict[str, DAGNode] = field(default_factory=dict)
    edges: dict[str, list[str]] = field(default_factory=dict)
    reverse_edges: dict[str, list[str]] = field(default_factory=dict)

    def add_node(self, node_id: str, name: str = "", duration: float = 1.0) -> None:
        """添加节点。"""
        try:
            if node_id not in self.nodes:
                self.nodes[node_id] = DAGNode(id=node_id, name=name or node_id, duration=duration)
                self.edges[node_id] = []
                self.reverse_edges[node_id] = []
        except Exception:
            pass

    def add_edge(self, from_id: str, to_id: str) -> bool:
        """添加依赖边：from_id 必须先完成，to_id 才能开始。"""
        try:
            if from_id not in self.nodes or to_id not in self.nodes:
                return False
            if to_id not in self.edges[from_id]:
                self.edges[from_id].append(to_id)
            if from_id not in self.reverse_edges[to_id]:
                self.reverse_edges[to_id].append(from_id)
            return True
        except Exception:
            return False

    def get_node(self, node_id: str) -> DAGNode | None:
        """获取节点。"""
        return self.nodes.get(node_id)

    @property
    def size(self) -> int:
        return len(self.nodes)


def topo_sort(dag: TaskDAG) -> list[str]:
    """拓扑排序（Kahn 算法）。有环返回空列表。"""
    try:
        in_degree = {nid: 0 for nid in dag.nodes}
        for from_id, tos in dag.edges.items():
            for to_id in tos:
                if to_id in in_degree:
                    in_degree[to_id] += 1

        queue = deque([nid for nid, d in in_degree.items() if d == 0])
        result = []

        while queue:
            node = queue.popleft()
            result.append(node)
            for neighbor in dag.edges.get(node, []):
                if neighbor in in_degree:
                    in_degree[neighbor] -= 1
                    if in_degree[neighbor] == 0:
                        queue.append(neighbor)

        if len(result) != len(dag.nodes):
            return []
        return result
    except Exception:
        return []


def find_parallel_groups(dag: TaskDAG) -> list[list[str]]:
    """找出可以并行执行的任务分组。

    每一组内的任务互不依赖，可以同时执行。
    """
    try:
        order = topo_sort(dag)
        if not order:
            return []

        completed: set[str] = set()
        groups: list[list[str]] = []
        remaining = set(order)

        while remaining:
            ready = []
            for nid in order:
                if nid not in remaining:
                    continue
                deps = dag.reverse_edges.get(nid, [])
                if all(d in completed for d in deps):
                    ready.append(nid)
            if not ready:
                break
            groups.append(ready)
            for nid in ready:
                completed.add(nid)
                remaining.discard(nid)

        return groups
    except Exception:
        return []


def find_critical_path(dag: TaskDAG) -> tuple[list[str], float]:
    """找关键路径（最长路径），决定总工期。

    返回 (路径节点列表, 总时长)。
    """
    try:
        order = topo_sort(dag)
        if not order:
            return [], 0.0

        earliest: dict[str, float] = {}
        prev: dict[str, str | None] = {}

        for nid in order:
            node = dag.get_node(nid)
            dur = node.duration if node else 1.0
            deps = dag.reverse_edges.get(nid, [])
            if not deps:
                earliest[nid] = dur
                prev[nid] = None
            else:
                max_pred = max(deps, key=lambda d: earliest.get(d, 0))
                earliest[nid] = earliest.get(max_pred, 0) + dur
                prev[nid] = max_pred

        if not earliest:
            return [], 0.0

        end_node = max(earliest, key=earliest.get)
        total = earliest[end_node]

        path = []
        current: str | None = end_node
        while current is not None:
            path.append(current)
            current = prev.get(current)
        path.reverse()

        return path, round(total, 2)
    except Exception:
        return [], 0.0
