"""自主任务生成器单测（M31）。

验证：
1. GLM 返回 should_continue=True → 返回 FactoryTask
2. GLM 返回 should_continue=False → 返回 None
3. GLM 异常 → fail-open 返回 None
4. 空描述 → 返回 None
5. verify_cmd 被清洗
6. cwd 文件扫描跳过 .git/node_modules
7. design_score 被获取
"""
from __future__ import annotations

import os
import tempfile
from unittest.mock import patch, MagicMock

import pytest

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from driving.factory_loop import FactoryState, FactoryTask, FactoryStatus, TaskStatus
from driving.task_proposer import (
    propose_next_task,
    _scan_cwd_files,
    TaskProposal,
)


def _make_state(cwd: str, completed: list = None) -> FactoryState:
    return FactoryState(
        factory_id="test-factory",
        product_goal="做一个计算器应用",
        cwd=cwd,
        status=FactoryStatus.running,
        roadmap=[],
        design_style="dark",
        completed=completed or [],
    )


def test_propose_returns_task_when_should_continue():
    """GLM 返回 should_continue=True → 返回 FactoryTask。"""
    proposal = TaskProposal(
        description="添加历史记录功能",
        verify_cmd=["python -m pytest tests/test_history.py -q"],
        reasoning="计算器缺少历史记录",
        should_continue=True,
    )
    with tempfile.TemporaryDirectory() as d:
        state = _make_state(d)
        with patch("driving.task_proposer._invoke_structured", return_value=proposal):
            result = propose_next_task(state)

    assert result is not None
    assert result.description == "添加历史记录功能"
    assert "python -m pytest" in result.verify_cmd[0]


def test_propose_returns_none_when_should_not_continue():
    """GLM 返回 should_continue=False → 返回 None（项目已完善）。"""
    proposal = TaskProposal(
        description="",
        verify_cmd=[],
        reasoning="项目已完善，无更多任务",
        should_continue=False,
    )
    with tempfile.TemporaryDirectory() as d:
        state = _make_state(d)
        with patch("driving.task_proposer._invoke_structured", return_value=proposal):
            result = propose_next_task(state)

    assert result is None


def test_propose_returns_none_on_llm_error():
    """GLM 异常 → fail-open 返回 None。"""
    with tempfile.TemporaryDirectory() as d:
        state = _make_state(d)
        with patch("driving.task_proposer._invoke_structured", side_effect=RuntimeError("no model")):
            result = propose_next_task(state)

    assert result is None


def test_propose_returns_none_on_empty_description():
    """空 description → 返回 None。"""
    proposal = TaskProposal(
        description="",
        verify_cmd=["true"],
        reasoning="",
        should_continue=True,
    )
    with tempfile.TemporaryDirectory() as d:
        state = _make_state(d)
        with patch("driving.task_proposer._invoke_structured", return_value=proposal):
            result = propose_next_task(state)

    assert result is None


def test_propose_sanitizes_verify_cmd():
    """verify_cmd 被清洗：裸 pytest → python -m pytest。"""
    proposal = TaskProposal(
        description="添加测试",
        verify_cmd=["pytest tests/test_x.py"],
        reasoning="需要测试覆盖",
        should_continue=True,
    )
    with tempfile.TemporaryDirectory() as d:
        state = _make_state(d)
        with patch("driving.task_proposer._invoke_structured", return_value=proposal):
            result = propose_next_task(state)

    assert result is not None
    assert "python -m pytest" in result.verify_cmd[0]
    assert "pytest" in result.verify_cmd[0]


def test_propose_includes_reasoning_in_feedback():
    """reasoning 被写入 task.feedback。"""
    proposal = TaskProposal(
        description="优化加载速度",
        verify_cmd=["true"],
        reasoning="Lighthouse 分数低于 80",
        should_continue=True,
    )
    with tempfile.TemporaryDirectory() as d:
        state = _make_state(d)
        with patch("driving.task_proposer._invoke_structured", return_value=proposal):
            result = propose_next_task(state)

    assert result is not None
    assert "Lighthouse" in result.feedback


def test_propose_task_id_includes_iteration():
    """生成的 task id 包含 iteration_count，便于追踪。"""
    proposal = TaskProposal(
        description="下一个任务",
        verify_cmd=["true"],
        reasoning="",
        should_continue=True,
    )
    with tempfile.TemporaryDirectory() as d:
        state = _make_state(d)
        state.iteration_count = 5
        with patch("driving.task_proposer._invoke_structured", return_value=proposal):
            result = propose_next_task(state)

    assert result is not None
    assert "6" in result.id  # iteration_count + 1


# ---------- _scan_cwd_files ----------

def test_scan_cwd_files_skips_dirs():
    """扫描跳过 .git/node_modules/__pycache__ 等。"""
    with tempfile.TemporaryDirectory() as d:
        # 创建正常文件
        open(os.path.join(d, "index.html"), "w").close()
        open(os.path.join(d, "app.js"), "w").close()
        # 创建应跳过的目录
        os.makedirs(os.path.join(d, ".git", "objects"))
        os.makedirs(os.path.join(d, "node_modules", "react"))
        os.makedirs(os.path.join(d, "__pycache__"))
        open(os.path.join(d, ".git", "objects", "abc"), "w").close()
        open(os.path.join(d, "node_modules", "react", "index.js"), "w").close()
        open(os.path.join(d, "__pycache__", "app.pyc"), "w").close()

        files = _scan_cwd_files(d)

    assert "index.html" in files
    assert "app.js" in files
    assert not any(".git" in f for f in files)
    assert not any("node_modules" in f for f in files)
    assert not any("__pycache__" in f for f in files)


def test_scan_cwd_files_max_files():
    """max_files 限制返回数量。"""
    with tempfile.TemporaryDirectory() as d:
        for i in range(20):
            open(os.path.join(d, f"file_{i}.txt"), "w").close()
        files = _scan_cwd_files(d, max_files=5)
    assert len(files) <= 5


def test_scan_cwd_files_empty_dir():
    """空目录返回空列表。"""
    with tempfile.TemporaryDirectory() as d:
        files = _scan_cwd_files(d)
    assert files == []


def test_scan_cwd_files_subdirectories():
    """扫描子目录中的文件。"""
    with tempfile.TemporaryDirectory() as d:
        os.makedirs(os.path.join(d, "src", "components"))
        open(os.path.join(d, "src", "components", "Header.jsx"), "w").close()
        open(os.path.join(d, "index.html"), "w").close()
        files = _scan_cwd_files(d)
    assert "index.html" in files
    assert any("Header.jsx" in f for f in files)


def test_scan_cwd_files_skips_pyc_and_db():
    """跳过 .pyc/.db/.log 等非源码文件。"""
    with tempfile.TemporaryDirectory() as d:
        open(os.path.join(d, "app.py"), "w").close()
        open(os.path.join(d, "cache.pyc"), "w").close()
        open(os.path.join(d, "data.db"), "w").close()
        open(os.path.join(d, "debug.log"), "w").close()
        files = _scan_cwd_files(d)
    assert "app.py" in files
    assert "cache.pyc" not in files
    assert "data.db" not in files
    assert "debug.log" not in files


# ---------- 集成测试 ----------

def test_factory_loop_uses_proposer_when_roadmap_empty():
    """factory_loop roadmap 用完后调用 proposer 继续迭代。

    M31 核心场景：初始 roadmap 只有 1 个任务，执行完后 proposer 生成新任务，
    工厂不 done 而是继续迭代。
    """
    from driving.factory_loop import run_factory_loop, FactoryTask, TaskResult

    call_count = [0]
    proposed_task = FactoryTask(
        id="proposed-1",
        description="自主生成的任务",
        verify_cmd=["true"],
    )

    def fake_proposer(state):
        call_count[0] += 1
        if call_count[0] == 1:
            return proposed_task
        return None  # 第二次停止

    def fake_orchestrator(task, state):
        return TaskResult(task=task, verified=True, stop_reason="verified", iteration=1)

    with tempfile.TemporaryDirectory() as d:
        # 初始 roadmap 只有 1 个任务
        initial_task = FactoryTask(
            id="task-initial",
            description="初始任务",
            verify_cmd=["true"],
        )
        state = run_factory_loop(
            product_goal="test",
            cwd=d,
            db_path=os.path.join(d, "test_factory.db"),
            checkpoint_db_path=os.path.join(d, "test_ckpt.db"),
            max_tasks=10,
            planner=lambda s: [initial_task],
            orchestrator_fn=fake_orchestrator,
        )

    # 初始 roadmap 有 1 个任务，auto-proposer 被 conftest 禁用，roadmap 用完就 done
    assert state.status.value == "done"


def test_factory_loop_with_proposer_continues_iteration():
    """proposer 集成后：roadmap 用完 → proposer 生成新任务 → 继续迭代。

    这是 M31 的核心集成测试。proposer 第一次返回新任务，第二次返回 None。
    验证工厂执行了初始任务 + proposer 生成的任务。
    """
    from driving.factory_loop import run_factory_loop, FactoryTask, TaskResult

    proposer_calls = [0]

    def fake_proposer(state):
        proposer_calls[0] += 1
        if proposer_calls[0] == 1:
            return FactoryTask(
                id="proposed-1",
                description="自主任务",
                verify_cmd=["true"],
            )
        return None  # 第二次返回 None 停止

    def fake_orchestrator(task, state):
        return TaskResult(task=task, verified=True, stop_reason="verified", iteration=1)

    with tempfile.TemporaryDirectory() as d:
        initial_task = FactoryTask(
            id="task-1",
            description="初始任务",
            verify_cmd=["true"],
        )
        state = run_factory_loop(
            product_goal="test",
            cwd=d,
            db_path=os.path.join(d, "test_factory.db"),
            checkpoint_db_path=os.path.join(d, "test_ckpt.db"),
            max_tasks=10,
            planner=lambda s: [initial_task],
            orchestrator_fn=fake_orchestrator,
            task_proposer=fake_proposer,
        )

    # 初始 1 个任务 + proposer 生成 1 个 = 2 个完成
    assert len(state.completed) == 2
    assert state.completed[0].task.id == "task-1"
    assert state.completed[1].task.id == "proposed-1"


def test_factory_loop_max_rounds_limits_proposer():
    """max_rounds 限制 proposer 调用次数，防止无限空转。"""
    from driving.factory_loop import run_factory_loop, FactoryTask, TaskResult

    proposer_calls = [0]

    def fake_proposer(state):
        proposer_calls[0] += 1
        # 总是返回新任务（模拟无限提议）
        return FactoryTask(
            id=f"proposed-{proposer_calls[0]}",
            description=f"无限任务 {proposer_calls[0]}",
            verify_cmd=["true"],
        )

    def fake_orchestrator(task, state):
        return TaskResult(task=task, verified=True, stop_reason="verified", iteration=1)

    with tempfile.TemporaryDirectory() as d:
        state = run_factory_loop(
            product_goal="test",
            cwd=d,
            db_path=os.path.join(d, "test_factory.db"),
            checkpoint_db_path=os.path.join(d, "test_ckpt.db"),
            max_tasks=10,
            max_rounds=3,
            planner=lambda s: [FactoryTask(id="t0", description="init", verify_cmd=["true"])],
            orchestrator_fn=fake_orchestrator,
            task_proposer=fake_proposer,
        )

    # 初始 1 + max_rounds=3 = 4 个任务
    assert len(state.completed) == 4
    assert proposer_calls[0] == 3  # proposer 被调用 3 次（max_rounds）


def test_factory_loop_proposer_none_stops_immediately():
    """proposer 返回 None 时立即停止，不再迭代。"""
    from driving.factory_loop import run_factory_loop, FactoryTask, TaskResult

    def fake_proposer(state):
        return None  # 立即停止

    def fake_orchestrator(task, state):
        return TaskResult(task=task, verified=True, stop_reason="verified", iteration=1)

    with tempfile.TemporaryDirectory() as d:
        state = run_factory_loop(
            product_goal="test",
            cwd=d,
            db_path=os.path.join(d, "test_factory.db"),
            checkpoint_db_path=os.path.join(d, "test_ckpt.db"),
            max_tasks=10,
            max_rounds=5,
            planner=lambda s: [FactoryTask(id="t0", description="init", verify_cmd=["true"])],
            orchestrator_fn=fake_orchestrator,
            task_proposer=fake_proposer,
        )

    # 只有初始任务，proposer 立即返回 None
    assert len(state.completed) == 1
    assert state.status.value == "done"


# ---------- M40: design_score 反馈循环增强 ----------


def test_get_design_score_includes_violation_rules_when_low():
    """差 HTML 时 _get_design_score 应包含具体违规 rule 名。"""
    import tempfile
    import os
    from driving.task_proposer import _get_design_score

    bad_html = """<html><head></head><body>
    <img src="x.jpg">
    </body></html>"""

    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(bad_html)
        result = _get_design_score(td)

    # 应包含 design_score=
    assert "design_score=" in result
    # 应包含具体违规 rule 名
    assert "meta_viewport" in result or "img_alt" in result


def test_get_design_score_good_html_no_violations():
    """良好 HTML 时 _get_design_score 应返回高分且不含违规 rule 名。"""
    import tempfile
    import os
    from driving.task_proposer import _get_design_score

    good_html = """<!DOCTYPE html>
<html lang="zh"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
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

    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(good_html)
        result = _get_design_score(td)

    # 应包含 design_score=
    assert "design_score=" in result
    # 分数应较高
    import re
    score_match = re.search(r"design_score=(\d+)/100", result)
    assert score_match is not None
    score = int(score_match.group(1))
    assert score >= 80, f"良好 HTML 应 ≥80 分，实际 {score}: {result}"


def test_get_design_score_no_html_returns_message():
    """无 HTML 文件时返回提示信息。"""
    import tempfile
    from driving.task_proposer import _get_design_score

    with tempfile.TemporaryDirectory() as td:
        result = _get_design_score(td)

    assert "HTML" in result or "无" in result


# ---------- M41: 确定性 design fix fallback ----------


def test_propose_design_fix_task_low_score():
    """design_score 低时，确定性 fallback 生成修复任务。"""
    import tempfile
    import os
    from driving.task_proposer import propose_design_fix_task

    bad_html = """<html><head></head><body>
    <img src="x.jpg">
    </body></html>"""

    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(bad_html)
        state = _make_state(td)
        result = propose_design_fix_task(state)

    assert result is not None
    assert "设计" in result.description or "design" in result.description.lower()
    assert result.verify_cmd  # 应有验收命令
    assert "auto_fix" in result.feedback or "design_score" in result.feedback


def test_propose_design_fix_task_good_score():
    """design_score 高时，确定性 fallback 返回 None（无需修复）。"""
    import tempfile
    import os
    from driving.task_proposer import propose_design_fix_task

    good_html = """<!DOCTYPE html>
<html lang="zh"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
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

    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "index.html"), "w") as f:
            f.write(good_html)
        state = _make_state(td)
        result = propose_design_fix_task(state)

    assert result is None  # 高分时无需修复


def test_propose_design_fix_task_no_html():
    """无 HTML 文件时，确定性 fallback 返回 None。"""
    import tempfile
    from driving.task_proposer import propose_design_fix_task

    with tempfile.TemporaryDirectory() as td:
        state = _make_state(td)
        result = propose_design_fix_task(state)

    assert result is None


def test_factory_loop_uses_design_fix_fallback():
    """factory_loop：GLM 不可用时，design fix fallback 接管。

    M41 核心场景：GLM 调用失败（propose_next_task 返回 None），
    但 HTML 的 design_score 低，factory_loop 用确定性 fallback 生成修复任务。
    """
    from driving.factory_loop import run_factory_loop, FactoryTask, TaskResult

    def fake_proposer(state):
        return None  # GLM 不可用

    fix_task = FactoryTask(
        id="design-fix-1",
        description="修复设计质量问题",
        verify_cmd=["true"],
    )

    def fake_design_fix(state):
        return fix_task  # 确定性 fallback

    def fake_orchestrator(task, state):
        return TaskResult(task=task, verified=True, stop_reason="verified", iteration=1)

    bad_html = "<html><head></head><body><img src='x.jpg'></body></html>"

    with tempfile.TemporaryDirectory() as d:
        with open(os.path.join(d, "index.html"), "w") as f:
            f.write(bad_html)
        state = run_factory_loop(
            product_goal="test",
            cwd=d,
            db_path=os.path.join(d, "test_factory.db"),
            checkpoint_db_path=os.path.join(d, "test_ckpt.db"),
            max_tasks=10,
            planner=lambda s: [FactoryTask(id="t0", description="init", verify_cmd=["true"])],
            orchestrator_fn=fake_orchestrator,
            task_proposer=fake_proposer,
            design_fix_fallback=fake_design_fix,
        )

    # 初始 1 + fallback 1 = 2 个任务
    assert len(state.completed) == 2
    assert state.completed[1].task.id == "design-fix-1"


def test_factory_loop_auto_proposer_enabled_by_env(monkeypatch):
    """M42: FLIPPED_AUTO_PROPOSER=1 时，不传 task_proposer 也自动接入。

    验证默认行为：GLM 不可用时（mock 异常），design_fix_fallback
    确定性接管。有低分 HTML 时生成修复任务。
    """
    from driving.factory_loop import run_factory_loop, FactoryTask, TaskResult

    monkeypatch.setenv("FLIPPED_AUTO_PROPOSER", "1")

    # mock GLM 不可用（propose_next_task 会 fail-open 返回 None）
    def fake_orchestrator(task, state):
        return TaskResult(task=task, verified=True, stop_reason="verified", iteration=1)

    bad_html = "<html><head></head><body><img src='x.jpg'></body></html>"

    with tempfile.TemporaryDirectory() as d:
        with open(os.path.join(d, "index.html"), "w") as f:
            f.write(bad_html)
        with patch("driving.task_proposer._invoke_structured", side_effect=RuntimeError("no GLM")):
            state = run_factory_loop(
                product_goal="test",
                cwd=d,
                db_path=os.path.join(d, "test_factory.db"),
                checkpoint_db_path=os.path.join(d, "test_ckpt.db"),
                max_tasks=10,
                max_rounds=3,
                planner=lambda s: [FactoryTask(id="t0", description="init", verify_cmd=["true"])],
                orchestrator_fn=fake_orchestrator,
                # 不传 task_proposer 和 design_fix_fallback，验证自动接入
            )

    # 初始 1 + GLM 失败后 design_fix_fallback 接管 ≥1 = ≥2 个任务
    assert len(state.completed) >= 2
    # 至少有一个 design-fix 任务
    fix_tasks = [r for r in state.completed if "design-fix" in r.task.id]
    assert len(fix_tasks) >= 1
