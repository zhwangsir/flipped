"""M106 · 自适应回路检测。

根据任务复杂度动态调整 loop_threshold，避免"简单任务熔断太松、复杂任务熔断太紧"。
- estimate_task_complexity: 基于描述长度、文件数、依赖数估算复杂度
- compute_dynamic_threshold: 动态 loop_threshold（简单=2 / 中等=3 / 复杂=5）
- detect_progress: 检测是否有实质进展（文件变化 / verify 输出变化）
- check_loop_behavior: 综合判断回路状态，给出渐进式建议

fail-open: 任何异常都返回默认阈值，不阻塞主流程。
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import Enum
from typing import Any


class ComplexityLevel(str, Enum):
    simple = "simple"
    medium = "medium"
    complex = "complex"


@dataclass
class LoopDiagnosis:
    """回路检测诊断结果。"""
    should_escalate: bool
    reason: str
    complexity_level: ComplexityLevel
    complexity_score: float
    current_threshold: int
    consecutive_stuck: int
    suggested_action: str


COMPLEXITY_KEYWORDS = {
    "high": [
        "distributed", "microservice", "architecture", "scalable",
        "分布式", "微服务", "架构", "集群", "高并发",
        "database", "migration", "authentication", "oauth",
        "数据库", "迁移", "认证", "权限系统",
        "full-stack", "end-to-end", "production", "ci/cd",
        "全栈", "端到端", "生产级", "部署",
        "e-commerce", "ecommerce", "payment", "checkout",
        "电商", "支付", "结算",
        "multi-tenant", "saas", "real-time", "websocket",
        "多租户", "实时",
    ],
    "medium": [
        "component", "module", "feature", "integration",
        "组件", "模块", "功能", "集成",
        "dashboard", "landing page", "form", "table",
        "仪表板", "表单", "表格",
        "refactor", "optimize", "redesign",
        "重构", "优化", "重新设计",
        "user management", "inventory", "analytics", "tracking",
        "用户管理", "库存", "分析", "追踪",
        "order", "cart", "search", "filter",
        "订单", "购物车", "搜索", "筛选",
    ],
}


def estimate_task_complexity(
    description: str,
    *,
    file_count: int = 1,
    dependency_count: int = 0,
) -> tuple[ComplexityLevel, float]:
    """估算任务复杂度，返回 (level, score 0-100)。

    评分维度：
    - 描述长度 (30%): 越长通常越复杂
    - 关键词匹配 (40%): 复杂/中等关键词命中
    - 文件数量 (20%): 越多越复杂
    - 依赖数量 (10%): 越多越复杂
    """
    try:
        desc = description or ""
        desc_len = len(desc)

        # 描述长度得分 (0-30)
        len_score = min(30.0, desc_len / 20.0)

        # 关键词得分 (0-40)
        kw_score = 0.0
        desc_lower = desc.lower()
        for kw in COMPLEXITY_KEYWORDS["high"]:
            if kw.lower() in desc_lower:
                kw_score += 8.0
        for kw in COMPLEXITY_KEYWORDS["medium"]:
            if kw.lower() in desc_lower:
                kw_score += 3.0
        kw_score = min(40.0, kw_score)

        # 文件数量得分 (0-20)
        file_score = min(20.0, file_count * 1.5)

        # 依赖数量得分 (0-10)
        dep_score = min(10.0, dependency_count * 2.0)

        total = len_score + kw_score + file_score + dep_score

        if total < 30:
            level = ComplexityLevel.simple
        elif total < 60:
            level = ComplexityLevel.medium
        else:
            level = ComplexityLevel.complex

        return level, round(total, 1)
    except Exception:
        return ComplexityLevel.medium, 50.0


def compute_dynamic_threshold(
    complexity: ComplexityLevel | str,
    *,
    base_simple: int = 2,
    base_medium: int = 3,
    base_complex: int = 5,
) -> int:
    """根据复杂度计算动态 loop_threshold。"""
    try:
        level = complexity.value if isinstance(complexity, ComplexityLevel) else complexity
        if level == ComplexityLevel.simple:
            return base_simple
        elif level == ComplexityLevel.complex:
            return base_complex
        else:
            return base_medium
    except Exception:
        return base_medium


def detect_progress(
    prev_files: dict[str, str],
    curr_files: dict[str, str],
    verify_output_prev: str,
    verify_output_curr: str,
) -> tuple[bool, str]:
    """检测两轮之间是否有实质进展。

    返回 (has_progress, reason)。
    """
    try:
        # 检查文件内容变化
        if prev_files and curr_files:
            all_keys = set(prev_files.keys()) | set(curr_files.keys())
            changed = 0
            for k in all_keys:
                if prev_files.get(k) != curr_files.get(k):
                    changed += 1
            if changed > 0:
                return True, f"文件变化 ({changed} 个文件)"

        # 新增或删除文件也算进展
        if len(prev_files) != len(curr_files):
            return True, f"文件数量变化 ({len(prev_files)} → {len(curr_files)})"

        # 检查 verify 输出变化（即使文件没变，错误信息变了也是进展）
        if verify_output_prev and verify_output_curr:
            if verify_output_prev.strip() != verify_output_curr.strip():
                return True, "验证输出变化"

        return False, "无实质进展"
    except Exception:
        return False, "检测异常"


def _file_signature(files: dict[str, str]) -> str:
    """生成文件状态的签名，用于快速比较两轮是否相同。"""
    try:
        content = ""
        for k in sorted(files.keys()):
            content += f"{k}:{hashlib.md5(files[k].encode()).hexdigest()[:8]};"
        return hashlib.md5(content.encode()).hexdigest()[:12]
    except Exception:
        return ""


def check_loop_behavior(
    history: list[dict[str, Any]],
    task_description: str,
    *,
    file_count: int = 1,
    dependency_count: int = 0,
) -> LoopDiagnosis:
    """综合检测回路行为，给出诊断结果。

    history 格式: [{"files": {path: content}, "verify": "output"}, ...]

    返回 LoopDiagnosis，包含是否应该升级干预、原因、建议动作等。
    """
    try:
        complexity_level, complexity_score = estimate_task_complexity(
            task_description, file_count=file_count, dependency_count=dependency_count
        )
        threshold = compute_dynamic_threshold(complexity_level)

        if len(history) < 2:
            return LoopDiagnosis(
                should_escalate=False,
                reason="迭代次数不足",
                complexity_level=complexity_level,
                complexity_score=complexity_score,
                current_threshold=threshold,
                consecutive_stuck=0,
                suggested_action="continue",
            )

        # 计算连续无进展的轮数
        consecutive_stuck = 0
        for i in range(len(history) - 1, 0, -1):
            has_progress, _ = detect_progress(
                history[i - 1].get("files", {}),
                history[i].get("files", {}),
                history[i - 1].get("verify", ""),
                history[i].get("verify", ""),
            )
            if not has_progress:
                consecutive_stuck += 1
            else:
                break

        # 判断是否需要升级干预
        should_escalate = consecutive_stuck >= threshold

        # 建议动作（渐进式）
        if not should_escalate:
            action = "continue"
        elif consecutive_stuck == threshold:
            action = "change_temperature"
        elif consecutive_stuck <= threshold + 1:
            action = "simplify_prompt"
        else:
            action = "human_intervention"

        reason = (
            f"连续 {consecutive_stuck} 轮无实质进展，"
            f"复杂度={complexity_level.value}({complexity_score}), "
            f"阈值={threshold}"
        )

        return LoopDiagnosis(
            should_escalate=should_escalate,
            reason=reason,
            complexity_level=complexity_level,
            complexity_score=complexity_score,
            current_threshold=threshold,
            consecutive_stuck=consecutive_stuck,
            suggested_action=action,
        )
    except Exception:
        return LoopDiagnosis(
            should_escalate=False,
            reason="检测异常，跳过检查(fail-open)",
            complexity_level=ComplexityLevel.medium,
            complexity_score=50.0,
            current_threshold=3,
            consecutive_stuck=0,
            suggested_action="continue",
        )
