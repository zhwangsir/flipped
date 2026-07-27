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


class TestAddNodeEdgeCases:
    """add_node 边界与异常分支。"""

    def test_add_node_returns_existing_when_id_duplicates(self):
        kg = KnowledgeGraph()
        first = kg.add_node("s1", NodeType.skill, "First")
        second = kg.add_node("s1", NodeType.failure, "Second")
        # 同 id → 返回已存在节点，不覆盖
        assert first is second
        assert second.name == "First"
        assert second.type == NodeType.skill

    def test_add_node_with_metadata_and_description(self):
        kg = KnowledgeGraph()
        node = kg.add_node(
            "s1",
            NodeType.skill,
            "Pattern",
            description="desc",
            metadata={"k": "v"},
        )
        assert node is not None
        assert node.description == "desc"
        assert node.metadata == {"k": "v"}

    def test_add_node_exception_returns_none(self):
        kg = KnowledgeGraph()
        # 把 nodes 替换为非 dict 触发 __contains__ 异常
        kg.nodes = None  # type: ignore
        result = kg.add_node("s1", NodeType.skill, "X")
        assert result is None


class TestAddEdgeEdgeCases:
    """add_edge 边界与异常分支。"""

    def test_add_edge_returns_false_when_from_missing(self):
        kg = KnowledgeGraph()
        kg.add_node("f1", NodeType.failure, "F")
        # from_id 不存在
        assert kg.add_edge("ghost", "f1", EdgeType.related_to) is False

    def test_add_edge_returns_false_when_to_missing(self):
        kg = KnowledgeGraph()
        kg.add_node("s1", NodeType.skill, "S")
        # to_id 不存在
        assert kg.add_edge("s1", "ghost", EdgeType.related_to) is False

    def test_add_edge_returns_false_when_both_missing(self):
        kg = KnowledgeGraph()
        assert kg.add_edge("a", "b", EdgeType.related_to) is False

    def test_add_edge_exception_returns_false(self):
        kg = KnowledgeGraph()
        kg.add_node("s1", NodeType.skill, "S")
        kg.add_node("f1", NodeType.failure, "F")
        # edges 字典被破坏 → 触发异常
        kg.edges = None  # type: ignore
        assert kg.add_edge("s1", "f1", EdgeType.solved_by) is False

    def test_add_edge_with_weight(self):
        kg = KnowledgeGraph()
        kg.add_node("s1", NodeType.skill, "S")
        kg.add_node("f1", NodeType.failure, "F")
        assert kg.add_edge("s1", "f1", EdgeType.solved_by, weight=2.5) is True
        edges = kg.get_edges("s1")
        assert edges[0].weight == 2.5


class TestGetEdges:
    def test_get_edges_empty_for_unknown_node(self):
        kg = KnowledgeGraph()
        assert kg.get_edges("ghost") == []

    def test_get_edges_returns_copy(self):
        # 返回的 list 是副本，外部修改不影响内部
        kg = KnowledgeGraph()
        kg.add_node("s1", NodeType.skill, "S")
        kg.add_node("f1", NodeType.failure, "F")
        kg.add_edge("s1", "f1", EdgeType.solved_by)
        e1 = kg.get_edges("s1")
        e1.clear()
        e2 = kg.get_edges("s1")
        assert len(e2) == 1

    def test_get_edges_exception_returns_empty(self):
        kg = KnowledgeGraph()
        kg.edges = None  # type: ignore
        assert kg.get_edges("s1") == []


class TestGetNeighborsEdgeCases:
    def test_get_neighbors_includes_reverse_edges(self):
        # 仅通过 reverse_edges 关联（即别的节点指向 center）
        kg = KnowledgeGraph()
        kg.add_node("center", NodeType.skill, "Center")
        kg.add_node("a", NodeType.task, "A")
        kg.add_node("b", NodeType.pattern, "B")
        # a → center, b → center（center 是 to_id）
        kg.add_edge("a", "center", EdgeType.uses_skill)
        kg.add_edge("b", "center", EdgeType.related_to)
        neighbors = kg.get_neighbors("center")
        neighbor_ids = {n.id for n in neighbors}
        assert neighbor_ids == {"a", "b"}

    def test_get_neighbors_unknown_node_returns_empty(self):
        kg = KnowledgeGraph()
        assert kg.get_neighbors("ghost") == []

    def test_get_neighbors_combines_forward_and_reverse(self):
        kg = KnowledgeGraph()
        kg.add_node("c", NodeType.skill, "C")
        kg.add_node("fwd", NodeType.task, "F")  # c → fwd
        kg.add_node("rev", NodeType.pattern, "R")  # rev → c
        kg.add_edge("c", "fwd", EdgeType.related_to)
        kg.add_edge("rev", "c", EdgeType.uses_skill)
        neighbors = kg.get_neighbors("c")
        ids = {n.id for n in neighbors}
        assert ids == {"fwd", "rev"}

    def test_get_neighbors_exception_returns_empty(self):
        kg = KnowledgeGraph()
        kg.edges = None  # type: ignore
        assert kg.get_neighbors("c") == []


class TestFindRelatedSkillsEdgeCases:
    def test_find_related_skills_no_skills_in_graph(self):
        kg = KnowledgeGraph()
        kg.add_node("t1", NodeType.task, "T")
        kg.add_node("f1", NodeType.failure, "F")
        kg.add_edge("t1", "f1", EdgeType.caused_by)
        # 图里没有 skill 节点
        assert kg.find_related_skills("t1") == []

    def test_find_related_skills_unknown_node_returns_empty(self):
        kg = KnowledgeGraph()
        assert kg.find_related_skills("ghost") == []

    def test_find_related_skills_via_reverse_edges(self):
        # skill 节点只能通过 reverse_edges 可达
        kg = KnowledgeGraph()
        kg.add_node("f1", NodeType.failure, "F")
        kg.add_node("s1", NodeType.skill, "S")
        # f1 → s1（s1 是 to_id），从 s1 视角看是 reverse edge
        kg.add_edge("f1", "s1", EdgeType.solved_by)
        # 从 s1 出发找相关 skill → 应通过 reverse_edges 找到 f1，再从 f1 找其它 skill
        kg.add_node("s2", NodeType.skill, "S2")
        kg.add_edge("f1", "s2", EdgeType.solved_by)
        skills = kg.find_related_skills("s1")
        ids = {s.id for s in skills}
        # s2 通过 reverse(f1→s1) → f1 → forward(f1→s2) 可达
        assert "s2" in ids

    def test_find_related_skills_depth_limit(self):
        # 链长度 4+，验证 depth > 3 时不再扩展
        kg = KnowledgeGraph()
        kg.add_node("n0", NodeType.task, "N0")
        kg.add_node("n1", NodeType.task, "N1")
        kg.add_node("n2", NodeType.task, "N2")
        kg.add_node("n3", NodeType.task, "N3")
        kg.add_node("s_deep", NodeType.skill, "SDeep")
        kg.add_edge("n0", "n1", EdgeType.related_to)
        kg.add_edge("n1", "n2", EdgeType.related_to)
        kg.add_edge("n2", "n3", EdgeType.related_to)
        kg.add_edge("n3", "s_deep", EdgeType.uses_skill)
        # 从 n0 出发，s_deep 在 depth=4，超出 depth>3 限制
        skills = kg.find_related_skills("n0")
        ids = {s.id for s in skills}
        assert "s_deep" not in ids

    def test_find_related_skills_exception_returns_empty(self):
        kg = KnowledgeGraph()
        kg.nodes = None  # type: ignore
        assert kg.find_related_skills("x") == []


class TestFindPathEdgeCases:
    def test_find_path_missing_from_returns_empty(self):
        kg = KnowledgeGraph()
        kg.add_node("b", NodeType.skill, "B")
        assert kg.find_path("ghost", "b") == []

    def test_find_path_missing_to_returns_empty(self):
        kg = KnowledgeGraph()
        kg.add_node("a", NodeType.skill, "A")
        assert kg.find_path("a", "ghost") == []

    def test_find_path_same_node_returns_singleton(self):
        kg = KnowledgeGraph()
        kg.add_node("a", NodeType.skill, "A")
        assert kg.find_path("a", "a") == ["a"]

    def test_find_path_max_depth_exceeded_returns_empty(self):
        # 路径长度超过 max_depth → 返回 []
        kg = KnowledgeGraph()
        kg.add_node("a", NodeType.task, "A")
        kg.add_node("b", NodeType.task, "B")
        kg.add_node("c", NodeType.task, "C")
        kg.add_node("d", NodeType.task, "D")
        kg.add_edge("a", "b", EdgeType.related_to)
        kg.add_edge("b", "c", EdgeType.related_to)
        kg.add_edge("c", "d", EdgeType.related_to)
        # a→b→c→d 长度 4，max_depth=2 → 找不到
        assert kg.find_path("a", "d", max_depth=2) == []

    def test_find_path_via_reverse_edges(self):
        # 通过 reverse_edges 反向找路径
        kg = KnowledgeGraph()
        kg.add_node("a", NodeType.task, "A")
        kg.add_node("b", NodeType.skill, "B")
        kg.add_node("c", NodeType.failure, "C")
        # c → b → a（反向链）
        kg.add_edge("b", "a", EdgeType.uses_skill)
        kg.add_edge("c", "b", EdgeType.related_to)
        # 从 a 找 c：a -(reverse)- b -(reverse)- c
        path = kg.find_path("a", "c")
        assert path[0] == "a"
        assert path[-1] == "c"
        assert len(path) >= 3

    def test_find_path_exception_returns_empty(self):
        kg = KnowledgeGraph()
        kg.nodes = None  # type: ignore
        assert kg.find_path("a", "b") == []

    def test_find_path_no_path_returns_empty(self):
        # 两个不连通的子图
        kg = KnowledgeGraph()
        kg.add_node("a", NodeType.skill, "A")
        kg.add_node("b", NodeType.skill, "B")
        kg.add_node("c", NodeType.skill, "C")
        kg.add_node("d", NodeType.skill, "D")
        kg.add_edge("a", "b", EdgeType.related_to)
        kg.add_edge("c", "d", EdgeType.related_to)
        assert kg.find_path("a", "d") == []


class TestGetSubgraph:
    def test_get_subgraph_unknown_node_returns_empty(self):
        kg = KnowledgeGraph()
        sub = kg.get_subgraph("ghost")
        assert isinstance(sub, KnowledgeGraph)
        assert sub.nodes == {}

    def test_get_subgraph_depth_1(self):
        kg = KnowledgeGraph()
        kg.add_node("c", NodeType.skill, "C")
        kg.add_node("n1", NodeType.task, "N1")
        kg.add_node("n2", NodeType.failure, "N2")
        kg.add_node("far", NodeType.pattern, "Far")
        kg.add_edge("c", "n1", EdgeType.related_to)
        kg.add_edge("n1", "n2", EdgeType.related_to)
        kg.add_edge("n2", "far", EdgeType.related_to)
        sub = kg.get_subgraph("c", depth=1)
        # depth=1：c + 直接邻居 n1
        assert "c" in sub.nodes
        assert "n1" in sub.nodes
        # n2 在 depth=2，不应被纳入
        assert "n2" not in sub.nodes
        assert "far" not in sub.nodes

    def test_get_subgraph_depth_2(self):
        kg = KnowledgeGraph()
        kg.add_node("c", NodeType.skill, "C")
        kg.add_node("n1", NodeType.task, "N1")
        kg.add_node("n2", NodeType.failure, "N2")
        kg.add_node("far", NodeType.pattern, "Far")
        kg.add_edge("c", "n1", EdgeType.related_to)
        kg.add_edge("n1", "n2", EdgeType.related_to)
        kg.add_edge("n2", "far", EdgeType.related_to)
        sub = kg.get_subgraph("c", depth=2)
        assert "c" in sub.nodes
        assert "n1" in sub.nodes
        assert "n2" in sub.nodes
        # far 在 depth=3，不应被纳入
        assert "far" not in sub.nodes

    def test_get_subgraph_includes_edges(self):
        kg = KnowledgeGraph()
        kg.add_node("c", NodeType.skill, "C", description="d", metadata={"k": "v"})
        kg.add_node("n1", NodeType.task, "N1")
        kg.add_edge("c", "n1", EdgeType.uses_skill, weight=2.0)
        sub = kg.get_subgraph("c", depth=1)
        # 子图的边应存在
        edges = sub.get_edges("c")
        assert len(edges) == 1
        assert edges[0].type == EdgeType.uses_skill
        assert edges[0].weight == 2.0
        # 节点元数据保留
        c_node = sub.get_node("c")
        assert c_node.description == "d"
        assert c_node.metadata == {"k": "v"}

    def test_get_subgraph_exception_returns_empty(self):
        kg = KnowledgeGraph()
        kg.nodes = None  # type: ignore
        sub = kg.get_subgraph("c")
        assert isinstance(sub, KnowledgeGraph)
        assert sub.nodes == {}


class TestGetStatsEdgeCases:
    def test_get_stats_empty_graph(self):
        kg = KnowledgeGraph()
        stats = kg.get_stats()
        assert stats["node_count"] == 0
        assert stats["edge_count"] == 0
        assert stats["by_type"] == {}
        # 空图 density = 0/(max(1, 0*-1)) = 0/1 = 0
        assert stats["density"] == 0.0

    def test_get_stats_density_single_node(self):
        kg = KnowledgeGraph()
        kg.add_node("s1", NodeType.skill, "S")
        stats = kg.get_stats()
        # 1 节点 0 边 → density = 0 / max(1, 1*0) = 0/1 = 0
        assert stats["node_count"] == 1
        assert stats["edge_count"] == 0
        assert stats["density"] == 0.0

    def test_get_stats_by_type(self):
        kg = KnowledgeGraph()
        kg.add_node("s1", NodeType.skill, "S1")
        kg.add_node("s2", NodeType.skill, "S2")
        kg.add_node("f1", NodeType.failure, "F1")
        kg.add_node("t1", NodeType.task, "T1")
        stats = kg.get_stats()
        assert stats["by_type"]["skill"] == 2
        assert stats["by_type"]["failure"] == 1
        assert stats["by_type"]["task"] == 1

    def test_get_stats_exception_returns_minimal(self):
        # 让 self.edges.values() 抛异常（edges=None），但 self.nodes 仍可用
        # → except 分支执行 len(self.nodes) 成功，返回 {"node_count": N, "edge_count": 0}
        kg = KnowledgeGraph()
        kg.add_node("s1", NodeType.skill, "S1")
        kg.add_node("s2", NodeType.failure, "S2")
        kg.edges = None  # type: ignore
        stats = kg.get_stats()
        assert stats["node_count"] == 2
        assert stats["edge_count"] == 0
        # 异常分支不返回 by_type / density
        assert "by_type" not in stats
        assert "density" not in stats
