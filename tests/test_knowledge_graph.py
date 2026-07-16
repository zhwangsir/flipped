"""M121 · 跨任务知识图谱 测试。

Knowledge Graph = 把 Skill、Failure、Experience 串成关联图谱，
而不是各自孤立的向量检索。支持：
- 节点：Skill / Failure / Task / Pattern
- 边：solved_by, caused_by, related_to, composed_of
- 推理路径：给定一个问题，找出"相关 Skill → 解决过的类似失败 → 最佳实践"的路径
"""
from __future__ import annotations

from driving.knowledge_graph import (
    KGNode,
    KGEdge,
    KnowledgeGraph,
    NodeType,
    EdgeType,
)


class TestKGNode:
    def test_node_has_fields(self):
        n = KGNode(id="s1", type=NodeType.skill, name="landing_page")
        assert n.id == "s1"
        assert n.type == NodeType.skill


class TestKnowledgeGraph:
    def test_add_node(self):
        kg = KnowledgeGraph()
        kg.add_node("s1", NodeType.skill, "Landing Page Pattern")
        kg.add_node("f1", NodeType.failure, "CSS not applied")
        assert kg.get_node("s1") is not None
        assert kg.get_node("f1") is not None

    def test_add_edge(self):
        kg = KnowledgeGraph()
        kg.add_node("s1", NodeType.skill, "Pattern A")
        kg.add_node("f1", NodeType.failure, "Failure B")
        kg.add_edge("s1", "f1", EdgeType.solved_by)
        edges = kg.get_edges("s1")
        assert len(edges) >= 1

    def test_find_related_skills_for_failure(self):
        kg = KnowledgeGraph()
        kg.add_node("f1", NodeType.failure, "layout broken")
        kg.add_node("s1", NodeType.skill, "Flexbox Pattern")
        kg.add_node("s2", NodeType.skill, "Grid Pattern")
        kg.add_edge("f1", "s1", EdgeType.solved_by)
        kg.add_edge("f1", "s2", EdgeType.solved_by)
        skills = kg.find_related_skills("f1")
        assert len(skills) >= 2

    def test_find_path_between_nodes(self):
        kg = KnowledgeGraph()
        kg.add_node("a", NodeType.task, "Task A")
        kg.add_node("b", NodeType.skill, "Skill B")
        kg.add_node("c", NodeType.failure, "Failure C")
        kg.add_edge("a", "b", EdgeType.uses_skill)
        kg.add_edge("b", "c", EdgeType.solved_by)
        path = kg.find_path("a", "c")
        assert len(path) >= 3
        assert path[0] == "a"
        assert path[-1] == "c"

    def test_get_neighbors(self):
        kg = KnowledgeGraph()
        kg.add_node("center", NodeType.skill, "Center")
        kg.add_node("n1", NodeType.skill, "N1")
        kg.add_node("n2", NodeType.failure, "N2")
        kg.add_edge("center", "n1", EdgeType.related_to)
        kg.add_edge("center", "n2", EdgeType.solved_by)
        neighbors = kg.get_neighbors("center")
        assert len(neighbors) == 2

    def test_no_path_returns_empty(self):
        kg = KnowledgeGraph()
        kg.add_node("a", NodeType.skill, "A")
        kg.add_node("b", NodeType.failure, "B")
        path = kg.find_path("a", "b")
        assert path == []

    def test_get_stats(self):
        kg = KnowledgeGraph()
        kg.add_node("s1", NodeType.skill, "S1")
        kg.add_node("s2", NodeType.skill, "S2")
        kg.add_node("f1", NodeType.failure, "F1")
        kg.add_edge("s1", "f1", EdgeType.solved_by)
        stats = kg.get_stats()
        assert stats["node_count"] == 3
        assert stats["edge_count"] == 1
        assert "by_type" in stats
