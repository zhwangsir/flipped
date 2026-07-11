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
