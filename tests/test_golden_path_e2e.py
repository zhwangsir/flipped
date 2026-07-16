"""M116 · Golden Path E2E 测试。

Golden Path = 最核心的用户旅程，从"输入一句话"到"产出 verified 结果"的完整链路。
验证：Skill推荐 → 任务分解 → Worker执行 → RCA失败重试 → Skill沉淀 → 质量把关

注意：这里测试的是模块集成的逻辑正确性，不跑真实 LLM。
"""
from __future__ import annotations

from driving.golden_path_e2e import (
    GoldenPathRunner,
    GoldenPathResult,
    GoldenPathScenario,
    run_golden_path,
)


class TestGoldenPathScenario:
    def test_scenario_definition(self):
        s = GoldenPathScenario(
            id="gp-001",
            name="build landing page",
            description="user asks to build a SaaS landing page",
            expected_stages=["skill_recommendation", "task_decomposition", "execution", "verification"],
            success_criteria=["output_verified", "skill_saved"],
        )
        assert s.id == "gp-001"
        assert len(s.expected_stages) == 4


class TestGoldenPathResult:
    def test_result_tracks_stages(self):
        r = GoldenPathResult(scenario_id="gp-001")
        r.add_stage("skill_recommendation", True, {"skills_found": 3})
        r.add_stage("task_decomposition", True, {"subtasks": 4})
        assert r.success is True
        assert len(r.completed_stages) == 2
        assert r.stage_count == 2


class TestGoldenPathRunner:
    def test_runner_runs_all_stages(self):
        runner = GoldenPathRunner()
        scenario = GoldenPathScenario(
            id="gp-test",
            name="test scenario",
            description="test",
            expected_stages=["skill_recommendation", "execution", "verification"],
            success_criteria=["all_stages_pass"],
        )
        result = runner.run(scenario, mock=True)
        assert result is not None
        assert result.scenario_id == "gp-test"
        assert result.stage_count >= 3

    def test_runner_failure_stage(self):
        runner = GoldenPathRunner()
        scenario = GoldenPathScenario(
            id="gp-fail",
            name="fail test",
            description="test failure path",
            expected_stages=["execution", "rca_retry", "verification"],
            success_criteria=["rca_triggered"],
        )
        result = runner.run(scenario, mock=True, force_fail_stage="execution")
        assert result is not None
        assert result.success is False or "rca_retry" in [s[0] for s in result.completed_stages]

    def test_runner_returns_summary(self):
        runner = GoldenPathRunner()
        scenario = GoldenPathScenario(
            id="gp-sum",
            name="summary test",
            description="test summary",
            expected_stages=["execution"],
            success_criteria=["ok"],
        )
        result = runner.run(scenario, mock=True)
        summary = result.get_summary()
        assert "scenario_id" in summary
        assert "success" in summary
        assert "stage_count" in summary


class TestRunGoldenPath:
    def test_simple_run(self):
        result = run_golden_path("build a button", mock=True)
        assert result is not None
        assert isinstance(result, GoldenPathResult)
        assert result.stage_count > 0

    def test_run_with_skill_recommendation(self):
        result = run_golden_path("build landing page", mock=True)
        stages = [s[0] for s in result.completed_stages]
        assert "skill_recommendation" in stages
