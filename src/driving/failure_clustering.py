"""M109 · 失败模式自动聚类。

定期自动聚类相似的失败，识别系统性失败，自动生成改进建议。
- cluster_failures: 基于 cause + 语义相似度的聚类
- identify_systemic_failures: 识别高频率/高影响的系统性失败
- generate_improvement_suggestions: 自动生成改进建议
- get_cluster_stats: 聚类统计面板数据

fail-open: 任何异常都返回空结果，不阻塞主流程。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from driving.failure_kb import _embed, _cosine_similarity


@dataclass
class FailureCluster:
    """失败聚类结果。"""
    cluster_id: str
    failure_ids: list[str]
    cause_category: str
    summary: str
    frequency: int = 0
    percentage: float = 0.0
    avg_iterations: float = 0.0
    sample_errors: list[str] = field(default_factory=list)


@dataclass
class SystemicFailure:
    """系统性失败识别结果。"""
    cluster_id: str
    cause_category: str
    summary: str
    frequency: int
    percentage: float
    severity: str
    suggested_fix: str


def _normalize_error(text: str) -> str:
    """归一化错误文本，移除行号、数字等可变部分。"""
    text = text or ""
    text = re.sub(r'line\s+\d+', 'line N', text, flags=re.IGNORECASE)
    text = re.sub(r'\d+', 'N', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip().lower()


def cluster_failures(
    failures: list[dict[str, Any]],
    *,
    similarity_threshold: float = 0.6,
    max_clusters: int = 20,
) -> list[FailureCluster]:
    """对失败进行聚类。

    先按 cause 粗分类，再按错误文本的语义相似度细分类。
    """
    try:
        if not failures:
            return []

        by_cause: dict[str, list[dict[str, Any]]] = {}
        for f in failures:
            cause = f.get("cause", "unknown") or "unknown"
            by_cause.setdefault(cause, []).append(f)

        clusters: list[FailureCluster] = []
        cluster_id = 0

        for cause, group in by_cause.items():
            if len(group) == 1:
                f = group[0]
                clusters.append(FailureCluster(
                    cluster_id=f"c{cluster_id}",
                    failure_ids=[f.get("id", "")],
                    cause_category=cause,
                    summary=f.get("error_detail", cause)[:100],
                    frequency=1,
                    sample_errors=[f.get("error_detail", "")[:200]],
                ))
                cluster_id += 1
                continue

            sub_clusters: list[list[dict[str, Any]]] = []
            for f in group:
                err_text = _normalize_error(f.get("error_detail", ""))
                err_vec = _embed(err_text)
                placed = False
                for sc in sub_clusters:
                    sc_text = _normalize_error(sc[0].get("error_detail", ""))
                    sc_vec = _embed(sc_text)
                    sim = _cosine_similarity(err_vec, sc_vec)
                    if sim >= similarity_threshold:
                        sc.append(f)
                        placed = True
                        break
                if not placed:
                    sub_clusters.append([f])

            for sc in sub_clusters:
                if len(sc) == 0:
                    continue
                ids = [f.get("id", "") for f in sc]
                sample_errors = [f.get("error_detail", "")[:200] for f in sc[:3]]
                iters = [f.get("iterations", 1) for f in sc if f.get("iterations")]
                avg_iter = sum(iters) / len(iters) if iters else 1.0
                summary = sc[0].get("error_detail", cause)[:100]
                clusters.append(FailureCluster(
                    cluster_id=f"c{cluster_id}",
                    failure_ids=ids,
                    cause_category=cause,
                    summary=summary,
                    frequency=len(sc),
                    sample_errors=sample_errors,
                    avg_iterations=round(avg_iter, 1),
                ))
                cluster_id += 1
                if cluster_id >= max_clusters:
                    break

        total = len(failures)
        for c in clusters:
            c.percentage = round(c.frequency / total * 100, 1) if total > 0 else 0.0

        clusters.sort(key=lambda c: c.frequency, reverse=True)
        return clusters
    except Exception:
        return []


def identify_systemic_failures(
    clusters: list[FailureCluster],
    *,
    total_failures: int,
    frequency_threshold: int = 5,
    percentage_threshold: float = 15.0,
) -> list[SystemicFailure]:
    """识别系统性失败（高频率/高占比的失败模式）。"""
    try:
        systemic: list[SystemicFailure] = []
        for c in clusters:
            is_systemic = (
                c.frequency >= frequency_threshold
                or c.percentage >= percentage_threshold
            )
            if not is_systemic:
                continue

            if c.percentage >= 30.0 or c.frequency >= 10:
                severity = "critical"
            elif c.percentage >= 20.0 or c.frequency >= 7:
                severity = "high"
            else:
                severity = "medium"

            suggestion = _suggest_fix_for_cause(c.cause_category)

            systemic.append(SystemicFailure(
                cluster_id=c.cluster_id,
                cause_category=c.cause_category,
                summary=c.summary,
                frequency=c.frequency,
                percentage=c.percentage,
                severity=severity,
                suggested_fix=suggestion,
            ))

        return systemic
    except Exception:
        return []


def _suggest_fix_for_cause(cause: str) -> str:
    """根据失败原因生成改进建议。"""
    suggestions = {
        "syntax_error": "加强 pre-commit 语法检查，在 worker 输出后增加 AST 语法校验节点，将语法错误消灭在生成阶段。",
        "verification_failed": "优化 verify_cmd 的设计，提供更明确的失败信息；增加 incremental_mode 使用率，减少全量重写。",
        "context_overflow": "升级上下文分层管理（M111），更早触发摘要压缩；优化 worker prompt 减少冗余输出。",
        "model_error": "增加模型健康检查和自动降级机制；LiteLLM Proxy 配置 fallback 模型；错误重试策略优化。",
        "tool_call_error": "加强工具调用格式校验；增加结构化输出约束；失败时自动重试 + 格式纠错。",
        "reasoning_loop": "优化 loop 检测机制（M106），更早识别死循环；增加 temperature 扰动打破循环。",
        "dependency_missing": "建立依赖白名单和自动安装机制；任务规划阶段提前扫描依赖需求。",
        "file_not_found": "加强上下文管理，确保文件路径在 worker 可见范围内；任务分解时明确文件依赖。",
        "timeout": "优化任务拆解粒度，单个任务不要太大；增加进度反馈机制；合理设置超时阈值。",
    }
    return suggestions.get(cause, "分析失败模式的根因，针对性优化相关模块；增加对应场景的测试用例。")


def generate_improvement_suggestions(
    clusters: list[FailureCluster],
    *,
    total_failures: int,
    top_n: int = 5,
) -> list[str]:
    """基于聚类结果生成改进建议列表。"""
    try:
        if not clusters or total_failures == 0:
            return []

        systemic = identify_systemic_failures(clusters, total_failures=total_failures)

        suggestions: list[str] = []

        for s in systemic[:top_n]:
            suggestions.append(
                f"[严重度: {s.severity}] {s.cause_category} 类失败占 {s.percentage}% "
                f"({s.frequency} 次) — {s.suggested_fix}"
            )

        if not suggestions and clusters:
            suggestions.append(
                f"当前共 {len(clusters)} 类失败模式，尚未达到系统性失败阈值。"
                "建议持续观察，重点关注 Top 失败原因的变化趋势。"
            )

        total_rate = sum(c.frequency for c in clusters) / max(1, total_failures) * 100
        if total_rate < 80:
            suggestions.append(
                f"仅 {round(total_rate, 1)}% 的失败被聚类，说明失败模式分散。"
                "建议积累更多数据后重新聚类分析。"
            )

        return suggestions[:top_n + 2]
    except Exception:
        return []


def get_cluster_stats(
    clusters: list[FailureCluster],
    *,
    total_failures: int,
) -> dict[str, Any]:
    """获取聚类统计数据，用于前端面板展示。"""
    try:
        clustered = sum(c.frequency for c in clusters)
        return {
            "total_clusters": len(clusters),
            "total_failures": total_failures,
            "clustered_failures": clustered,
            "clustering_rate": round(clustered / max(1, total_failures) * 100, 1),
            "top_clusters": [
                {
                    "cluster_id": c.cluster_id,
                    "cause_category": c.cause_category,
                    "summary": c.summary,
                    "frequency": c.frequency,
                    "percentage": c.percentage,
                    "avg_iterations": c.avg_iterations,
                }
                for c in clusters[:10]
            ],
            "cause_distribution": _cause_distribution(clusters),
        }
    except Exception:
        return {
            "total_clusters": 0,
            "total_failures": 0,
            "clustered_failures": 0,
            "clustering_rate": 0.0,
            "top_clusters": [],
            "cause_distribution": {},
        }


def _cause_distribution(clusters: list[FailureCluster]) -> dict[str, int]:
    """按 cause 分类统计失败数量。"""
    dist: dict[str, int] = {}
    for c in clusters:
        dist[c.cause_category] = dist.get(c.cause_category, 0) + c.frequency
    return dict(sorted(dist.items(), key=lambda x: x[1], reverse=True))
