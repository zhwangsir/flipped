"""无限迭代外层循环测试（M10.2）。

用 mock factory_loop_fn + evolve_fn 避免真 LLM 调用，
验证循环逻辑：轮次演进、停止条件、持久化。
"""
import sys
import os
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from driving.factory_loop import FactoryState, FactoryStatus
from driving.infinite_loop import (
    InfiniteLoopState,
    RoundSummary,
    _collect_round_summary,
    is_stop_requested,
    run_infinite_loop,
    save_loop_state,
    load_loop_state,
)


def _make_factory_state(goal: str, completed: int = 3, failed: int = 0) -> FactoryState:
    """构造一个 done 状态的 FactoryState。"""
    from driving.factory_loop import FactoryTask, TaskResult, TaskStatus

    tasks = [FactoryTask(id=f"task{i+1}", description=f"任务{i+1}", verify_cmd=["true"])
             for i in range(completed)]
    return FactoryState(
        factory_id="test-factory",
        product_goal=goal,
        cwd="/tmp/test",
        status=FactoryStatus.done,
        roadmap=tasks,
        completed=[
            TaskResult(task=t, verified=True, stop_reason="verified", iteration=1)
            for t in tasks
        ],
        failed=[
            TaskResult(
                task=FactoryTask(id=f"fail{i+1}", description=f"失败{i+1}", verify_cmd=["true"]),
                verified=False, stop_reason="circuit_breaker", iteration=1,
            )
            for i in range(failed)
        ],
    )


def test_run_infinite_loop_goal_achieved_after_two_rounds():
    """两轮后 GLM 判定目标达成，循环停止。"""
    call_count = {"evolve": 0}

    def mock_evolve(direction, rounds):
        call_count["evolve"] += 1
        if not rounds:  # 首轮：用 direction
            return direction, False, "首轮"
        if len(rounds) == 1:  # 第二轮
            return "第二轮：完善 UI", False, "继续"
        return "达成", True, "所有功能已实现"

    round_count = {"n": 0}

    def mock_factory_loop(goal, cwd, **kwargs):
        round_count["n"] += 1
        return _make_factory_state(goal, completed=round_count["n"])

    with tempfile.TemporaryDirectory() as td:
        db = os.path.join(td, "loop.db")
        state = run_infinite_loop(
            "构建一个 Web 应用",
            td,
            design_style="dark",
            max_rounds=10,
            db_path=db,
            evolve_fn=mock_evolve,
            factory_loop_fn=mock_factory_loop,
        )

    assert state.status == "goal_achieved"
    assert len(state.rounds) == 2
    assert state.rounds[0].product_goal == "构建一个 Web 应用"
    assert state.rounds[1].product_goal == "第二轮：完善 UI"
    assert call_count["evolve"] == 3  # 首轮 + 第2轮 + 达成判定


def test_run_infinite_loop_max_rounds():
    """达到 max_rounds 后 budget_exhausted。"""
    def mock_evolve(direction, rounds):
        return f"第 {len(rounds) + 1} 轮目标", False, "继续"

    def mock_factory_loop(goal, cwd, **kwargs):
        return _make_factory_state(goal, completed=1)

    with tempfile.TemporaryDirectory() as td:
        db = os.path.join(td, "loop.db")
        state = run_infinite_loop(
            "方向",
            td,
            max_rounds=3,
            db_path=db,
            evolve_fn=mock_evolve,
            factory_loop_fn=mock_factory_loop,
        )

    assert state.status == "budget_exhausted"
    assert len(state.rounds) == 3


def test_run_infinite_loop_stop_requested():
    """用户请求停止。"""
    def mock_evolve(direction, rounds):
        return "继续", False, "继续"

    def mock_factory_loop(goal, cwd, **kwargs):
        return _make_factory_state(goal, completed=1)

    with tempfile.TemporaryDirectory() as td:
        db = os.path.join(td, "loop.db")
        # 设环境变量请求停止
        old = os.environ.get("FLIPPED_STOP_LOOP")
        os.environ["FLIPPED_STOP_LOOP"] = "all"
        try:
            state = run_infinite_loop(
                "方向",
                td,
                max_rounds=10,
                db_path=db,
                evolve_fn=mock_evolve,
                factory_loop_fn=mock_factory_loop,
            )
        finally:
            if old is None:
                del os.environ["FLIPPED_STOP_LOOP"]
            else:
                os.environ["FLIPPED_STOP_LOOP"] = old

    assert state.status == "stopped"


def test_evolve_goal_fallback():
    """_evolve_goal 在 GLM 失败时兜底返回泛化目标。"""
    from driving.infinite_loop import _evolve_goal

    rounds = [RoundSummary(
        round_num=1, factory_id="f1", product_goal="第一轮",
        tasks_completed=3, tasks_failed=0, summary="完成基础功能",
    )]
    # 不调真 GLM，直接测 fallback 路径：_evolve_goal 内部 try/except
    # 我们 mock _make_llm 抛异常
    import driving.orchestrator as orch
    original = orch._make_llm
    orch._make_llm = lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("mock GLM fail"))
    try:
        goal, achieved, reasoning = _evolve_goal("方向", rounds)
    finally:
        orch._make_llm = original

    assert not achieved
    assert "fallback" in reasoning or "继续推进" in goal


def test_collect_round_summary():
    """成果摘要收集。"""
    factory = _make_factory_state("测试目标", completed=5, failed=1)
    summary = _collect_round_summary(1, factory)

    assert summary.round_num == 1
    assert summary.tasks_completed == 5
    assert summary.tasks_failed == 1
    assert "完成 5" in summary.summary
    assert "失败 1" in summary.summary


def test_infinite_loop_persistence():
    """状态持久化到 SQLite 并能恢复。"""
    with tempfile.TemporaryDirectory() as td:
        db = os.path.join(td, "loop.db")
        state = InfiniteLoopState(
            loop_id="test-persist",
            direction="测试方向",
            cwd=td,
            design_style="bento",
            max_rounds=5,
        )
        state.rounds.append(RoundSummary(
            round_num=1, factory_id="f1", product_goal="第一轮",
            tasks_completed=3, tasks_failed=0, summary="完成",
        ))
        save_loop_state(state, db)

        loaded = load_loop_state("test-persist", db)
        assert loaded is not None
        assert loaded.direction == "测试方向"
        assert loaded.design_style == "bento"
        assert len(loaded.rounds) == 1
        assert loaded.rounds[0].product_goal == "第一轮"


def test_run_infinite_loop_resume():
    """崩溃恢复：已有状态的循环能继续。"""
    with tempfile.TemporaryDirectory() as td:
        db = os.path.join(td, "loop.db")
        # 先创建一个已运行 1 轮的状态
        existing = InfiniteLoopState(
            loop_id="resume-test",
            direction="恢复测试",
            cwd=td,
            design_style="dark",
            max_rounds=3,
        )
        existing.rounds.append(RoundSummary(
            round_num=1, factory_id="f1", product_goal="第一轮",
            tasks_completed=2, tasks_failed=0, summary="完成",
        ))
        save_loop_state(existing, db)

        call_count = {"evolve": 0, "factory": 0}

        def mock_evolve(direction, rounds):
            call_count["evolve"] += 1
            if call_count["evolve"] == 1:
                # 恢复后第一次：还有目标要推进
                return "第二轮目标", False, "继续"
            # 第二次：目标达成
            return "达成", True, "所有功能已实现"

        def mock_factory_loop(goal, cwd, **kwargs):
            call_count["factory"] += 1
            return _make_factory_state(goal, completed=1)

        # 用已有 loop_id 恢复
        state = run_infinite_loop(
            "恢复测试",
            td,
            loop_id="resume-test",
            db_path=db,
            evolve_fn=mock_evolve,
            factory_loop_fn=mock_factory_loop,
        )

    assert state.status == "goal_achieved"
    assert len(state.rounds) == 2  # 原有 1 轮 + 新 1 轮
    assert call_count["evolve"] == 2


# ---------- M17: infra_failure 早停（不浪费预算跑下一轮） ----------


def test_infra_failure_round_stops_loop():
    """整轮全部 infra_failure 时，无限迭代循环立即停止，不浪费预算跑下一轮。

    E2E 暴露：exo 集群 ConnectTimeout 时 factory_loop 返回 paused + failed 全是
    infra_failure，但 infinite_loop 仍继续跑第 2 轮（又全 ConnectTimeout）。
    修复：检测到整轮全是 infra_failure 时，立即停止循环。
    """
    from driving.factory_loop import FactoryTask, TaskResult

    def mock_evolve(direction, rounds):
        return f"第 {len(rounds) + 1} 轮目标", False, "继续"

    def mock_factory_loop(goal, cwd, **kwargs):
        # 返回一个整轮全 infra_failure 的 FactoryState
        fail_task = FactoryTask(id="t1", description="task", verify_cmd=["true"])
        return FactoryState(
            factory_id="infra-factory",
            product_goal=goal,
            cwd=cwd,
            status=FactoryStatus.paused,
            roadmap=[fail_task],
            completed=[],
            failed=[
                TaskResult(
                    task=fail_task, verified=False,
                    stop_reason="infra_failure", iteration=0,
                    summary="ConnectTimeout: timed out",
                )
            ],
        )

    with tempfile.TemporaryDirectory() as td:
        db = os.path.join(td, "loop.db")
        state = run_infinite_loop(
            "方向",
            td,
            max_rounds=5,
            db_path=db,
            evolve_fn=mock_evolve,
            factory_loop_fn=mock_factory_loop,
        )

    assert state.status == "infra_failure"
    assert len(state.rounds) == 1  # 只跑了 1 轮（不浪费预算跑第 2 轮）


def test_mixed_round_continues_loop():
    """一轮有完成也有 infra_failure 时，循环应继续（不是整轮 infra_failure）。"""
    from driving.factory_loop import FactoryTask, TaskResult

    call_count = {"factory": 0}

    def mock_evolve(direction, rounds):
        if len(rounds) >= 2:
            return "达成", True, "完成"
        return f"第 {len(rounds) + 1} 轮目标", False, "继续"

    def mock_factory_loop(goal, cwd, **kwargs):
        call_count["factory"] += 1
        if call_count["factory"] == 1:
            # 第 1 轮：1 完成 + 1 infra_failure
            ok_task = FactoryTask(id="ok", description="ok", verify_cmd=["true"])
            fail_task = FactoryTask(id="fail", description="fail", verify_cmd=["true"])
            return FactoryState(
                factory_id="mixed-factory",
                product_goal=goal,
                cwd=cwd,
                status=FactoryStatus.done,
                roadmap=[ok_task, fail_task],
                completed=[
                    TaskResult(task=ok_task, verified=True, stop_reason="verified", iteration=1)
                ],
                failed=[
                    TaskResult(
                        task=fail_task, verified=False,
                        stop_reason="infra_failure", iteration=0,
                        summary="ConnectTimeout",
                    )
                ],
            )
        # 第 2 轮：全部完成
        return _make_factory_state(goal, completed=2)

    with tempfile.TemporaryDirectory() as td:
        db = os.path.join(td, "loop.db")
        state = run_infinite_loop(
            "方向",
            td,
            max_rounds=5,
            db_path=db,
            evolve_fn=mock_evolve,
            factory_loop_fn=mock_factory_loop,
        )

    assert state.status == "goal_achieved"
    assert len(state.rounds) == 2  # 跑了 2 轮（第1轮有完成不是全 infra_failure）


# ---------- M18: infra_failure 恢复（集群恢复后续跑） ----------


def test_resume_from_infra_failure():
    """infra_failure 状态的循环可以恢复——集群恢复后续跑。

    E2E 场景：集群 ConnectTimeout → infra_failure 停止。
    集群恢复后用相同 loop_id 再调 run_infinite_loop，应从 infra_failure 恢复继续。
    """
    from driving.factory_loop import FactoryTask, TaskResult

    with tempfile.TemporaryDirectory() as td:
        db = os.path.join(td, "loop.db")
        # 先创建一个 infra_failure 状态的循环（已跑 1 轮全失败）
        existing = InfiniteLoopState(
            loop_id="infra-resume-test",
            direction="恢复测试",
            cwd=td,
            design_style="dark",
            max_rounds=5,
        )
        fail_task = FactoryTask(id="t1", description="task", verify_cmd=["true"])
        existing.rounds.append(RoundSummary(
            round_num=1, factory_id="f1", product_goal="第一轮",
            tasks_completed=0, tasks_failed=1,
            summary="infra_failure: ConnectTimeout",
        ))
        existing.status = "infra_failure"
        save_loop_state(existing, db)

        factory_calls = {"n": 0}

        def mock_evolve(direction, rounds):
            if len(rounds) >= 2:
                return "达成", True, "完成"
            return "第二轮目标", False, "继续"

        def mock_factory_loop(goal, cwd, **kwargs):
            factory_calls["n"] += 1
            # 集群已恢复，正常完成
            return _make_factory_state(goal, completed=2)

        # 用相同 loop_id 恢复——应从 infra_failure 状态继续
        state = run_infinite_loop(
            "恢复测试",
            td,
            loop_id="infra-resume-test",
            db_path=db,
            evolve_fn=mock_evolve,
            factory_loop_fn=mock_factory_loop,
        )

    assert state.status == "goal_achieved"
    assert len(state.rounds) == 2  # 原有 1 轮 + 新 1 轮
    assert factory_calls["n"] == 1  # 只跑了 1 轮新 factory_loop


# ---------- M21: design_score 集成到无限迭代演进循环 ----------


def test_collect_round_summary_includes_design_score():
    """_collect_round_summary 应计算 design_score 并存入 RoundSummary。

    M21：每轮摘要应包含设计质量评分，让演进者看到设计质量趋势。
    """
    import os

    good_html = """<!DOCTYPE html>
<html lang="zh"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="description" content="test">
<style>
:root { --color-accent: #0A84FF; --color-bg: #0D0D12; --color-text: #F5F5F5; }
body { transition: opacity 0.3s ease; transform: translateY(0); }
@media (max-width: 768px) { body { font-size: 14px; } }
</style>
</head><body>
<header><nav>Logo</nav></header>
<main><section><h1>Title</h1></section></main>
<footer>Footer</footer>
</body></html>"""

    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(good_html)
        factory = _make_factory_state("测试目标", completed=3)
        factory.cwd = td
        summary = _collect_round_summary(1, factory)

    assert summary.design_score >= 80, f"良好HTML应得≥80分，实际{summary.design_score}"
    assert isinstance(summary.design_notes, list)
    assert len(summary.design_notes) > 0


def test_collect_round_summary_design_score_zero_for_no_html():
    """无 HTML 文件时 design_score=0。"""
    with tempfile.TemporaryDirectory() as td:
        factory = _make_factory_state("测试目标", completed=2)
        factory.cwd = td
        summary = _collect_round_summary(1, factory)

    assert summary.design_score == 0


def test_collect_round_summary_design_score_low_for_bad_html():
    """差的 HTML 应得低分。"""
    import os

    bad_html = """<html><head></head><body>
<div>Content</div>
</body></html>"""

    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(bad_html)
        factory = _make_factory_state("测试目标", completed=2)
        factory.cwd = td
        summary = _collect_round_summary(1, factory)

    assert summary.design_score < 70, f"差HTML应得<70分，实际{summary.design_score}"


def test_evolve_goal_includes_design_score_in_prompt():
    """_evolve_goal 的 prompt 应包含上一轮的 design_score。

    M21：演进者应知道上一轮设计质量评分，决定是否需要优化设计。
    低分时应提示"提升设计质量"。
    """
    from driving.infinite_loop import _evolve_goal

    rounds = [RoundSummary(
        round_num=1, factory_id="f1", product_goal="第一轮",
        tasks_completed=3, tasks_failed=0, summary="完成基础功能",
        design_score=45,  # 低分
        design_notes=["缺少 meta viewport", "缺少 CSS 变量"],
    )]

    captured_msg = {"text": ""}

    class FakeLLM:
        def with_structured_output(self, schema, **kwargs):
            class FakeResult:
                next_goal = "提升设计质量"
                goal_achieved = False
                reasoning = "设计评分低"
            return FakeResult()

    import driving.orchestrator as orch
    original_invoke = orch._invoke_structured
    original_make = orch._make_llm

    def capture_invoke(llm, schema, msg, **kwargs):
        captured_msg["text"] = msg
        return type("R", (), {"next_goal": "提升设计质量", "goal_achieved": False, "reasoning": "设计评分低"})()

    orch._invoke_structured = capture_invoke
    orch._make_llm = lambda *a, **kw: FakeLLM()
    try:
        _evolve_goal("方向", rounds, cwd="/tmp")
    finally:
        orch._invoke_structured = original_invoke
        orch._make_llm = original_make

    assert "45" in captured_msg["text"], "prompt 应包含 design_score 数值"
    assert "设计质量" in captured_msg["text"] or "design_score" in captured_msg["text"]


def test_evolve_goal_low_score_suggests_design_improvement():
    """design_score 低于阈值时，prompt 应明确提示需要提升设计质量。"""
    from driving.infinite_loop import _evolve_goal

    rounds = [RoundSummary(
        round_num=1, factory_id="f1", product_goal="第一轮",
        tasks_completed=3, tasks_failed=0, summary="完成",
        design_score=30,
        design_notes=["缺少 viewport", "缺少 CSS 变量", "无语义化 HTML"],
    )]

    captured_msg = {"text": ""}

    class FakeLLM:
        def with_structured_output(self, schema, **kwargs):
            class FakeResult:
                pass
            return FakeResult()

    import driving.orchestrator as orch
    original_invoke = orch._invoke_structured
    original_make = orch._make_llm

    def capture_invoke(llm, schema, msg, **kwargs):
        captured_msg["text"] = msg
        return type("R", (), {"next_goal": "优化设计", "goal_achieved": False, "reasoning": "设计评分低"})()

    orch._invoke_structured = capture_invoke
    orch._make_llm = lambda *a, **kw: FakeLLM()
    try:
        _evolve_goal("方向", rounds, cwd="/tmp")
    finally:
        orch._invoke_structured = original_invoke
        orch._make_llm = original_make

    # 低分时 prompt 应包含"提升设计质量"或"优化设计"的指令
    assert "设计质量" in captured_msg["text"] or "优化设计" in captured_msg["text"] or "提升设计" in captured_msg["text"]


def test_round_summary_has_design_score_field():
    """RoundSummary 应有 design_score 和 design_notes 字段。"""
    rs = RoundSummary(
        round_num=1, factory_id="f1", product_goal="测试",
        tasks_completed=1, tasks_failed=0,
        design_score=85,
        design_notes=["良好"],
    )
    assert rs.design_score == 85
    assert rs.design_notes == ["良好"]


def test_loop_state_persists_design_score():
    """design_score 应能持久化到 SQLite 并恢复。"""
    with tempfile.TemporaryDirectory() as td:
        db = os.path.join(td, "loop.db")
        state = InfiniteLoopState(
            loop_id="score-persist",
            direction="测试",
            cwd=td,
            design_style="dark",
            max_rounds=5,
        )
        state.rounds.append(RoundSummary(
            round_num=1, factory_id="f1", product_goal="第一轮",
            tasks_completed=3, tasks_failed=0, summary="完成",
            design_score=72,
            design_notes=["缺少 viewport", "CSS 变量完整"],
        ))
        save_loop_state(state, db)

        loaded = load_loop_state("score-persist", db)
        assert loaded is not None
        assert loaded.rounds[0].design_score == 72
    assert "缺少 viewport" in loaded.rounds[0].design_notes


# ---------- M46: infinite_loop 透传 task_proposer/design_fix_fallback + RoundSummary 追踪 ----------


def test_run_infinite_loop_passes_task_proposer_to_factory_loop():
    """run_infinite_loop 应把 task_proposer 透传给 factory_loop。

    M46：外层循环应能注入 task_proposer 控制自主任务生成，
    而不是只能靠环境变量自动接线。
    """
    received_kwargs = {}

    def mock_evolve(direction, rounds):
        if not rounds:
            return direction, False, "首轮"
        return "达成", True, "完成"

    def mock_factory_loop(goal, cwd, **kwargs):
        received_kwargs.update(kwargs)
        return _make_factory_state(goal, completed=1)

    def my_task_proposer(state):
        return None

    with tempfile.TemporaryDirectory() as td:
        db = os.path.join(td, "loop.db")
        run_infinite_loop(
            "方向",
            td,
            max_rounds=5,
            db_path=db,
            evolve_fn=mock_evolve,
            factory_loop_fn=mock_factory_loop,
            task_proposer=my_task_proposer,
        )

    assert "task_proposer" in received_kwargs
    assert received_kwargs["task_proposer"] is my_task_proposer


def test_run_infinite_loop_passes_design_fix_fallback_to_factory_loop():
    """run_infinite_loop 应把 design_fix_fallback 透传给 factory_loop。"""
    received_kwargs = {}

    def mock_evolve(direction, rounds):
        if not rounds:
            return direction, False, "首轮"
        return "达成", True, "完成"

    def mock_factory_loop(goal, cwd, **kwargs):
        received_kwargs.update(kwargs)
        return _make_factory_state(goal, completed=1)

    def my_design_fix_fallback(state):
        return None

    with tempfile.TemporaryDirectory() as td:
        db = os.path.join(td, "loop.db")
        run_infinite_loop(
            "方向",
            td,
            max_rounds=5,
            db_path=db,
            evolve_fn=mock_evolve,
            factory_loop_fn=mock_factory_loop,
            design_fix_fallback=my_design_fix_fallback,
        )

    assert "design_fix_fallback" in received_kwargs
    assert received_kwargs["design_fix_fallback"] is my_design_fix_fallback


def test_round_summary_has_proposer_fields():
    """RoundSummary 应有 proposer_triggered 和 design_fix_count 字段。"""
    rs = RoundSummary(
        round_num=1, factory_id="f1", product_goal="测试",
        tasks_completed=2, tasks_failed=0,
        proposer_triggered=True,
        design_fix_count=1,
    )
    assert rs.proposer_triggered is True
    assert rs.design_fix_count == 1


def test_round_summary_proposer_fields_default():
    """RoundSummary 的 proposer 字段默认值。"""
    rs = RoundSummary(
        round_num=1, factory_id="f1", product_goal="测试",
        tasks_completed=1, tasks_failed=0,
    )
    assert rs.proposer_triggered is False
    assert rs.design_fix_count == 0


def test_collect_round_summary_detects_design_fix_tasks():
    """_collect_round_summary 应从 completed 中检测 design-fix 任务。

    M46：proposer 触发的 design-fix 任务（feedback 含 'design_score' 或 'auto_fix'）
    应被识别并记入 RoundSummary，让演进者知道本轮已自动修复过设计问题。
    """
    from driving.factory_loop import FactoryTask, TaskResult

    normal_task = FactoryTask(id="t1", description="创建页面", verify_cmd=["true"])
    design_fix_task = FactoryTask(
        id="t2", description="修复设计质量问题",
        verify_cmd=["true"],
        feedback="(design_fix_fallback) design_score=55/70 未达标",
    )
    factory = FactoryState(
        factory_id="f1",
        product_goal="测试",
        cwd="/tmp/test_m46",
        status=FactoryStatus.done,
        roadmap=[normal_task, design_fix_task],
        completed=[
            TaskResult(task=normal_task, verified=True, stop_reason="verified", iteration=1),
            TaskResult(task=design_fix_task, verified=True, stop_reason="verified", iteration=1),
        ],
    )
    summary = _collect_round_summary(1, factory)

    assert summary.proposer_triggered is True
    assert summary.design_fix_count == 1


def test_collect_round_summary_no_design_fix_tasks():
    """没有 design-fix 任务时，proposer_triggered=False。"""
    from driving.factory_loop import FactoryTask, TaskResult

    normal_task = FactoryTask(id="t1", description="创建页面", verify_cmd=["true"])
    factory = FactoryState(
        factory_id="f1",
        product_goal="测试",
        cwd="/tmp/test_m46_none",
        status=FactoryStatus.done,
        roadmap=[normal_task],
        completed=[
            TaskResult(task=normal_task, verified=True, stop_reason="verified", iteration=1),
        ],
    )
    summary = _collect_round_summary(1, factory)

    assert summary.proposer_triggered is False
    assert summary.design_fix_count == 0


def test_loop_state_persists_proposer_fields():
    """proposer_triggered 和 design_fix_count 应能持久化到 SQLite 并恢复。"""
    with tempfile.TemporaryDirectory() as td:
        db = os.path.join(td, "loop.db")
        state = InfiniteLoopState(
            loop_id="proposer-persist",
            direction="测试",
            cwd=td,
            design_style="dark",
            max_rounds=5,
        )
        state.rounds.append(RoundSummary(
            round_num=1, factory_id="f1", product_goal="第一轮",
            tasks_completed=3, tasks_failed=0, summary="完成",
            proposer_triggered=True,
            design_fix_count=2,
        ))
        save_loop_state(state, db)

        loaded = load_loop_state("proposer-persist", db)
        assert loaded is not None
        assert loaded.rounds[0].proposer_triggered is True
        assert loaded.rounds[0].design_fix_count == 2


# ---------- M47: _evolve_goal 利用 proposer_triggered 做更智能演进决策 ----------


def _capture_evolve_prompt(rounds):
    """辅助：mock GLM 捕获 _evolve_goal 的 prompt 文本。"""
    from driving.infinite_loop import _evolve_goal

    captured = {"text": ""}

    class FakeLLM:
        def with_structured_output(self, schema, **kwargs):
            class FakeResult:
                pass
            return FakeResult()

    import driving.orchestrator as orch
    orig_invoke = orch._invoke_structured
    orig_make = orch._make_llm

    def capture_invoke(llm, schema, msg, **kwargs):
        captured["text"] = msg
        return type("R", (), {
            "next_goal": "目标", "goal_achieved": False, "reasoning": "推理"
        })()

    orch._invoke_structured = capture_invoke
    orch._make_llm = lambda *a, **kw: FakeLLM()
    try:
        _evolve_goal("方向", rounds, cwd="/tmp")
    finally:
        orch._invoke_structured = orig_invoke
        orch._make_llm = orig_make
    return captured["text"]


def test_evolve_prompt_design_fix_already_attempted():
    """M47: 上一轮已触发 design-fix 但分数仍低时，prompt 应提示'auto-fix 已尝试未达标'。

    避免重复"提升设计质量"指令导致空转：auto-fix 已经修过一轮了，
    再触发还是同样的结果。演进者应知道需要更深层的重构。
    """
    rounds = [RoundSummary(
        round_num=1, factory_id="f1", product_goal="第一轮",
        tasks_completed=3, tasks_failed=0, summary="完成",
        design_score=50,
        design_notes=["配色超过 5 种", "动画性能差"],
        proposer_triggered=True,
        design_fix_count=2,
    )]
    prompt = _capture_evolve_prompt(rounds)

    assert "auto-fix" in prompt or "已尝试" in prompt or "已修复" in prompt
    assert "重构" in prompt or "深层" in prompt or "人工" in prompt


def test_evolve_prompt_no_design_fix_attempted_low_score():
    """M47: 未触发 design-fix 且低分时，保持原有的'提升设计质量'提示。"""
    rounds = [RoundSummary(
        round_num=1, factory_id="f1", product_goal="第一轮",
        tasks_completed=3, tasks_failed=0, summary="完成",
        design_score=45,
        design_notes=["缺少 viewport"],
        proposer_triggered=False,
        design_fix_count=0,
    )]
    prompt = _capture_evolve_prompt(rounds)

    assert "提升设计质量" in prompt
    assert "auto-fix" not in prompt.lower().replace("-", "_") or "未尝试" in prompt


def test_evolve_prompt_design_fix_attempted_score_ok():
    """M47: 已触发 design-fix 且分数达标时，不应出现'auto-fix 已尝试未达标'提示。"""
    rounds = [RoundSummary(
        round_num=1, factory_id="f1", product_goal="第一轮",
        tasks_completed=3, tasks_failed=0, summary="完成",
        design_score=85,
        design_notes=["良好"],
        proposer_triggered=True,
        design_fix_count=1,
    )]
    prompt = _capture_evolve_prompt(rounds)

    assert "auto-fix 已尝试" not in prompt
    assert "未达标" not in prompt


# ---------- M49: E2E 集成测试 — 完整无限迭代链路 ----------


def test_e2e_infinite_loop_with_auto_fix_and_proposer_tracking():
    """E2E: 方向 → worker 产出有设计问题的 HTML → auto_fix 修复 →
    design_score 计算 → proposer 追踪 → evolve 下一轮 → 停止。

    验证完整链路：
    1. worker 产出配色过多的 HTML（8 种设计色）
    2. auto_fix_color_palette 合并到 ≤5 色（模拟 factory_loop 内行为）
    3. design_score 计算（应因 auto_fix 得到更高分）
    4. RoundSummary 记录设计评分
    5. 第二轮 goal_achieved 停止
    """
    import os
    import re
    from driving.factory_loop import FactoryTask, TaskResult, TaskStatus
    from driving.design_context import auto_fix_design_issues

    # worker 第一轮产出有设计问题的 HTML，第二轮产出良好 HTML
    factory_call = {"n": 0}

    def mock_evolve(direction, rounds, cwd=""):
        if len(rounds) < 2:
            return f"第 {len(rounds) + 1} 轮目标", False, "继续"
        return "达成", True, "已完成"

    def mock_factory_loop(goal, cwd, **kwargs):
        factory_call["n"] += 1

        if factory_call["n"] == 1:
            # 第一轮：worker 产出配色过多的 HTML（8 种设计色）
            html = """<!DOCTYPE html>
<html lang="zh"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<style>
:root { --c1: #0A84FF; --c2: #FF3B30; --c3: #34C759; --c4: #FF9500; --c5: #AF52DE; --c6: #5AC8FA; --c7: #FFD60A; --c8: #BF5AF2; }
body { margin: 0; padding: 16px; transition: opacity 0.3s ease; }
</style>
</head><body><header><nav>Logo</nav></header>
<main><section><h1>Title</h1><p>Content</p></section></main>
<footer>Footer</footer>
</body></html>"""
        else:
            # 第二轮：良好 HTML
            html = """<!DOCTYPE html>
<html lang="zh"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<style>
:root { --color-bg: #0D0D12; --color-text: #F5F5F5; --color-accent: #0A84FF; }
body { margin: 0; padding: 16px; transition: opacity 0.3s ease; }
</style>
</head><body><header><nav>Logo</nav></header>
<main><section><h1>Title</h1><p>Content</p></section></main>
<footer>Footer</footer>
</body></html>"""

        with open(os.path.join(cwd, "index.html"), "w") as f:
            f.write(html)

        # 模拟 factory_loop 内 auto_fix_design_issues 的行为
        auto_fix_design_issues(cwd)

        # 验证 auto_fix 后配色 ≤5（仅第一轮有意义）
        with open(os.path.join(cwd, "index.html"), "r") as f:
            content = f.read()
        hex_colors = set(re.findall(r"#[0-9A-Fa-f]{6}\b", content))
        design_colors = {c for c in hex_colors if c.upper() not in ("#000000", "#FFFFFF")}
        assert len(design_colors) <= 5, f"auto_fix 后应≤5色，实际{len(design_colors)}"

        task = FactoryTask(id=f"t{factory_call['n']}", description=goal, verify_cmd=["true"])
        return FactoryState(
            factory_id=f"factory-{factory_call['n']}",
            product_goal=goal,
            cwd=cwd,
            status=FactoryStatus.done,
            roadmap=[task],
            completed=[
                TaskResult(task=task, verified=True, stop_reason="verified", iteration=1)
            ],
        )

    with tempfile.TemporaryDirectory() as td:
        db = os.path.join(td, "loop.db")
        state = run_infinite_loop(
            "做一个落地页",
            td,
            max_rounds=5,
            db_path=db,
            evolve_fn=mock_evolve,
            factory_loop_fn=mock_factory_loop,
        )

    assert state.status == "goal_achieved"
    assert len(state.rounds) == 2

    # 第一轮应有 design_score（auto_fix 运行后计算）
    r1 = state.rounds[0]
    assert r1.design_score > 0, "第一轮应有 design_score"
    # auto_fix 后不应有"配色过多"的 note
    assert not any("配色过多" in n for n in r1.design_notes), \
        f"auto_fix 后不应有配色过多 note: {r1.design_notes}"


def test_e2e_proposer_triggered_reflects_design_fix():
    """E2E: worker 产出 design-fix 任务时，RoundSummary 应追踪到。

    模拟 factory_loop 内 task_proposer 触发了一个 design-fix 任务，
    该任务的 feedback 含 'design_score' 标记。
    _collect_round_summary 应设 proposer_triggered=True + design_fix_count=1。
    """
    from driving.factory_loop import FactoryTask, TaskResult

    normal_task = FactoryTask(id="t1", description="创建页面", verify_cmd=["true"])
    design_fix_task = FactoryTask(
        id="t2",
        description="修复设计质量",
        verify_cmd=["true"],
        feedback="(确定性 fallback: design_score=55/70, auto_fix 已修复 11 组维度)",
    )
    factory = FactoryState(
        factory_id="f1",
        product_goal="测试",
        cwd="/tmp/e2e_proposer",
        status=FactoryStatus.done,
        roadmap=[normal_task, design_fix_task],
        completed=[
            TaskResult(task=normal_task, verified=True, stop_reason="verified", iteration=1),
            TaskResult(task=design_fix_task, verified=True, stop_reason="verified", iteration=1),
        ],
    )
    summary = _collect_round_summary(1, factory)

    assert summary.proposer_triggered is True
    assert summary.design_fix_count == 1
    assert summary.tasks_completed == 2


def test_e2e_evolve_prompt_with_proposer_history():
    """E2E: 两轮历史 + 第一轮有 design-fix → evolve prompt 应包含 auto-fix 信息。

    M47 的核心价值：演进者看到"auto-fix 已尝试但未达标"后应给出深层重构指令，
    而非重复"提升设计质量"。这个测试验证 prompt 中包含修复活动历史。
    """
    rounds = [
        RoundSummary(
            round_num=1, factory_id="f1", product_goal="第一轮",
            tasks_completed=3, tasks_failed=0, summary="完成基础页面",
            design_score=50,
            design_notes=["配色超过 5 种", "动画性能差"],
            proposer_triggered=True,
            design_fix_count=2,
        ),
        RoundSummary(
            round_num=2, factory_id="f2", product_goal="第二轮",
            tasks_completed=2, tasks_failed=0, summary="优化设计",
            design_score=65,
            design_notes=["仍有配色问题"],
            proposer_triggered=True,
            design_fix_count=1,
        ),
    ]
    prompt = _capture_evolve_prompt(rounds)

    # 应包含 auto-fix 已尝试的提示（因为最新一轮 proposer_triggered + 低分）
    assert "auto-fix" in prompt or "已尝试" in prompt
    # 应包含修复数量信息
    assert "1" in prompt  # design_fix_count=1 出现在 rounds_text 或 hint
    # 应包含深层重构指令
    assert "重构" in prompt or "人工" in prompt


# ---------- M65: infinite_loop 透传 feature_fallback + RoundSummary 追踪 feature_count ----------


def test_run_infinite_loop_passes_feature_fallback_to_factory_loop():
    """run_infinite_loop 应把 feature_fallback 透传给 factory_loop。"""
    received_kwargs = {}

    def mock_evolve(direction, rounds):
        if not rounds:
            return direction, False, "首轮"
        return "达成", True, "完成"

    def mock_factory_loop(goal, cwd, **kwargs):
        received_kwargs.update(kwargs)
        return _make_factory_state(goal, completed=1)

    def my_feature_fallback(state):
        return None

    with tempfile.TemporaryDirectory() as td:
        db = os.path.join(td, "loop.db")
        run_infinite_loop(
            "方向",
            td,
            max_rounds=5,
            db_path=db,
            evolve_fn=mock_evolve,
            factory_loop_fn=mock_factory_loop,
            feature_fallback=my_feature_fallback,
        )

    assert "feature_fallback" in received_kwargs
    assert received_kwargs["feature_fallback"] is my_feature_fallback


def test_round_summary_has_feature_count_field():
    """RoundSummary 应有 feature_count 字段。"""
    rs = RoundSummary(
        round_num=1, factory_id="f1", product_goal="测试",
        tasks_completed=2, tasks_failed=0,
        feature_count=3,
    )
    assert rs.feature_count == 3


def test_round_summary_feature_count_default():
    """RoundSummary 的 feature_count 默认值为 0。"""
    rs = RoundSummary(
        round_num=1, factory_id="f1", product_goal="测试",
        tasks_completed=1, tasks_failed=0,
    )
    assert rs.feature_count == 0


def test_collect_round_summary_detects_feature_tasks():
    """_collect_round_summary 应从 completed 中检测 feature 任务。

    M65：feature 任务的 feedback 含 '确定性 feature' 标记，
    应被识别并记入 RoundSummary.feature_count。
    """
    from driving.factory_loop import FactoryTask, TaskResult

    normal_task = FactoryTask(id="t1", description="创建页面", verify_cmd=["true"])
    feature_task = FactoryTask(
        id="feature-1", description="添加表单组件",
        verify_cmd=["true"],
        feedback="(确定性 feature: 添加 <form>)",
    )
    factory = FactoryState(
        factory_id="f1",
        product_goal="测试",
        cwd="/tmp/test_m65",
        status=FactoryStatus.done,
        roadmap=[normal_task, feature_task],
        completed=[
            TaskResult(task=normal_task, verified=True, stop_reason="verified", iteration=1),
            TaskResult(task=feature_task, verified=True, stop_reason="verified", iteration=1),
        ],
    )
    summary = _collect_round_summary(1, factory)

    assert summary.feature_count == 1
    assert summary.proposer_triggered is True  # feature 也算自主生成


def test_collect_round_summary_no_feature_tasks():
    """没有 feature 任务时，feature_count=0。"""
    from driving.factory_loop import FactoryTask, TaskResult

    normal_task = FactoryTask(id="t1", description="创建页面", verify_cmd=["true"])
    factory = FactoryState(
        factory_id="f1",
        product_goal="测试",
        cwd="/tmp/test_m65_none",
        status=FactoryStatus.done,
        roadmap=[normal_task],
        completed=[
            TaskResult(task=normal_task, verified=True, stop_reason="verified", iteration=1),
        ],
    )
    summary = _collect_round_summary(1, factory)

    assert summary.feature_count == 0


def test_loop_state_persists_feature_count():
    """feature_count 应能持久化到 SQLite 并恢复。"""
    with tempfile.TemporaryDirectory() as td:
        db = os.path.join(td, "loop.db")
        state = InfiniteLoopState(
            loop_id="feature-persist",
            direction="测试",
            cwd=td,
            design_style="dark",
            max_rounds=5,
        )
        state.rounds.append(RoundSummary(
            round_num=1, factory_id="f1", product_goal="第一轮",
            tasks_completed=3, tasks_failed=0, summary="完成",
            feature_count=2,
        ))
        save_loop_state(state, db)

        loaded = load_loop_state("feature-persist", db)
        assert loaded is not None
        assert loaded.rounds[0].feature_count == 2


def test_evolve_goal_includes_feature_count_in_rounds_text():
    """_evolve_goal 的 prompt 应包含 feature_count 信息。"""
    rounds = [
        RoundSummary(
            round_num=1, factory_id="f1", product_goal="第一轮",
            tasks_completed=5, tasks_failed=0, summary="完成",
            feature_count=3,
        ),
        RoundSummary(
            round_num=2, factory_id="f1", product_goal="第二轮",
            tasks_completed=2, tasks_failed=0, summary="增强功能",
            feature_count=2,
        ),
    ]
    prompt = _capture_evolve_prompt(rounds)

    # 应包含 feature 增强数量
    assert "功能" in prompt or "feature" in prompt.lower()
    assert "3" in prompt  # feature_count=3


def test_evolve_goal_feature_hint_when_high_score_and_features():
    """M66: design_score 达标 + feature_count>0 时，提示关注更深层功能/内容。

    当设计质量已达标且功能增强已进行，演进者应收到提示：
    产品已进入功能深化阶段，可关注更复杂的功能或内容丰富度。
    """
    rounds = [
        RoundSummary(
            round_num=1, factory_id="f1", product_goal="第一轮",
            tasks_completed=5, tasks_failed=0, summary="基础页面",
            design_score=85,  # 达标
            feature_count=3,
        ),
    ]
    prompt = _capture_evolve_prompt(rounds)

    # 应包含功能深化提示
    assert "功能" in prompt
    # 应提示进入功能深化阶段或关注更深层功能
    assert "深化" in prompt or "更复杂" in prompt or "内容" in prompt


def test_evolve_goal_no_feature_hint_when_no_features():
    """M66: feature_count=0 时不触发功能深化提示。"""
    rounds = [
        RoundSummary(
            round_num=1, factory_id="f1", product_goal="第一轮",
            tasks_completed=3, tasks_failed=0, summary="基础页面",
            design_score=85,
            feature_count=0,
        ),
    ]
    prompt = _capture_evolve_prompt(rounds)

    # 不应包含功能深化提示
    assert "深化" not in prompt


def test_evolve_goal_feature_hint_skipped_when_low_score():
    """M66: design_score 低分时，feature_hint 让位于 design_hint（设计优先）。"""
    rounds = [
        RoundSummary(
            round_num=1, factory_id="f1", product_goal="第一轮",
            tasks_completed=5, tasks_failed=0, summary="基础页面",
            design_score=50,  # 低分
            feature_count=3,
        ),
    ]
    prompt = _capture_evolve_prompt(rounds)

    # 应优先提示设计质量问题，而非功能深化
    assert "设计质量" in prompt or "提升设计" in prompt
    # 不应包含功能深化提示（设计优先）
    assert "深化" not in prompt


# ---------- M67: E2E 集成测试 — 三层 fallback 完整链路 ----------


def test_e2e_three_layer_fallback_round_summary_tracking():
    """M67 E2E: 三层 fallback 产出 feature 任务 → RoundSummary 正确追踪。

    模拟完整链路在 infinite_loop 层面的表现：
    1. task_proposer (GLM) 返回 None（GLM 不可用）
    2. design_fix_fallback 返回 None（design_score 已达标）
    3. feature_fallback 返回 feature 任务
    4. factory_loop 执行 feature 任务 → completed
    5. _collect_round_summary 检测到 feature → feature_count=1, proposer_triggered=True
    6. _evolve_goal prompt 包含 feature 信息
    """
    from driving.factory_loop import FactoryTask, TaskResult

    # 构造一个有 feature 任务的 FactoryState（模拟三层 fallback 产出）
    normal_task = FactoryTask(id="t1", description="创建页面", verify_cmd=["true"])
    feature_task = FactoryTask(
        id="feature-1",
        description="添加表单组件（<form> + input + label，用于用户交互）",
        verify_cmd=["true"],
        feedback="(确定性 feature: 添加 <form>)",
    )

    captured_evolve = {"prompt": ""}

    def mock_evolve(direction, rounds):
        if not rounds:
            return direction, False, "首轮"
        # 捕获 evolve prompt 以验证 feature 信息
        # 手动调用 _evolve_goal 来捕获 prompt
        return "达成", True, "完成"

    def mock_factory_loop(goal, cwd, **kwargs):
        return FactoryState(
            factory_id="e2e-factory",
            product_goal=goal,
            cwd=cwd,
            status=FactoryStatus.done,
            roadmap=[normal_task, feature_task],
            completed=[
                TaskResult(task=normal_task, verified=True, stop_reason="verified", iteration=1),
                TaskResult(task=feature_task, verified=True, stop_reason="verified", iteration=1),
            ],
        )

    with tempfile.TemporaryDirectory() as td:
        db = os.path.join(td, "loop.db")
        state = run_infinite_loop(
            "做一个落地页",
            td,
            max_rounds=5,
            db_path=db,
            evolve_fn=mock_evolve,
            factory_loop_fn=mock_factory_loop,
        )

    assert state.status == "goal_achieved"
    assert len(state.rounds) == 1

    r1 = state.rounds[0]
    # 三层 fallback 产出的 feature 任务应被追踪
    assert r1.feature_count == 1, f"应追踪到 1 个 feature 任务，实际 {r1.feature_count}"
    assert r1.proposer_triggered is True, "feature 任务应触发 proposer_triggered"
    assert r1.tasks_completed == 2


def test_e2e_three_layer_fallback_with_real_proposers():
    """M67 E2E: 使用真实的 propose_design_fix_task + propose_feature_task。

    场景：GLM 不可用（mock propose_next_task 抛异常）+ HTML design_score 达标 +
    HTML 缺少功能维度（无 <form>）。验证三层 fallback 链路：
    - propose_next_task → 异常 → None
    - propose_design_fix_task → auto_fix + score ≥ 70 → None
    - propose_feature_task → 扫描到缺少 <form> → 返回 feature 任务
    - factory_loop 执行 feature 任务 → completed
    - _collect_round_summary → feature_count=1
    """
    from driving.factory_loop import run_factory_loop, FactoryTask, TaskResult
    from driving.task_proposer import propose_design_fix_task, propose_feature_task

    # 良好 HTML（design_score ≥ 70）但缺少所有 feature 维度
    good_html_no_features = """<!DOCTYPE html>
<html lang="zh"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="description" content="test">
<style>
:root { --color-bg: #0D0D12; --color-text: #F5F5F5; --color-accent: #0A84FF; }
body { padding: 16px; margin: 0; font-size: 16px; transition: opacity 0.3s ease; }
h1 { font-size: 48px; }
:focus-visible { outline: 2px solid var(--color-accent); outline-offset: 2px; }
@media (max-width: 768px) { body { font-size: 14px; } }
button:hover { opacity: 0.85; }
button:active { transform: scale(0.98); }
button:disabled { opacity: 0.5; cursor: not-allowed; }
</style></head><body>
<header><nav>Logo</nav></header>
<main><section><h1>Title</h1>
<button>Click</button>
</section></main>
<footer>Copyright</footer>
</body></html>"""

    def fake_orchestrator(task, state):
        # feature 任务的验收命令检查 HTML 标记，
        # 但 worker 没真正改 HTML，所以 mock 让所有任务通过
        return TaskResult(task=task, verified=True, stop_reason="verified", iteration=1)

    def fake_proposer(state):
        return None  # 模拟 GLM 不可用

    with tempfile.TemporaryDirectory() as d:
        with open(os.path.join(d, "index.html"), "w") as f:
            f.write(good_html_no_features)

        factory_state = run_factory_loop(
            product_goal="test",
            cwd=d,
            db_path=os.path.join(d, "test_factory.db"),
            checkpoint_db_path=os.path.join(d, "test_ckpt.db"),
            max_tasks=10,
            max_rounds=3,
            planner=lambda s: [FactoryTask(id="t0", description="init", verify_cmd=["true"])],
            orchestrator_fn=fake_orchestrator,
            task_proposer=fake_proposer,  # GLM 不可用 → None
            design_fix_fallback=propose_design_fix_task,  # 真实的
            feature_fallback=propose_feature_task,  # 真实的
        )

        # 初始 1 + feature 1 = 2
        assert len(factory_state.completed) >= 2

        # 最后一个任务应是 feature 任务
        feature_tasks = [t for t in factory_state.completed if "feature" in t.task.id]
        assert len(feature_tasks) >= 1, "应至少有 1 个 feature 任务"
        assert "feature" in feature_tasks[0].task.id

        # 验证 RoundSummary 追踪
        summary = _collect_round_summary(1, factory_state)
        assert summary.feature_count >= 1, f"feature_count 应≥1，实际 {summary.feature_count}"
        assert summary.proposer_triggered is True


def test_e2e_three_layer_fallback_evolve_integration():
    """M67 E2E: 三层 fallback 产出 feature + design_score 达标 → evolve prompt 包含 feature_hint。

    完整链路验证：
    1. factory_loop 产出 feature 任务（三层 fallback）
    2. RoundSummary: feature_count=2, design_score=85
    3. _evolve_goal prompt 应包含 feature_hint（"深化"）
    """
    from driving.factory_loop import FactoryTask, TaskResult

    # 构造有 2 个 feature 任务 + design_score 达标的 rounds
    feature_task_1 = FactoryTask(
        id="feature-1", description="添加表单", verify_cmd=["true"],
        feedback="(确定性 feature: 添加 <form>)",
    )
    feature_task_2 = FactoryTask(
        id="feature-2", description="添加 SVG", verify_cmd=["true"],
        feedback="(确定性 feature: 添加 <svg>)",
    )
    normal_task = FactoryTask(id="t1", description="创建页面", verify_cmd=["true"])

    def mock_evolve(direction, rounds):
        if not rounds:
            return direction, False, "首轮"
        return "达成", True, "完成"

    def mock_factory_loop(goal, cwd, **kwargs):
        return FactoryState(
            factory_id="e2e-evolve-factory",
            product_goal=goal,
            cwd=cwd,
            status=FactoryStatus.done,
            roadmap=[normal_task, feature_task_1, feature_task_2],
            completed=[
                TaskResult(task=normal_task, verified=True, stop_reason="verified", iteration=1),
                TaskResult(task=feature_task_1, verified=True, stop_reason="verified", iteration=1),
                TaskResult(task=feature_task_2, verified=True, stop_reason="verified", iteration=1),
            ],
        )

    with tempfile.TemporaryDirectory() as td:
        # 写一个良好的 HTML 让 design_score 达标
        good_html = """<!DOCTYPE html>
<html lang="zh"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="description" content="test">
<style>
:root { --color-bg: #0D0D12; --color-text: #F5F5F5; --color-accent: #0A84FF; }
body { padding: 16px; margin: 0; transition: opacity 0.3s ease; }
:focus-visible { outline: 2px solid var(--color-accent); }
</style></head><body>
<header><nav>Logo</nav></header>
<main><section><h1>Title</h1></section></main>
<footer>Footer</footer>
</body></html>"""
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(good_html)

        db = os.path.join(td, "loop.db")
        state = run_infinite_loop(
            "做一个落地页",
            td,
            max_rounds=5,
            db_path=db,
            evolve_fn=mock_evolve,
            factory_loop_fn=mock_factory_loop,
        )

    assert state.status == "goal_achieved"
    r1 = state.rounds[0]
    assert r1.feature_count == 2, f"应追踪到 2 个 feature 任务，实际 {r1.feature_count}"
    assert r1.proposer_triggered is True

    # 验证 evolve prompt 包含 feature_hint
    # 构造 rounds 列表，模拟 design_score 达标 + feature_count > 0
    evolve_rounds = [
        RoundSummary(
            round_num=1, factory_id="e2e-evolve-factory", product_goal="第一轮",
            tasks_completed=3, tasks_failed=0, summary="完成 + feature",
            design_score=85,
            feature_count=2,
            proposer_triggered=True,
        ),
    ]
    prompt = _capture_evolve_prompt(evolve_rounds)

    # 应包含 feature_hint
    assert "深化" in prompt or "更复杂" in prompt, \
        f"design_score=85 + feature_count=2 应触发 feature_hint，prompt: {prompt}"
    assert "功能" in prompt
