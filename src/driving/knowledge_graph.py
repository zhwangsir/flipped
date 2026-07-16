"""M121 · 跨任务知识图谱。

Knowledge Graph = 把 Skill、Failure、Experience 串成关联图谱，
而不是各自孤立的向量检索。

节点类型：skill / failure / task / pattern / experience
边类型：solved_by / caused_by / related_to / composed_of / uses_skill

支持：
- 图遍历：找相关节点
- 路径推理：A → B → C 的关联路径
- 子图提取：围绕一个节点的相关知识子图

fail-open: 异常时返回空结果。
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class NodeType(str, Enum):
    skill = "skill"
    failure = "failure"
    task = "task"
    pattern = "pattern"
    experience = "experience"


class EdgeType(str, Enum):
    solved_by = "solved_by"
    caused_by = "caused_by"
    related_to = "related_to"
    composed_of = "composed_of"
    uses_skill = "uses_skill"
    improves = "improves"


@dataclass
class KGNode:
    """知识图谱节点。"""
    id: str
    type: NodeType
    name: str
    description: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class KGEdge:
    """知识图谱边。"""
    from_id: str
    to_id: str
    type: EdgeType
    weight: float = 1.0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class KnowledgeGraph:
    """跨任务知识图谱。"""
    nodes: dict[str, KGNode] = field(default_factory=dict)
    edges: dict[str, list[KGEdge]] = field(default_factory=dict)
    reverse_edges: dict[str, list[KGEdge]] = field(default_factory=dict)

    def add_node(
        self,
        node_id: str,
        node_type: NodeType,
        name: str,
        *,
        description: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> KGNode | None:
        """添加节点。"""
        try:
            if node_id in self.nodes:
                return self.nodes[node_id]
            node = KGNode(
                id=node_id,
                type=node_type,
                name=name,
                description=description,
                metadata=metadata or {},
            )
            self.nodes[node_id] = node
            self.edges[node_id] = []
            self.reverse_edges[node_id] = []
            return node
        except Exception:
            return None

    def add_edge(
        self,
        from_id: str,
        to_id: str,
        edge_type: EdgeType,
        *,
        weight: float = 1.0,
    ) -> bool:
        """添加边。"""
        try:
            if from_id not in self.nodes or to_id not in self.nodes:
                return False
            edge = KGEdge(from_id=from_id, to_id=to_id, type=edge_type, weight=weight)
            self.edges[from_id].append(edge)
            self.reverse_edges[to_id].append(edge)
            return True
        except Exception:
            return False

    def get_node(self, node_id: str) -> KGNode | None:
        """获取节点。"""
        return self.nodes.get(node_id)

    def get_edges(self, node_id: str) -> list[KGEdge]:
        """获取从某节点出发的所有边。"""
        try:
            return list(self.edges.get(node_id, []))
        except Exception:
            return []

    def get_neighbors(self, node_id: str) -> list[KGNode]:
        """获取直接相邻节点。"""
        try:
            neighbors = []
            for edge in self.edges.get(node_id, []):
                n = self.nodes.get(edge.to_id)
                if n:
                    neighbors.append(n)
            for edge in self.reverse_edges.get(node_id, []):
                n = self.nodes.get(edge.from_id)
                if n:
                    neighbors.append(n)
            return neighbors
        except Exception:
            return []

    def find_related_skills(self, node_id: str) -> list[KGNode]:
        """找出与某节点相关的所有 Skill。"""
        try:
            skills = []
            visited = set()
            queue = deque([(node_id, 0)])
            visited.add(node_id)

            while queue:
                current, depth = queue.popleft()
                if depth > 3:
                    continue
                node = self.nodes.get(current)
                if node and node.type == NodeType.skill and current != node_id:
                    skills.append(node)
                for edge in self.edges.get(current, []):
                    if edge.to_id not in visited:
                        visited.add(edge.to_id)
                        queue.append((edge.to_id, depth + 1))
                for edge in self.reverse_edges.get(current, []):
                    if edge.from_id not in visited:
                        visited.add(edge.from_id)
                        queue.append((edge.from_id, depth + 1))

            return skills
        except Exception:
            return []

    def find_path(
        self,
        from_id: str,
        to_id: str,
        *,
        max_depth: int = 5,
    ) -> list[str]:
        """BFS 找两个节点之间的最短路径。"""
        try:
            if from_id not in self.nodes or to_id not in self.nodes:
                return []
            if from_id == to_id:
                return [from_id]

            visited = {from_id: None}
            queue = deque([(from_id, 0)])

            while queue:
                current, depth = queue.popleft()
                if depth >= max_depth:
                    continue
                if current == to_id:
                    break
                for edge in self.edges.get(current, []):
                    if edge.to_id not in visited:
                        visited[edge.to_id] = current
                        queue.append((edge.to_id, depth + 1))
                for edge in self.reverse_edges.get(current, []):
                    if edge.from_id not in visited:
                        visited[edge.from_id] = current
                        queue.append((edge.from_id, depth + 1))

            if to_id not in visited:
                return []

            path = []
            current: str | None = to_id
            while current is not None:
                path.append(current)
                current = visited.get(current)
            path.reverse()
            return path
        except Exception:
            return []

    def get_subgraph(self, node_id: str, *, depth: int = 2) -> "KnowledgeGraph":
        """提取以某节点为中心的子图。"""
        try:
            sub = KnowledgeGraph()
            if node_id not in self.nodes:
                return sub

            visited = set()
            queue = deque([(node_id, 0)])
            visited.add(node_id)

            while queue:
                current, d = queue.popleft()
                if d >= depth:
                    continue
                node = self.nodes.get(current)
                if node:
                    sub.add_node(node.id, node.type, node.name, description=node.description, metadata=node.metadata)
                for edge in self.edges.get(current, []):
                    if edge.to_id not in visited:
                        visited.add(edge.to_id)
                        queue.append((edge.to_id, d + 1))
                    to_node = self.nodes.get(edge.to_id)
                    if to_node:
                        sub.add_node(to_node.id, to_node.type, to_node.name, description=to_node.description, metadata=to_node.metadata)
                        sub.add_edge(current, edge.to_id, edge.type, weight=edge.weight)

            return sub
        except Exception:
            return KnowledgeGraph()

    def get_stats(self) -> dict[str, Any]:
        """获取图谱统计信息。"""
        try:
            by_type: dict[str, int] = {}
            for node in self.nodes.values():
                t = node.type.value
                by_type[t] = by_type.get(t, 0) + 1
            total_edges = sum(len(e) for e in self.edges.values())
            return {
                "node_count": len(self.nodes),
                "edge_count": total_edges,
                "by_type": by_type,
                "density": round(
                    total_edges / max(1, len(self.nodes) * (len(self.nodes) - 1)),
                    4,
                ),
            }
        except Exception:
            return {"node_count": len(self.nodes), "edge_count": 0}
