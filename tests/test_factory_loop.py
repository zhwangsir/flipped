"""factory_loop 确定性单测（不依赖真实 LLM / 沙盒）。"""
from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest  # noqa: E402

from driving.factory_loop import (  # noqa: E402
    FactoryState,
    FactoryStatus,
    FactoryTask,
    TaskResult,
    TaskStatus,
    _deterministic_roadmap,
    _next_task,
    _wrap_with_design_quality,
    default_planner,
    list_factories,
    load_factory_state,
    resume_factory_loop,
    run_factory_loop,
    save_factory_state,
)


@pytest.fixture
def tmp_db():
    with tempfile.TemporaryDirectory() as td:
        yield Path(td) / "factory.db"


@pytest.fixture
def tmp_cwd():
    with tempfile.TemporaryDirectory() as td:
        yield td


def make_task(description: str, verify_cmd: list[str] | None = None) -> FactoryTask:
    return FactoryTask(
        description=description,
        verify_cmd=verify_cmd or ["true"],
        max_attempts=3,
    )


# ---------- 持久化 ----------


def test_save_and_load_roundtrip(tmp_db):
    state = FactoryState(
        factory_id="f1",
        product_goal="build a calculator",
        cwd="/tmp",
        status=FactoryStatus.running,
        roadmap=[make_task("add")],
        max_tasks=5,
    )
    save_factory_state(state, str(tmp_db))
    loaded = load_factory_state("f1", str(tmp_db))
    assert loaded is not None
    assert loaded.factory_id == "f1"
    assert loaded.product_goal == "build a calculator"
    assert len(loaded.roadmap) == 1
    assert loaded.roadmap[0].description == "add"
    assert loaded.status == FactoryStatus.running


def test_list_factories_order_by_updated(tmp_db):
    for fid in ("f-old", "f-new"):
        save_factory_state(
            FactoryState(
                factory_id=fid,
                product_goal="g",
                cwd="/tmp",
                status=FactoryStatus.pending,
                roadmap=[],
            ),
            str(tmp_db),
        )
    factories = list_factories(str(tmp_db))
    assert factories == ["f-new", "f-old"]


# ---------- 调度 ----------


def test_next_task_respects_dependencies():
    t1 = make_task("a")
    t2 = make_task("b")
    t2.depends_on = [t1.id]
    state = FactoryState(
        factory_id="f",
        product_goal="g",
        cwd="/tmp",
        status=FactoryStatus.running,
        roadmap=[t1, t2],
    )
    assert _next_task(state) == t1
    t1.status = TaskStatus.done
    assert _next_task(state) == t2


def test_next_task_skips_running():
    t1 = make_task("a")
    t1.status = TaskStatus.running
    state = FactoryState(
        factory_id="f",
        product_goal="g",
        cwd="/tmp",
        status=FactoryStatus.running,
        roadmap=[t1],
    )
    assert _next_task(state) is None


# ---------- Master Loop ----------


def test_run_factory_loop_planner_stub_and_executes_two_tasks(tmp_db, tmp_cwd):
    executed = []

    def stub_planner(state: FactoryState) -> list[FactoryTask]:
        return [
            make_task("task one", verify_cmd=["echo", "one"]),
            make_task("task two", verify_cmd=["echo", "two"]),
        ]

    def stub_orchestrator(task: FactoryTask, state: FactoryState) -> TaskResult:
        executed.append(task.description)
        return TaskResult(
            task=task,
            verified=True,
            stop_reason="completed",
            iteration=1,
            summary="ok",
        )

    result = run_factory_loop(
        product_goal="build calc",
        cwd=tmp_cwd,
        db_path=str(tmp_db),
        planner=stub_planner,
        orchestrator_fn=stub_orchestrator,
        max_tasks=10,
    )

    assert result.status == FactoryStatus.done
    assert len(result.completed) == 2
    assert executed == ["task one", "task two"]

    # 持久化验证
    loaded = load_factory_state(result.factory_id, str(tmp_db))
    assert loaded.status == FactoryStatus.done
    assert len(loaded.completed) == 2


def test_run_factory_loop_retries_then_pauses(tmp_db, tmp_cwd):
    calls = []

    def stub_planner(state: FactoryState) -> list[FactoryTask]:
        return [make_task("always fail", verify_cmd=["false"])]

    def stub_orchestrator(task: FactoryTask, state: FactoryState) -> TaskResult:
        calls.append(task.attempts)
        return TaskResult(
            task=task,
            verified=False,
            stop_reason="verify_failed",
            iteration=1,
            summary="nope",
        )

    result = run_factory_loop(
        product_goal="build calc",
        cwd=tmp_cwd,
        db_path=str(tmp_db),
        planner=stub_planner,
        orchestrator_fn=stub_orchestrator,
        max_tasks=10,
    )

    # max_attempts=3，三次失败后暂停
    assert calls == [1, 2, 3]
    assert result.status == FactoryStatus.paused
    assert len(result.failed) == 3
    assert result.iteration_count == 3


# ---------- M16: infra_failure 优雅暂停（不烧光重试次数） ----------


def test_infra_failure_pauses_without_consuming_retries(tmp_db, tmp_cwd):
    """集群不可用(ConnectTimeout)时立即暂停，不消耗 max_attempts。

    E2E 暴露：exo 集群 ConnectTimeout 时 worker_error=True → stop_reason="worker_error"，
    factory_loop 把它当普通失败重试 3 次 → 烧光重试次数 → paused。
    修复：检测 infra_failure 模式（ConnectTimeout/ReadTimeout/worker_error 含 timeout），
    立即暂停并标记 infra_failure，不消耗重试次数。
    """
    call_count = [0]

    def stub_planner(state: FactoryState) -> list[FactoryTask]:
        return [make_task("any task", verify_cmd=["true"])]

    def stub_orchestrator(task: FactoryTask, state: FactoryState) -> TaskResult:
        call_count[0] += 1
        return TaskResult(
            task=task,
            verified=False,
            stop_reason="worker_error",
            iteration=0,
            summary="ConnectTimeout: timed out",
        )

    result = run_factory_loop(
        product_goal="build something",
        cwd=tmp_cwd,
        db_path=str(tmp_db),
        planner=stub_planner,
        orchestrator_fn=stub_orchestrator,
        max_tasks=10,
    )

    # 只调 1 次（而非 3 次），因为 infra_failure → 立即暂停
    assert call_count[0] == 1
    assert result.status == FactoryStatus.paused
    # failed 只有 1 条（不消耗重试次数）
    assert len(result.failed) == 1
    # stop_reason 标记为 infra_failure
    assert "infra" in result.failed[0].stop_reason or "infra" in result.failed[0].summary.lower()


def test_non_infra_failure_still_retries(tmp_db, tmp_cwd):
    """普通失败（verify_failed）仍正常重试 3 次。

    确认 M16 修复不影响普通失败的正常重试逻辑。
    """
    calls = []

    def stub_planner(state: FactoryState) -> list[FactoryTask]:
        return [make_task("verify fail", verify_cmd=["false"])]

    def stub_orchestrator(task: FactoryTask, state: FactoryState) -> TaskResult:
        calls.append(task.attempts)
        return TaskResult(
            task=task,
            verified=False,
            stop_reason="verify_failed",
            iteration=1,
            summary="assertion failed",
        )

    result = run_factory_loop(
        product_goal="build something",
        cwd=tmp_cwd,
        db_path=str(tmp_db),
        planner=stub_planner,
        orchestrator_fn=stub_orchestrator,
        max_tasks=10,
    )

    # 普通失败仍重试 3 次
    assert calls == [1, 2, 3]
    assert result.status == FactoryStatus.paused
    assert len(result.failed) == 3


def test_resume_factory_loop_continues_after_crash(tmp_db, tmp_cwd):
    """模拟进程崩溃：直接写入一个 current_task 为 running 的状态，再 resume。"""
    calls = []

    first = make_task("first", verify_cmd=["echo", "first"])
    second = make_task("second", verify_cmd=["echo", "second"])
    first.status = TaskStatus.done
    second.status = TaskStatus.running

    crashed_state = FactoryState(
        factory_id="crash-factory",
        product_goal="build calc",
        cwd=tmp_cwd,
        status=FactoryStatus.running,
        roadmap=[first, second],
        current_task_id=second.id,
        iteration_count=1,
        max_tasks=10,
    )
    crashed_state.completed.append(
        TaskResult(
            task=first,
            verified=True,
            stop_reason="completed",
            iteration=1,
            summary="ok",
        )
    )
    save_factory_state(crashed_state, str(tmp_db))

    def success_orchestrator(task: FactoryTask, state: FactoryState) -> TaskResult:
        calls.append(task.description)
        return TaskResult(
            task=task,
            verified=True,
            stop_reason="completed",
            iteration=1,
            summary="ok",
        )

    resumed = resume_factory_loop(
        factory_id="crash-factory",
        db_path=str(tmp_db),
        orchestrator_fn=success_orchestrator,
        max_tasks=10,
    )

    assert resumed.status == FactoryStatus.done
    assert len(resumed.completed) == 2
    assert "second" in calls


# ---------- default_planner fail-open ----------


def test_default_planner_returns_fallback_on_llm_error():
    # mock _make_llm 快速抛异常，验证 fail-open 兜底（M45: 改用确定性 roadmap）
    state = FactoryState(
        factory_id="f",
        product_goal="build a calculator",
        cwd="/tmp",
        status=FactoryStatus.pending,
        roadmap=[],
    )
    with patch("driving.factory_loop._make_llm", side_effect=RuntimeError("no model")):
        tasks = default_planner(state)
    # M45: 不再返回单个 true 任务，而是确定性 roadmap（≥2 个有意义的任务）
    assert len(tasks) >= 2
    assert all("planner fail-open" in (t.feedback or "") for t in tasks)
    assert all(t.verify_cmd[0] != "true" for t in tasks)


# ---------- schema 迁移兼容 ----------


def test_sqlite_schema_has_expected_columns(tmp_db):
    save_factory_state(
        FactoryState(
            factory_id="schema-check",
            product_goal="g",
            cwd="/tmp",
            status=FactoryStatus.pending,
            roadmap=[],
        ),
        str(tmp_db),
    )
    with sqlite3.connect(str(tmp_db)) as conn:
        cur = conn.execute("PRAGMA table_info(factory_states)")
        cols = {row[1] for row in cur.fetchall()}
    expected = {
        "factory_id",
        "product_goal",
        "cwd",
        "status",
        "roadmap_json",
        "completed_json",
        "failed_json",
        "current_task_id",
        "context_summary",
        "iteration_count",
        "max_tasks",
        "created_at",
        "updated_at",
    }
    assert expected.issubset(cols)


# ---------- M20: _wrap_with_design_quality ----------


def test_wrap_with_design_quality_passes_good_html(tmp_cwd):
    """良好 HTML 通过 base verifier 后 design_quality 也无 error 违规。"""
    good_html = """<!DOCTYPE html>
<html lang="zh"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<style>:root { --color-accent: #0A84FF; }</style>
</head><body><header><nav>Logo</nav></header>
<main><section><h1>Title</h1></section></main><footer>Footer</footer>
</body></html>"""
    import os
    with open(os.path.join(tmp_cwd, "index.html"), "w") as f:
        f.write(good_html)

    def base_verifier(history, cwd):
        return True, "base ok"

    wrapped = _wrap_with_design_quality(base_verifier)
    ok, msg = wrapped([], tmp_cwd)
    assert ok is True
    assert "base ok" in msg


def test_wrap_with_design_quality_blocks_missing_viewport(tmp_cwd):
    """缺少 viewport 的 HTML 应被 design_quality 阻断。"""
    bad_html = """<html><head></head><body>
<header>H</header><main><section>S</section></main><footer>F</footer>
</body></html>"""
    import os
    with open(os.path.join(tmp_cwd, "index.html"), "w") as f:
        f.write(bad_html)

    def base_verifier(history, cwd):
        return True, "base ok"

    wrapped = _wrap_with_design_quality(base_verifier)
    ok, msg = wrapped([], tmp_cwd)
    assert ok is False
    assert "design_quality" in msg
    assert "viewport" in msg.lower()


def test_wrap_with_design_quality_base_fail_skips_quality(tmp_cwd):
    """base verifier 失败时跳过 design_quality 检查。"""
    def base_verifier(history, cwd):
        return False, "base failed"

    wrapped = _wrap_with_design_quality(base_verifier)
    ok, msg = wrapped([], tmp_cwd)
    assert ok is False
    assert "base failed" in msg
    assert "design_quality" not in msg


def test_wrap_with_design_quality_warnings_dont_block(tmp_cwd):
    """warning 级违规不阻断验证，只追加提示。"""
    # 有 header/main/section/footer 和 viewport 但没有 footer 的 HTML
    # 实际上这个测试验证：只有 warning 时仍通过
    html_with_warnings = """<html lang="zh"><head>
<meta name="viewport" content="width=device-width">
</head><body><header>H</header><main><section>S</section></main><footer>F</footer>
</body></html>"""
    import os
    with open(os.path.join(tmp_cwd, "index.html"), "w") as f:
        f.write(html_with_warnings)

    def base_verifier(history, cwd):
        return True, "base ok"

    wrapped = _wrap_with_design_quality(base_verifier)
    ok, msg = wrapped([], tmp_cwd)
    assert ok is True  # warning 不阻断


# ---------- M45: deterministic planner fallback ----------


def test_deterministic_roadmap_generates_meaningful_tasks():
    """GLM 不可用时，确定性 roadmap 生成有意义的任务列表（非单个 true 任务）。"""
    with tempfile.TemporaryDirectory() as d:
        tasks = _deterministic_roadmap("做一个落地页", d)
    assert len(tasks) >= 2, f"应生成至少 2 个任务，实际 {len(tasks)}"
    for t in tasks:
        assert t.description, "任务必须有描述"
        assert t.verify_cmd, "任务必须有验收命令"
        assert t.verify_cmd[0] != "true", "验收命令不应是 true"


def test_deterministic_roadmap_verify_cmd_checks_html():
    """确定性 roadmap 的验收命令应检查 HTML 文件。"""
    with tempfile.TemporaryDirectory() as d:
        tasks = _deterministic_roadmap("做一个网页", d)
    has_file_check = any("index.html" in cmd for t in tasks for cmd in t.verify_cmd)
    assert has_file_check, "至少一个任务应检查 index.html"


def test_deterministic_roadmap_tasks_have_distinct_ids():
    """确定性 roadmap 的任务 id 不重复。"""
    with tempfile.TemporaryDirectory() as d:
        tasks = _deterministic_roadmap("做一个计算器", d)
    ids = [t.id for t in tasks]
    assert len(ids) == len(set(ids)), "任务 id 不重复"


def test_default_planner_fallback_uses_deterministic_roadmap():
    """GLM 失败时，default_planner 使用确定性 roadmap 而非单个 true 任务。"""
    state = FactoryState(
        factory_id="f",
        product_goal="做一个计算器",
        cwd="/tmp",
        status=FactoryStatus.pending,
        roadmap=[],
    )
    with patch("driving.factory_loop._make_llm", side_effect=RuntimeError("no model")):
        tasks = default_planner(state)
    assert len(tasks) >= 2, "确定性 fallback 应生成多个任务"
    for t in tasks:
        assert t.verify_cmd[0] != "true", "不应使用 true 作为验收命令"


def test_default_planner_fallback_feedback_mentions_deterministic():
    """GLM 失败时，task feedback 应提及确定性 fallback。"""
    state = FactoryState(
        factory_id="f",
        product_goal="做一个网页",
        cwd="/tmp",
        status=FactoryStatus.pending,
        roadmap=[],
    )
    with patch("driving.factory_loop._make_llm", side_effect=RuntimeError("no model")):
        tasks = default_planner(state)
    has_feedback = any("deterministic" in (t.feedback or "").lower() or "确定性" in (t.feedback or "") for t in tasks)
    assert has_feedback, "feedback 应提及确定性 fallback"


def test_e2e_direction_to_iteration_with_deterministic_planner(monkeypatch):
    """E2E: 方向 → 确定性 planner → 执行 → proposer → 停止。

    模拟 GLM 完全不可用：
    - planner fail-open 用确定性 roadmap
    - task_proposer fail-open 返回 None
    - 工厂执行完确定性 roadmap 后自然停止
    """
    # 启用 auto-proposer（conftest 默认禁用）
    monkeypatch.setenv("FLIPPED_AUTO_PROPOSER", "1")
    # mock GLM 不可用
    monkeypatch.setattr("driving.factory_loop._make_llm", lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("no GLM")))
    monkeypatch.setattr("driving.task_proposer._make_llm", lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("no GLM")))
    # mock auto_fix 为 no-op（确保 design_fix_fallback 不干扰 E2E 测试）
    monkeypatch.setattr("driving.design_context.auto_fix_design_issues", lambda cwd: None)

    def fake_orchestrator(task, state):
        # 模拟 worker：在 cwd 创建包含 CSS 变量和交互元素的 HTML
        html_path = os.path.join(state.cwd, "index.html")
        good_html = """<!DOCTYPE html>
<html lang="zh"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<style>:root { --color-bg: #0D0D12; --color-text: #F5F5F5; --color-accent: #0A84FF; }
body { margin: 0; padding: 16px; }</style>
</head><body><header></header><main><h1>Test</h1><button>Click</button></main><footer></footer>
</body></html>"""
        with open(html_path, "w") as f:
            f.write(good_html)
        return TaskResult(task=task, verified=True, stop_reason="verified", iteration=1)

    with tempfile.TemporaryDirectory() as d:
        state = run_factory_loop(
            product_goal="做一个落地页",
            cwd=d,
            db_path=os.path.join(d, "test_factory.db"),
            max_tasks=10,
            max_rounds=2,
            orchestrator_fn=fake_orchestrator,
        )

    # 应该执行了确定性 roadmap 的任务（至少 2 个）
    assert len(state.completed) >= 2, f"应执行至少 2 个任务，实际 {len(state.completed)}"
    assert state.status.value == "done"


# ---------- M50: 增强确定性 roadmap — 更多 UI 组件任务 ----------


def test_deterministic_roadmap_has_at_least_six_tasks():
    """M50: 确定性 roadmap 应生成至少 6 个任务（覆盖更多 UI 维度）。"""
    with tempfile.TemporaryDirectory() as d:
        tasks = _deterministic_roadmap("做一个落地页", d)
    assert len(tasks) >= 6, f"M50 应生成≥6 个任务，实际 {len(tasks)}"


def test_deterministic_roadmap_covers_responsive():
    """M50: 确定性 roadmap 应包含响应式布局任务。"""
    with tempfile.TemporaryDirectory() as d:
        tasks = _deterministic_roadmap("做一个网页", d)
    has_responsive = any(
        "响应" in t.description or "responsive" in t.description.lower() or "@media" in t.description
        for t in tasks
    )
    assert has_responsive, "应包含响应式布局任务"


def test_deterministic_roadmap_covers_accessibility():
    """M50: 确定性 roadmap 应包含无障碍任务。"""
    with tempfile.TemporaryDirectory() as d:
        tasks = _deterministic_roadmap("做一个网页", d)
    has_a11y = any(
        "无障碍" in t.description or "aria" in t.description.lower() or "alt" in t.description.lower()
        for t in tasks
    )
    assert has_a11y, "应包含无障碍任务"


def test_deterministic_roadmap_covers_animations():
    """M50: 确定性 roadmap 应包含动画任务。"""
    with tempfile.TemporaryDirectory() as d:
        tasks = _deterministic_roadmap("做一个网页", d)
    has_anim = any(
        "动画" in t.description or "animation" in t.description.lower()
        or "transition" in t.description.lower() or "微交" in t.description
        for t in tasks
    )
    assert has_anim, "应包含动画/微交互任务"


def test_deterministic_roadmap_covers_hero_section():
    """M50: 确定性 roadmap 应包含 hero 区块任务。"""
    with tempfile.TemporaryDirectory() as d:
        tasks = _deterministic_roadmap("做一个落地页", d)
    has_hero = any(
        "hero" in t.description.lower() or "首屏" in t.description or "主视觉" in t.description
        for t in tasks
    )
    assert has_hero, "应包含 hero/首屏区块任务"


def test_deterministic_roadmap_all_verify_cmds_check_content():
    """M50: 所有任务的验收命令都检查 HTML 文件内容（非 true）。"""
    with tempfile.TemporaryDirectory() as d:
        tasks = _deterministic_roadmap("做一个网页", d)
    for t in tasks:
        assert t.verify_cmd, f"任务 {t.id} 缺少验收命令"
        assert t.verify_cmd[0] != "true", f"任务 {t.id} 验收命令不应是 true"
        assert "index.html" in t.verify_cmd[0], f"任务 {t.id} 验收命令应检查 index.html"


# ---- M94 factory_loop RCA + Gold Memory 集成 ----

def test_m94_factory_loop_uses_analyze_failure_with_memory(tmp_db, tmp_cwd):
    """M94: factory_loop 失败时调用 analyze_failure_with_memory(非旧 analyze_failure)。

    验证 M91.1 集成缺口已修复:RCA 查 Gold Memory 历史失败,形成学习闭环。
    """
    from driving.rca import reset_failure_counter, analyze_failure_with_memory

    reset_failure_counter()

    def fake_orchestrator(task: FactoryTask, state: FactoryState) -> TaskResult:
        return TaskResult(
            task=task, verified=False, stop_reason="verify_failed",
            iteration=1, summary="assertion failed",
        )

    def stub_planner(state: FactoryState) -> list[FactoryTask]:
        return [make_task("实现登录页面", verify_cmd=["false"])]

    with patch("driving.rca.analyze_failure_with_memory",
               wraps=analyze_failure_with_memory) as mock_rca:
        run_factory_loop(
            product_goal="build login",
            cwd=tmp_cwd,
            db_path=str(tmp_db),
            planner=stub_planner,
            orchestrator_fn=fake_orchestrator,
            max_tasks=10,
        )

    # analyze_failure_with_memory 被调用(每次失败一次,3 次重试 = 3 次)
    assert mock_rca.call_count >= 1, "factory_loop 失败时应调用 analyze_failure_with_memory"
    # 关键:传了 task_description(M91.1 语义检索的钥匙)
    first_call_kwargs = mock_rca.call_args_list[0].kwargs
    assert "task_description" in first_call_kwargs, "应传 task_description 给 RCA"
    assert first_call_kwargs["task_description"], "task_description 不应为空"


def test_m94_factory_loop_feedback_includes_rca(tmp_db, tmp_cwd):
    """M94: 失败后 task.feedback 含 RCA 根因信息(非泛泛'失败了')。"""
    from driving.rca import reset_failure_counter

    reset_failure_counter()

    def fake_orchestrator(task: FactoryTask, state: FactoryState) -> TaskResult:
        return TaskResult(
            task=task, verified=False, stop_reason="verify_failed",
            iteration=1, summary="SyntaxError: invalid syntax",
        )

    def stub_planner(state: FactoryState) -> list[FactoryTask]:
        return [make_task("写一个 Python 函数", verify_cmd=["false"])]

    result = run_factory_loop(
        product_goal="build func",
        cwd=tmp_cwd,
        db_path=str(tmp_db),
        planner=stub_planner,
        orchestrator_fn=fake_orchestrator,
        max_tasks=10,
    )

    # feedback 应含 RCA 根因(syntax_error 被 enrich_feedback 注入)
    assert result.failed, "应有失败记录"
    # 检查 roadmap 中的 task feedback(M94 后应含 RCA 信息)
    failed_task = result.roadmap[0]
    assert "RCA" in failed_task.feedback or "根因" in failed_task.feedback, \
        f"feedback 应含 RCA 根因,实际: {failed_task.feedback[:200]}"


def test_m94_gold_memory_writeback_on_failure(tmp_db, tmp_cwd):
    """M94: 任务失败后写回 Gold Memory(写回闭环已存在,M94 验证它不被 RCA 升级破坏)。"""
    from driving.rca import reset_failure_counter

    reset_failure_counter()

    record_calls = []

    def fake_orchestrator(task: FactoryTask, state: FactoryState) -> TaskResult:
        return TaskResult(
            task=task, verified=False, stop_reason="verify_failed",
            iteration=1, summary="fail",
        )

    def stub_planner(state: FactoryState) -> list[FactoryTask]:
        return [make_task("测试任务", verify_cmd=["false"])]

    with patch("driving.gold_memory.record_task_result",
               side_effect=lambda *a, **kw: record_calls.append(a)):
        run_factory_loop(
            product_goal="test",
            cwd=tmp_cwd,
            db_path=str(tmp_db),
            planner=stub_planner,
            orchestrator_fn=fake_orchestrator,
            max_tasks=10,
        )

    # 失败也应写回 Gold Memory(M10.4-D)
    assert len(record_calls) >= 1, "失败时应写回 Gold Memory"


# ---- M130 AgentCLI 集成测试 ----

def test_m130_factory_loop_creates_worktree_on_task_start(tmp_db, tmp_cwd):
    """M130: 任务开始时 factory_loop 应调用 AgentCLI 创建 worktree。"""
    from unittest.mock import MagicMock

    cli_calls = []

    def fake_orchestrator(task: FactoryTask, state: FactoryState) -> TaskResult:
        return TaskResult(
            task=task, verified=True, stop_reason="done",
            iteration=1, summary="ok",
        )

    def stub_planner(state: FactoryState) -> list[FactoryTask]:
        return [make_task("实现功能", verify_cmd=["true"])]

    with patch("driving.agent_cli.AgentCLI") as MockCLI:
        mock_cli = MagicMock()
        mock_cli.worktree_create.return_value = MagicMock(success=True, output={"worktree_id": "wt-123"})
        mock_cli.status_update.return_value = MagicMock(success=True)
        mock_cli.worktree_merge.return_value = MagicMock(success=True)
        mock_cli.worktree_remove.return_value = MagicMock(success=True)
        MockCLI.return_value = mock_cli

        result = run_factory_loop(
            product_goal="build feature",
            cwd=tmp_cwd,
            db_path=str(tmp_db),
            planner=stub_planner,
            orchestrator_fn=fake_orchestrator,
            max_tasks=1,
        )

    assert mock_cli.worktree_create.called, "任务开始时应调用 worktree_create"
    assert mock_cli.status_update.called, "任务开始时应调用 status_update"
    assert mock_cli.worktree_merge.called, "任务成功时应调用 worktree_merge"
    assert mock_cli.worktree_remove.called, "任务结束时应调用 worktree_remove"
    assert result.cli_stats["worktree_create"] == 1
    assert result.cli_stats["worktree_merge"] == 1
    assert result.cli_stats["worktree_remove"] == 1


def test_m130_factory_loop_updates_status_on_failure(tmp_db, tmp_cwd):
    """M130: 任务失败时 factory_loop 应更新 Agent 状态为 failed。"""
    from unittest.mock import MagicMock

    def fake_orchestrator(task: FactoryTask, state: FactoryState) -> TaskResult:
        return TaskResult(
            task=task, verified=False, stop_reason="verify_failed",
            iteration=1, summary="fail",
        )

    def stub_planner(state: FactoryState) -> list[FactoryTask]:
        return [make_task("失败任务", verify_cmd=["false"])]

    with patch("driving.agent_cli.AgentCLI") as MockCLI:
        mock_cli = MagicMock()
        mock_cli.worktree_create.return_value = MagicMock(success=True, output={"worktree_id": "wt-123"})
        mock_cli.status_update.return_value = MagicMock(success=True)
        mock_cli.worktree_remove.return_value = MagicMock(success=True)
        MockCLI.return_value = mock_cli

        run_factory_loop(
            product_goal="build fail",
            cwd=tmp_cwd,
            db_path=str(tmp_db),
            planner=stub_planner,
            orchestrator_fn=fake_orchestrator,
            max_tasks=1,
        )

    calls = mock_cli.status_update.call_args_list
    status_calls = [str(call.args[1]) for call in calls]
    assert "failed" in status_calls, "任务失败时应更新状态为 failed"


def test_m130_factory_loop_fan_out_mode(tmp_db, tmp_cwd):
    """M130: Fan-out 模式下 factory_loop 应调用 fan_out 命令。"""
    from unittest.mock import MagicMock

    def stub_planner(state: FactoryState) -> list[FactoryTask]:
        return [make_task("并行任务", verify_cmd=["true"])]

    with patch("driving.agent_cli.AgentCLI") as MockCLI:
        mock_cli = MagicMock()
        mock_cli.worktree_create.return_value = MagicMock(success=True, output={"worktree_id": "wt-123"})
        mock_cli.status_update.return_value = MagicMock(success=True)
        mock_cli.fan_out.return_value = MagicMock(
            success=True,
            output={"winner": {"agent_id": "agent-1", "score": 0.95}},
            message="Fan-out complete",
        )
        mock_cli.worktree_remove.return_value = MagicMock(success=True)
        MockCLI.return_value = mock_cli

        result = run_factory_loop(
            product_goal="build parallel",
            cwd=tmp_cwd,
            db_path=str(tmp_db),
            planner=stub_planner,
            fan_out_mode=True,
            max_tasks=1,
        )

    assert mock_cli.fan_out.called, "Fan-out 模式应调用 fan_out"
    assert result.cli_stats["fan_out"] == 1
    assert result.completed, "Fan-out 胜出应标记任务完成"


def test_m130_factory_loop_cli_fail_open(tmp_db, tmp_cwd):
    """M130: AgentCLI 导入失败或异常时 factory_loop 应继续运行(fail-open)。"""
    def fake_orchestrator(task: FactoryTask, state: FactoryState) -> TaskResult:
        return TaskResult(
            task=task, verified=True, stop_reason="done",
            iteration=1, summary="ok",
        )

    def stub_planner(state: FactoryState) -> list[FactoryTask]:
        return [make_task("测试任务", verify_cmd=["true"])]

    with patch("driving.agent_cli.AgentCLI", side_effect=ImportError("missing")):
        result = run_factory_loop(
            product_goal="build test",
            cwd=tmp_cwd,
            db_path=str(tmp_db),
            planner=stub_planner,
            orchestrator_fn=fake_orchestrator,
            max_tasks=1,
        )

    assert result.status == FactoryStatus.done, "CLI 失败时工厂应正常完成"
    assert result.completed, "任务应正常完成"
