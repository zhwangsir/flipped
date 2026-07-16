"""M117 · 任务 DAG 依赖图 + 并行调度 测试。

DAG = Directed Acyclic Graph，任务间有依赖关系的有向无环图。
- 拓扑排序：确定执行顺序
- 并行调度：无依赖的任务可以同时执行
- 关键路径：决定总时长的最长路径
"""
from __future__ import annotations

from driving.task_dag import (
    DAGNode,
    TaskDAG,
    topo_sort,
    find_parallel_groups,
    find_critical_path,
)


class TestDAGNode:
    def test_node_has_fields(self):
        n = DAGNode(id="n1", name="build ui", duration=5)
        assert n.id == "n1"
        assert n.duration == 5


class TestTopoSort:
    def test_simple_dag(self):
        dag = TaskDAG()
        dag.add_node("a", "task A", 1)
        dag.add_node("b", "task B", 1)
        dag.add_node("c", "task C", 1)
        dag.add_edge("a", "b")
        dag.add_edge("b", "c")
        order = topo_sort(dag)
        assert len(order) == 3
        assert order[0] == "a"
        assert order[-1] == "c"

    def test_diamond_dag(self):
        dag = TaskDAG()
        dag.add_node("a", "A", 1)
        dag.add_node("b1", "B1", 1)
        dag.add_node("b2", "B2", 1)
        dag.add_node("c", "C", 1)
        dag.add_edge("a", "b1")
        dag.add_edge("a", "b2")
        dag.add_edge("b1", "c")
        dag.add_edge("b2", "c")
        order = topo_sort(dag)
        assert len(order) == 4
        assert order[0] == "a"
        assert order[-1] == "c"

    def test_cycle_detection(self):
        dag = TaskDAG()
        dag.add_node("a", "A", 1)
        dag.add_node("b", "B", 1)
        dag.add_edge("a", "b")
        dag.add_edge("b", "a")
        result = topo_sort(dag)
        assert result == []


class TestParallelGroups:
    def test_parallel_groups_diamond(self):
        dag = TaskDAG()
        dag.add_node("a", "A", 1)
        dag.add_node("b1", "B1", 1)
        dag.add_node("b2", "B2", 1)
        dag.add_node("c", "C", 1)
        dag.add_edge("a", "b1")
        dag.add_edge("a", "b2")
        dag.add_edge("b1", "c")
        dag.add_edge("b2", "c")
        groups = find_parallel_groups(dag)
        assert len(groups) >= 3
        assert len(groups[0]) == 1
        mid_group = [g for g in groups if len(g) == 2]
        assert len(mid_group) >= 1

    def test_linear_chain_no_parallel(self):
        dag = TaskDAG()
        dag.add_node("a", "A", 1)
        dag.add_node("b", "B", 1)
        dag.add_node("c", "C", 1)
        dag.add_edge("a", "b")
        dag.add_edge("b", "c")
        groups = find_parallel_groups(dag)
        for g in groups:
            assert len(g) == 1


class TestCriticalPath:
    def test_critical_path_linear(self):
        dag = TaskDAG()
        dag.add_node("a", "A", 2)
        dag.add_node("b", "B", 3)
        dag.add_node("c", "C", 1)
        dag.add_edge("a", "b")
        dag.add_edge("b", "c")
        path, total = find_critical_path(dag)
        assert total == 6
        assert len(path) == 3

    def test_critical_path_diamond(self):
        dag = TaskDAG()
        dag.add_node("a", "A", 1)
        dag.add_node("b1", "B1", 5)
        dag.add_node("b2", "B2", 2)
        dag.add_node("c", "C", 1)
        dag.add_edge("a", "b1")
        dag.add_edge("a", "b2")
        dag.add_edge("b1", "c")
        dag.add_edge("b2", "c")
        path, total = find_critical_path(dag)
        assert total == 7
        assert "b1" in path
