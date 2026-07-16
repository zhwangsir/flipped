"""M118 · Prompt 资产版本管理。

Prompt Versioning = 把 prompt 当代码管理：
- 版本化：每次修改生成新版本，可追溯
- A/B 测试：两个版本对比效果
- 回滚：出问题快速回退到上一版本
- 标签：stable / experimental / deprecated

fail-open: 异常时返回 None 或空结果。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class VersionTag(str, Enum):
    stable = "stable"
    experimental = "experimental"
    deprecated = "deprecated"
    candidate = "candidate"


@dataclass
class PromptVersion:
    """单个 Prompt 版本。"""
    id: str
    name: str
    content: str
    version: str = "1.0.0"
    tag: VersionTag = VersionTag.stable
    description: str = ""
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ABTestResult:
    """A/B 测试结果。"""
    prompt_name: str
    version_a: str
    version_b: str
    winner: str
    success_rate_delta: float
    quality_delta: float
    iterations_delta: float
    recommendation: str = ""
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class PromptRegistry:
    """Prompt 版本注册中心。"""
    versions: dict[str, list[PromptVersion]] = field(default_factory=dict)
    current: dict[str, str] = field(default_factory=dict)

    def register(
        self,
        name: str,
        content: str,
        *,
        version: str = "1.0.0",
        tag: VersionTag = VersionTag.stable,
        description: str = "",
    ) -> PromptVersion | None:
        """注册一个 prompt 版本。"""
        try:
            pv = PromptVersion(
                id=f"{name}-{version}",
                name=name,
                content=content,
                version=version,
                tag=tag,
                description=description,
            )
            if name not in self.versions:
                self.versions[name] = []
            self.versions[name].append(pv)
            self.current[name] = version
            return pv
        except Exception:
            return None

    def get(self, name: str, *, version: str | None = None) -> PromptVersion | None:
        """获取 prompt，默认最新版本。"""
        try:
            versions = self.versions.get(name, [])
            if not versions:
                return None
            if version is None:
                ver = self.current.get(name)
                if ver:
                    for v in versions:
                        if v.version == ver:
                            return v
                return versions[-1]
            for v in versions:
                if v.version == version:
                    return v
            return None
        except Exception:
            return None

    def get_history(self, name: str) -> list[PromptVersion]:
        """获取某个 prompt 的所有版本历史。"""
        try:
            return list(self.versions.get(name, []))
        except Exception:
            return []

    def rollback(self, name: str) -> PromptVersion | None:
        """回滚到上一个版本。"""
        try:
            versions = self.versions.get(name, [])
            if len(versions) < 2:
                return versions[-1] if versions else None
            prev = versions[-2]
            self.current[name] = prev.version
            return prev
        except Exception:
            return None

    def set_tag(self, name: str, tag: VersionTag, *, version: str | None = None) -> bool:
        """设置某个版本的标签。"""
        try:
            pv = self.get(name, version=version)
            if pv:
                pv.tag = tag
                return True
            return False
        except Exception:
            return False

    def list_prompts(self) -> list[str]:
        """列出所有 prompt 名称。"""
        try:
            return list(self.versions.keys())
        except Exception:
            return []

    def run_ab_test(
        self,
        name: str,
        version_a: str,
        version_b: str,
        *,
        metrics_a: dict[str, Any],
        metrics_b: dict[str, Any],
    ) -> ABTestResult:
        """运行 A/B 测试对比。"""
        try:
            sr_a = metrics_a.get("success_rate", 0.0)
            sr_b = metrics_b.get("success_rate", 0.0)
            q_a = metrics_a.get("avg_quality", 0.0)
            q_b = metrics_b.get("avg_quality", 0.0)
            it_a = metrics_a.get("avg_iterations", 0.0)
            it_b = metrics_b.get("avg_iterations", 0.0)

            sr_delta = sr_b - sr_a
            q_delta = q_b - q_a
            it_delta = it_b - it_a

            score_b = sr_delta * 0.5 + (q_delta / 100) * 0.3 - (it_delta / 10) * 0.2

            if score_b > 0.05:
                winner = version_b
                rec = f"推荐切换到 {version_b}：成功率+{sr_delta:.1%}，质量+{q_delta:.1f}"
            elif score_b < -0.05:
                winner = version_a
                rec = f"保留 {version_a}：{version_b} 效果更差"
            else:
                winner = "tie"
                rec = "两版本效果接近，继续观察"

            return ABTestResult(
                prompt_name=name,
                version_a=version_a,
                version_b=version_b,
                winner=winner,
                success_rate_delta=round(sr_delta, 4),
                quality_delta=round(q_delta, 2),
                iterations_delta=round(it_delta, 2),
                recommendation=rec,
                details={
                    "a_metrics": metrics_a,
                    "b_metrics": metrics_b,
                    "combined_score_delta": round(score_b, 4),
                },
            )
        except Exception:
            return ABTestResult(
                prompt_name=name,
                version_a=version_a,
                version_b=version_b,
                winner="error",
                success_rate_delta=0.0,
                quality_delta=0.0,
                iterations_delta=0.0,
                recommendation="A/B 测试计算异常",
            )
