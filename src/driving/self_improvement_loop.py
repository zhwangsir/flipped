"""M123 · 自我超越循环。

Self-Improvement Loop = 对比→反馈→优化→再对比 的闭环，
目标是让 flipped 系统产出质量持续超越基准（监督者）。

循环流程：
1. 生成：flipped 和 基准 各生成一份产出
2. 对比：多维度质量对比
3. 分析：差距分析 + 根因定位
4. 优化：生成改进策略并应用
5. 再对比：验证改进效果
6. 循环：直到 flipped 连续 N 次胜出

fail-open: 异常时返回安全状态，不阻塞。
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from driving.errors import ConfigurationError, LoopError


def _gain_for_weakness(overall_gap: float, dim: str) -> int:
    """根据差距和维度计算确定性预期增益。"""
    base = min(10, max(3, int(abs(overall_gap) / 3)))
    dim_offset = hash(dim) % 3
    return base + dim_offset


def _gain_for_strength(overall_gap: float) -> int:
    """计算确定性优势利用增益。"""
    return min(4, max(1, int(abs(overall_gap) / 10) + 1))


@dataclass
class LoopIteration:
    """一轮循环的结果。"""
    iteration: int
    winner: str
    flipped_score: float
    baseline_score: float
    gap: float
    strategies_applied: list[str] = field(default_factory=list)
    dimensions_improved: list[str] = field(default_factory=list)
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def __post_init__(self) -> None:
        if not isinstance(self.iteration, int) or self.iteration <= 0:
            raise ConfigurationError(
                f"iteration must be a positive int, got {self.iteration}",
                context={"iteration": self.iteration},
            )
        if self.winner not in ("flipped", "baseline", "tie"):
            raise ConfigurationError(
                f"winner must be 'flipped', 'baseline' or 'tie', got {self.winner}",
                context={"winner": self.winner},
            )


@dataclass
class ImprovementStrategy:
    """改进策略生成器。"""

    @staticmethod
    def generate_from_gap(
        weakest_dimensions: list[str],
        strongest_dimensions: list[str],
        overall_gap: float,
        *,
        max_strategies: int = 5,
    ) -> list[dict[str, Any]]:
        """根据差距分析生成改进策略。

        expected_gain 由差距和维度名确定性计算，无随机性。
        """
        try:
            strategies = []

            for dim in weakest_dimensions[:max_strategies]:
                impact = "high" if abs(overall_gap) > 10 else "medium"
                effort = "medium" if dim in ("design", "creativity") else "low"
                strategies.append({
                    "dimension": dim,
                    "action": f"improve_{dim}",
                    "impact": impact,
                    "effort": effort,
                    "expected_gain": _gain_for_weakness(overall_gap, dim),
                    "priority": 0,
                })

            if strongest_dimensions:
                strategies.append({
                    "dimension": strongest_dimensions[0],
                    "action": "leverage_strength",
                    "impact": "medium",
                    "effort": "low",
                    "expected_gain": _gain_for_strength(overall_gap),
                    "priority": 0,
                })

            return ImprovementStrategy.prioritize(strategies)
        except Exception:
            return []

    @staticmethod
    def prioritize(strategies: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """按性价比（impact/effort）排序策略。"""
        try:
            impact_map = {"high": 3, "medium": 2, "low": 1}
            effort_map = {"high": 3, "medium": 2, "low": 1}

            for i, s in enumerate(strategies):
                imp = impact_map.get(s.get("impact", "medium"), 2)
                eff = effort_map.get(s.get("effort", "medium"), 2)
                s["priority"] = round(imp / max(1, eff) + s.get("expected_gain", 0) * 0.1, 3)

            strategies.sort(key=lambda s: s["priority"], reverse=True)
            return strategies
        except Exception:
            return strategies


@dataclass
class SelfImprovementLoop:
    """自我超越循环引擎。

    rng: 可注入的 random.Random 实例，用于测试时固定种子。
    """
    target_win_rate: float = 0.7
    max_iterations: int = 20
    required_consecutive_wins: int = 3
    dimensions: list[str] = field(default_factory=lambda: [
        "correctness", "completeness", "code_quality", "design", "efficiency", "creativity"
    ])
    rng: random.Random = field(default_factory=random.Random)

    def __post_init__(self) -> None:
        if not (0 < self.target_win_rate <= 1):
            raise ConfigurationError(
                f"target_win_rate must be in (0, 1], got {self.target_win_rate}",
                context={"target_win_rate": self.target_win_rate},
            )
        if self.max_iterations <= 0:
            raise ConfigurationError(
                f"max_iterations must be positive, got {self.max_iterations}",
                context={"max_iterations": self.max_iterations},
            )
        if self.required_consecutive_wins <= 0:
            raise ConfigurationError(
                f"required_consecutive_wins must be positive, got {self.required_consecutive_wins}",
                context={"required_consecutive_wins": self.required_consecutive_wins},
            )
        if not self.dimensions:
            raise ConfigurationError("dimensions must not be empty")

    def to_dict(self) -> dict[str, Any]:
        """序列化为可 JSON 序列化的 dict（rng 不可序列化，仅保存类型标识）。"""
        return {
            "target_win_rate": self.target_win_rate,
            "max_iterations": self.max_iterations,
            "required_consecutive_wins": self.required_consecutive_wins,
            "dimensions": list(self.dimensions),
            "rng_type": self.rng.__class__.__name__,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SelfImprovementLoop":
        """从 dict 反序列化。rng 使用默认实例。"""
        return cls(
            target_win_rate=data.get("target_win_rate", 0.7),
            max_iterations=data.get("max_iterations", 20),
            required_consecutive_wins=data.get("required_consecutive_wins", 3),
            dimensions=list(data.get("dimensions", [
                "correctness", "completeness", "code_quality", "design", "efficiency", "creativity"
            ])),
        )

    def run(
        self,
        *,
        initial_flipped_score: float = 70.0,
        initial_baseline_score: float = 85.0,
        improvement_per_round: float = 5.0,
        variance: float = 2.0,
    ) -> dict[str, Any]:
        """运行自我改进循环。

        模拟每轮改进后质量提升，直到达到目标或达到最大轮数。
        所有抖动由注入的 rng 产生，保证可复现性。
        """
        try:
            history: list[LoopIteration] = []
            flipped_score = initial_flipped_score
            baseline_score = initial_baseline_score
            target_reached = False
            consecutive_wins = 0

            for i in range(1, self.max_iterations + 1):
                flipped_variance = self.rng.uniform(-variance, variance)
                baseline_variance = self.rng.uniform(-variance, variance)
                f_score = round(flipped_score + flipped_variance, 2)
                b_score = round(baseline_score + baseline_variance, 2)

                if f_score > b_score + 1:
                    winner = "flipped"
                    consecutive_wins += 1
                elif b_score > f_score + 1:
                    winner = "baseline"
                    consecutive_wins = 0
                else:
                    winner = "tie"
                    consecutive_wins = 0

                gap = round(f_score - b_score, 2)

                strategies = []
                if winner != "flipped":
                    # 按固定顺序取前 2 个维度（避免随机），确保确定性
                    strategies = [f"improve_{d}" for d in self.dimensions[:2]]

                history.append(LoopIteration(
                    iteration=i,
                    winner=winner,
                    flipped_score=f_score,
                    baseline_score=b_score,
                    gap=gap,
                    strategies_applied=strategies,
                ))

                if consecutive_wins >= self.required_consecutive_wins:
                    target_reached = True
                    break

                flipped_score += improvement_per_round * (0.8 + self.rng.random() * 0.4)

            wins = sum(1 for h in history if h.winner == "flipped")
            win_rate = wins / max(1, len(history))

            return {
                "total_iterations": len(history),
                "target_reached": target_reached,
                "final_win_rate": round(win_rate, 3),
                "final_flipped_score": round(flipped_score, 2),
                "final_baseline_score": round(baseline_score, 2),
                "final_gap": round(flipped_score - baseline_score, 2),
                "consecutive_wins": consecutive_wins,
                "history": history,
            }
        except Exception:
            return {
                "total_iterations": 0,
                "target_reached": False,
                "final_win_rate": 0.0,
                "history": [],
                "error": "loop execution failed",
            }


def check_surpass_threshold(
    iterations: list[LoopIteration],
    *,
    required_consecutive: int = 3,
) -> dict[str, Any]:
    """检查是否已超越基准（连续 N 次胜出）。"""
    try:
        consecutive = 0
        max_consecutive = 0

        for it in iterations:
            if it.winner == "flipped":
                consecutive += 1
                max_consecutive = max(max_consecutive, consecutive)
            else:
                consecutive = 0

        surpassed = max_consecutive >= required_consecutive

        return {
            "surpassed": surpassed,
            "consecutive_wins": max_consecutive,
            "required": required_consecutive,
            "total_wins": sum(1 for it in iterations if it.winner == "flipped"),
            "total_iterations": len(iterations),
        }
    except Exception:
        return {"surpassed": False, "consecutive_wins": 0, "required": required_consecutive}


def run_improvement_cycle(
    task_description: str,
    *,
    initial_flipped_score: float = 70.0,
    initial_baseline_score: float = 85.0,
    max_cycles: int = 10,
    target_win_rate: float = 0.7,
    required_consecutive: int = 3,
) -> dict[str, Any]:
    """便捷函数：运行一个完整的改进周期。"""
    try:
        loop = SelfImprovementLoop(
            target_win_rate=target_win_rate,
            max_iterations=max_cycles,
            required_consecutive_wins=required_consecutive,
        )
        result = loop.run(
            initial_flipped_score=initial_flipped_score,
            initial_baseline_score=initial_baseline_score,
        )
        result["task_description"] = task_description
        result["started_at"] = datetime.now(timezone.utc).isoformat()
        result["total_cycles"] = result.get("total_iterations", 0)
        result["final_score"] = result.get("final_flipped_score", 0)
        return result
    except Exception:
        return {"task_description": task_description, "error": "cycle failed"}
