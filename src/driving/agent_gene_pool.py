"""M120 · Agent 基因池 + 优胜劣汰。

Agent Gene Pool = 维护多个不同策略的 agent 基因（参数组合），
用进化论思路自动优化系统配置：
- 选择(selection): 好的基因留下，差的淘汰
- 变异(mutation): 对参数做小幅度随机调整
- 繁衍(crossover): 两个好基因组合，产生新基因
- 进化(evolve): 一代一代迭代优化

fail-open: 异常时返回原始基因池。
"""
from __future__ import annotations

import random
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class SelectionStrategy(str, Enum):
    top_n = "top_n"
    tournament = "tournament"
    roulette = "roulette"


@dataclass
class AgentGene:
    """Agent 基因 = 一组参数配置 + 适应度评分。"""
    gene_id: str
    name: str
    params: dict[str, Any]
    fitness: float = 0.5
    generation: int = 0
    wins: int = 0
    losses: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


@dataclass
class GenePool:
    """基因池 = 所有基因的集合 + 进化操作。"""
    genes: list[AgentGene] = field(default_factory=list)
    generation: int = 0
    history: list[dict[str, Any]] = field(default_factory=list)

    def add_gene(
        self,
        gene_id: str,
        name: str,
        params: dict[str, Any],
        *,
        fitness: float = 0.5,
    ) -> AgentGene | None:
        """添加一个基因。"""
        try:
            gene = AgentGene(
                gene_id=gene_id,
                name=name,
                params=dict(params),
                fitness=fitness,
            )
            self.genes.append(gene)
            return gene
        except Exception:
            return None

    def get_gene(self, gene_id: str) -> AgentGene | None:
        """获取基因。"""
        for g in self.genes:
            if g.gene_id == gene_id:
                return g
        return None

    def update_fitness(self, gene_id: str, fitness: float) -> bool:
        """更新基因适应度。"""
        try:
            g = self.get_gene(gene_id)
            if g:
                g.fitness = max(0.0, min(1.0, fitness))
                return True
            return False
        except Exception:
            return False

    def select_top(self, n: int) -> list[AgentGene]:
        """选择适应度最高的 n 个基因。"""
        try:
            sorted_genes = sorted(self.genes, key=lambda g: g.fitness, reverse=True)
            return sorted_genes[:n]
        except Exception:
            return []

    def evolve(
        self,
        *,
        survival_rate: float = 0.5,
        mutation_rate: float = 0.3,
        crossover_rate: float = 0.5,
        min_population: int = 4,
        max_population: int = 20,
    ) -> "GenePool":
        """进化一代。

        1. 选择：适应度高的存活
        2. 变异：存活的基因有概率变异
        3. 繁衍：好基因配对产生后代
        4. 返回新一代基因池
        """
        try:
            if len(self.genes) < 2:
                return self

            survivors_count = max(
                min_population,
                int(len(self.genes) * survival_rate),
            )
            survivors = self.select_top(survivors_count)

            new_genes: list[AgentGene] = []
            for g in survivors:
                new_genes.append(g)

            for i, g in enumerate(survivors):
                if random.random() < mutation_rate:
                    mutated = mutate_gene(g, mutation_rate=mutation_rate)
                    mutated.generation = self.generation + 1
                    new_genes.append(mutated)

            if len(survivors) >= 2 and len(new_genes) < max_population:
                for i in range(0, len(survivors) - 1, 2):
                    if random.random() < crossover_rate:
                        child = crossover_genes(survivors[i], survivors[i + 1])
                        child.generation = self.generation + 1
                        new_genes.append(child)
                        if len(new_genes) >= max_population:
                            break

            new_pool = GenePool(
                genes=new_genes[:max_population],
                generation=self.generation + 1,
                history=self.history + [{
                    "generation": self.generation + 1,
                    "population": len(new_genes),
                    "avg_fitness": sum(g.fitness for g in new_genes) / max(1, len(new_genes)),
                    "top_fitness": max((g.fitness for g in new_genes), default=0.0),
                }],
            )
            return new_pool
        except Exception:
            return self

    def get_stats(self) -> dict[str, Any]:
        """获取基因池统计。"""
        try:
            if not self.genes:
                return {"population": 0, "generation": self.generation}
            fitnesses = [g.fitness for g in self.genes]
            return {
                "population": len(self.genes),
                "generation": self.generation,
                "avg_fitness": round(sum(fitnesses) / len(fitnesses), 3),
                "max_fitness": round(max(fitnesses), 3),
                "min_fitness": round(min(fitnesses), 3),
            }
        except Exception:
            return {"population": len(self.genes), "generation": self.generation}


def mutate_gene(
    gene: AgentGene,
    *,
    mutation_rate: float = 0.3,
    mutation_strength: float = 0.1,
) -> AgentGene:
    """基因突变：对参数做随机微调。"""
    try:
        new_params = dict(gene.params)
        for key, val in new_params.items():
            if random.random() < mutation_rate:
                if isinstance(val, float):
                    delta = random.uniform(-mutation_strength, mutation_strength) * val
                    new_params[key] = round(max(0.0, val + delta), 4)
                elif isinstance(val, int):
                    delta = random.randint(-1, 1)
                    new_params[key] = max(0, val + delta)
                elif isinstance(val, bool):
                    new_params[key] = not val
        new_id = f"gene-{uuid.uuid4().hex[:8]}"
        return AgentGene(
            gene_id=new_id,
            name=f"{gene.name}_mut",
            params=new_params,
            fitness=gene.fitness,
            generation=gene.generation,
        )
    except Exception:
        return gene


def crossover_genes(parent_a: AgentGene, parent_b: AgentGene) -> AgentGene:
    """基因交叉：两个父基因组合产生后代。"""
    try:
        child_params: dict[str, Any] = {}
        all_keys = set(parent_a.params.keys()) | set(parent_b.params.keys())
        for key in all_keys:
            if key in parent_a.params and key in parent_b.params:
                child_params[key] = random.choice([
                    parent_a.params[key],
                    parent_b.params[key],
                ])
            elif key in parent_a.params:
                child_params[key] = parent_a.params[key]
            else:
                child_params[key] = parent_b.params[key]
        child_fitness = (parent_a.fitness + parent_b.fitness) / 2
        new_id = f"gene-{uuid.uuid4().hex[:8]}"
        return AgentGene(
            gene_id=new_id,
            name=f"{parent_a.name}_{parent_b.name}",
            params=child_params,
            fitness=child_fitness,
            generation=max(parent_a.generation, parent_b.generation),
        )
    except Exception:
        return parent_a
