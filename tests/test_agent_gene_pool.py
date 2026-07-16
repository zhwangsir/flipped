"""M120 · Agent 基因池 + 优胜劣汰 测试。

Agent Gene Pool = 维护多个不同策略的 agent 基因（参数组合），
用进化论思路优化：选择(好的留下) → 变异(参数微调) → 繁衍(好的组合) → 淘汰(差的移除)
"""
from __future__ import annotations

from driving.agent_gene_pool import (
    AgentGene,
    GenePool,
    SelectionStrategy,
    mutate_gene,
    crossover_genes,
)


class TestAgentGene:
    def test_gene_has_fields(self):
        g = AgentGene(
            gene_id="g1",
            name="balanced",
            params={"temperature": 0.7, "max_iterations": 5},
            fitness=0.8,
        )
        assert g.gene_id == "g1"
        assert g.params["temperature"] == 0.7
        assert g.fitness == 0.8


class TestGenePool:
    def test_add_and_list_genes(self):
        pool = GenePool()
        pool.add_gene("g1", "fast", {"temperature": 0.5, "max_iterations": 3})
        pool.add_gene("g2", "quality", {"temperature": 0.2, "max_iterations": 8})
        assert len(pool.genes) == 2

    def test_select_top_n(self):
        pool = GenePool()
        pool.add_gene("g1", "a", {}, fitness=0.9)
        pool.add_gene("g2", "b", {}, fitness=0.7)
        pool.add_gene("g3", "c", {}, fitness=0.5)
        pool.add_gene("g4", "d", {}, fitness=0.3)
        top = pool.select_top(2)
        assert len(top) == 2
        assert top[0].gene_id == "g1"
        assert top[1].gene_id == "g2"

    def test_evolve_generation(self):
        pool = GenePool()
        pool.add_gene("g1", "a", {"temp": 0.5}, fitness=0.9)
        pool.add_gene("g2", "b", {"temp": 0.3}, fitness=0.8)
        pool.add_gene("g3", "c", {"temp": 0.7}, fitness=0.6)
        pool.add_gene("g4", "d", {"temp": 0.1}, fitness=0.4)
        new_pool = pool.evolve(survival_rate=0.5, mutation_rate=0.3)
        assert new_pool is not None
        assert len(new_pool.genes) > 0

    def test_update_fitness(self):
        pool = GenePool()
        pool.add_gene("g1", "test", {}, fitness=0.5)
        pool.update_fitness("g1", 0.9)
        g = pool.get_gene("g1")
        assert g is not None
        assert g.fitness == 0.9


class TestMutateGene:
    def test_mutate_changes_params(self):
        g = AgentGene(gene_id="g1", name="orig", params={"temp": 0.5, "iters": 5}, fitness=0.7)
        mutated = mutate_gene(g, mutation_rate=1.0)
        assert mutated.gene_id != g.gene_id
        assert "temp" in mutated.params
        assert mutated.params["temp"] != 0.5 or mutated.params["iters"] != 5


class TestCrossoverGenes:
    def test_crossover_combines_params(self):
        g1 = AgentGene(gene_id="a", name="a", params={"temp": 0.2, "iters": 3}, fitness=0.8)
        g2 = AgentGene(gene_id="b", name="b", params={"temp": 0.8, "iters": 7}, fitness=0.7)
        child = crossover_genes(g1, g2)
        assert child.gene_id not in ("a", "b")
        assert "temp" in child.params
        assert "iters" in child.params
