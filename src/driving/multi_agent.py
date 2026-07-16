"""M113 · 多智能体协作模式。

多 Agent 协作模式：
- vote: 多个 worker 并行生成，投票选最优
- critic: 专门的 critic agent 挑错，提升质量
- brainstorm: 头脑风暴模式，多 agent 各抒己见

注：当前实现是框架层的，实际调用 LLM 的部分留了接口。
     集成时替换为真实 LLM 调用即可。

fail-open: 任何异常都优雅降级到单 agent 模式。
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from enum import Enum
from typing import Any


class CollaborationMode(str, Enum):
    vote = "vote"
    critic = "critic"
    brainstorm = "brainstorm"


@dataclass
class AgentProposal:
    """Agent 的提案。"""
    agent_id: str
    content: str
    score: float
    reasoning: str = ""


def _mock_agent_solution(agent_id: str, task_goal: str) -> AgentProposal:
    """模拟 agent 生成方案（实际使用时替换为 LLM 调用）。"""
    templates = [
        f"方案 {agent_id}: 采用模块化设计，先构建基础组件再组合。",
        f"方案 {agent_id}: 从数据层开始，自底向上构建完整功能。",
        f"方案 {agent_id}: 快速原型 + 迭代优化，先跑通再打磨。",
        f"方案 {agent_id}: 优先考虑用户体验，从交互设计出发。",
        f"方案 {agent_id}: 性能优先，所有设计围绕效率优化。",
    ]
    content = random.choice(templates)
    score = round(random.uniform(0.5, 0.95), 2)
    return AgentProposal(
        agent_id=agent_id,
        content=content,
        score=score,
        reasoning=f"基于 {agent_id} 的经验和风格生成",
    )


def _mock_critic_feedback(proposal: AgentProposal, task_goal: str) -> list[str]:
    """模拟 critic 的反馈（实际使用时替换为 LLM 调用）。"""
    feedback_items = [
        "代码结构可以更清晰，建议增加模块化",
        "错误处理不够完善，需要增加边界情况处理",
        "性能方面还有优化空间",
        "用户体验可以更好，增加更多反馈",
        "缺少必要的注释和文档",
        "测试覆盖需要加强",
    ]
    n = random.randint(1, 3)
    return random.sample(feedback_items, n)


def _mock_brainstorm_idea(agent_id: str, goal: str) -> str:
    """模拟头脑风暴想法（实际使用时替换为 LLM 调用）。"""
    ideas = [
        f"{agent_id}: 可以尝试 A/B 测试不同设计",
        f"{agent_id}: 参考业内最佳实践，如 Apple/Stripe",
        f"{agent_id}: 加入微交互提升质感",
        f"{agent_id}: 考虑暗黑模式和可访问性",
        f"{agent_id}: 用动效引导用户注意力",
        f"{agent_id}: 简化流程，减少用户操作步骤",
        f"{agent_id}: 增加数据可视化让信息更直观",
    ]
    return random.choice(ideas)


def vote_select_best(
    proposals: list[AgentProposal],
) -> tuple[AgentProposal | None, list[AgentProposal]]:
    """投票选择最优方案。

    返回 (最佳方案, 按分数排序的全部方案)。
    """
    try:
        if not proposals:
            return None, []

        sorted_proposals = sorted(proposals, key=lambda p: p.score, reverse=True)
        return sorted_proposals[0], sorted_proposals
    except Exception:
        return None, proposals


def critic_review(
    proposal: AgentProposal,
    task_goal: str,
) -> list[str]:
    """Critic 模式：专门的 critic agent 挑错。"""
    try:
        if not proposal.content:
            return ["空提案，无法评审"]
        return _mock_critic_feedback(proposal, task_goal)
    except Exception:
        return ["评审出错，跳过"]


def brainstorm(
    goal: str,
    *,
    num_agents: int = 3,
) -> list[str]:
    """头脑风暴模式：多个 agent 各抒己见，发散思维。"""
    try:
        if not goal or not goal.strip():
            return []
        ideas = []
        for i in range(num_agents):
            agent_id = f"agent-{i + 1}"
            idea = _mock_brainstorm_idea(agent_id, goal)
            ideas.append(idea)
        return ideas
    except Exception:
        return []


def run_collaborative_task(
    task_goal: str,
    *,
    mode: CollaborationMode = CollaborationMode.vote,
    num_agents: int = 3,
) -> dict[str, Any]:
    """运行多智能体协作任务。

    根据模式选择不同的协作策略。
    """
    try:
        if mode == CollaborationMode.vote:
            proposals = [
                _mock_agent_solution(f"agent-{i + 1}", task_goal)
                for i in range(num_agents)
            ]
            best, sorted_list = vote_select_best(proposals)
            return {
                "mode": "vote",
                "best_proposal": best,
                "all_proposals": sorted_list,
                "num_agents": num_agents,
            }

        elif mode == CollaborationMode.critic:
            main_proposal = _mock_agent_solution("main-agent", task_goal)
            review = critic_review(main_proposal, task_goal)
            return {
                "mode": "critic",
                "main_proposal": main_proposal,
                "review": review,
                "num_agents": 2,
            }

        elif mode == CollaborationMode.brainstorm:
            ideas = brainstorm(task_goal, num_agents=num_agents)
            return {
                "mode": "brainstorm",
                "ideas": ideas,
                "num_agents": num_agents,
            }

        else:
            return {"mode": "unknown", "error": f"unsupported mode: {mode}"}
    except Exception:
        return {"mode": str(mode), "error": "collaboration failed, fallback to single agent"}
