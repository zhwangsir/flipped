"""M113 · 多智能体协作模式测试。

多 Agent 协作模式：
- vote: 多个 worker 并行生成，投票选最优
- critic: 专门的 critic agent 挑错
- brainstorm: 头脑风暴模式，多 agent 各抒己见
"""
from __future__ import annotations

from driving.multi_agent import (
    CollaborationMode,
    AgentProposal,
    vote_select_best,
    critic_review,
    brainstorm,
    run_collaborative_task,
)


class TestAgentProposal:
    def test_proposal_has_expected_fields(self):
        p = AgentProposal(
            agent_id="agent-1",
            content="solution 1",
            score=0.8,
            reasoning="because...",
        )
        assert p.agent_id == "agent-1"
        assert p.content == "solution 1"
        assert p.score == 0.8


class TestVoteSelectBest:
    def test_selects_highest_score(self):
        proposals = [
            AgentProposal("a1", "solution A", 0.6, "reason A"),
            AgentProposal("a2", "solution B", 0.9, "reason B"),
            AgentProposal("a3", "solution C", 0.7, "reason C"),
        ]
        best, all_sorted = vote_select_best(proposals)
        assert best.agent_id == "a2"
        assert all_sorted[0].agent_id == "a2"

    def test_empty_returns_none(self):
        best, _ = vote_select_best([])
        assert best is None


class TestCriticReview:
    def test_review_returns_feedback(self):
        proposal = AgentProposal("a1", "some code with potential issues", 0.7, "")
        feedback = critic_review(proposal, task_goal="build landing page")
        assert isinstance(feedback, list)
        assert len(feedback) >= 1

    def test_review_empty_proposal(self):
        feedback = critic_review(AgentProposal("", "", 0.0, ""), "test")
        assert isinstance(feedback, list)


class TestBrainstorm:
    def test_generates_multiple_ideas(self):
        ideas = brainstorm("design a landing page", num_agents=3)
        assert isinstance(ideas, list)
        assert len(ideas) >= 1

    def test_empty_goal_returns_empty(self):
        ideas = brainstorm("")
        assert ideas == []


class TestRunCollaborativeTask:
    def test_vote_mode(self):
        result = run_collaborative_task(
            "build a button",
            mode=CollaborationMode.vote,
            num_agents=2,
        )
        assert result["mode"] == "vote"
        assert "best_proposal" in result
        assert "all_proposals" in result

    def test_critic_mode(self):
        result = run_collaborative_task(
            "build a form",
            mode=CollaborationMode.critic,
        )
        assert result["mode"] == "critic"
        assert "review" in result

    def test_brainstorm_mode(self):
        result = run_collaborative_task(
            "design a dashboard",
            mode=CollaborationMode.brainstorm,
            num_agents=3,
        )
        assert result["mode"] == "brainstorm"
        assert "ideas" in result
