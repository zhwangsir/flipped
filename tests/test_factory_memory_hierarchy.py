"""M135-C · memory_hierarchy 替换 context_summary 的确定性单测。

验证：
1. _record_to_memory 双写：memory_data 被追加 working 条目
2. _build_ctx_tail：memory 非空时返回最近任务摘要（替代 150 字符截断）
3. _build_ctx_tail：memory 为空时 fallback 到旧 150 字符截断路径
4. memory_data 持久化 roundtrip（save/load 后记忆不丢）
5. fail-open：memory_data 损坏时 fallback，不抛异常
6. 上下文预算：长历史下 ctx_tail 不超 _CTX_BUDGET
"""
from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest  # noqa: E402

from driving.factory_loop import (  # noqa: E402
    _CTX_BUDGET,
    FactoryState,
    FactoryStatus,
    _build_ctx_tail,
    _record_to_memory,
    load_factory_state,
    save_factory_state,
)
from driving.memory_hierarchy import memory_from_dict  # noqa: E402


@pytest.fixture
def tmp_cwd():
    with tempfile.TemporaryDirectory() as td:
        yield td


def _make_state(cwd: str) -> FactoryState:
    return FactoryState(
        factory_id="f-memory",
        product_goal="demo",
        cwd=cwd,
        status=FactoryStatus.running,
        roadmap=[],
        repo_map_cache="cached",
    )


# ---------- 1. 双写：_record_to_memory 追加 working 条目 ----------


def test_record_to_memory_appends_working_item(tmp_cwd):
    """_record_to_memory 后,memory_data 含一条 working 记忆。"""
    state = _make_state(tmp_cwd)
    assert state.memory_data == {}

    _record_to_memory(state, "[task-1] 写函数: done. artifacts=['a.py']")

    mem = memory_from_dict(state.memory_data)
    assert mem is not None, "memory_data 应可反序列化"
    assert len(mem.working) == 1
    assert "task-1" in mem.working[0].content
    assert "done" in mem.working[0].content


def test_record_to_memory_accumulates_across_calls(tmp_cwd):
    """多次调用累加到同一 memory(roundtrip 不丢历史)。"""
    state = _make_state(tmp_cwd)
    for i in range(5):
        _record_to_memory(state, f"[task-{i}] 任务{i}: done.")

    mem = memory_from_dict(state.memory_data)
    assert len(mem.working) == 5


# ---------- 2. _build_ctx_tail：memory 非空时返回分层摘要 ----------


def test_build_ctx_tail_uses_memory_when_present(tmp_cwd):
    """memory 有数据时,ctx_tail 含最近任务摘要(而不是 150 字符截断)。"""
    state = _make_state(tmp_cwd)
    # context_summary 造一个超 150 字符的长串,验证不走截断路径
    state.context_summary = "X" * 500
    _record_to_memory(state, "[task-1] 实现登录: done.")
    _record_to_memory(state, "[task-2] 实现注册: done.")

    ctx = _build_ctx_tail(state, "实现密码重置")

    assert "task-1" in ctx or "task-2" in ctx, "应含最近任务摘要"
    assert "XXX" not in ctx, "不应走 context_summary 截断路径"
    assert len(ctx) <= _CTX_BUDGET


def test_build_ctx_tail_includes_recent_three(tmp_cwd):
    """最近 3 条 working 记忆都应出现在 ctx_tail 里。"""
    state = _make_state(tmp_cwd)
    for i in range(4):
        _record_to_memory(state, f"[task-{i}] 唯一标记{i}: done.")

    ctx = _build_ctx_tail(state, "新任务")
    # 最近 3 条 = task-1/2/3(task-0 掉出窗口,但可能被 search 捞回——只断言最近的必在)
    assert "唯一标记3" in ctx
    assert "唯一标记2" in ctx
    assert "唯一标记1" in ctx


# ---------- 3. fallback：memory 为空时退回旧 150 字符截断 ----------


def test_build_ctx_tail_fallback_to_legacy_truncation(tmp_cwd):
    """memory_data 为空 dict 时,fallback 到 context_summary[-150:]。"""
    state = _make_state(tmp_cwd)
    state.context_summary = "A" * 300

    ctx = _build_ctx_tail(state, "任意任务")

    assert ctx == "A" * 150, "旧路径:尾 150 字符截断"


def test_build_ctx_tail_fallback_empty_summary(tmp_cwd):
    """memory 和 context_summary 都为空时返回'无'。"""
    state = _make_state(tmp_cwd)
    assert _build_ctx_tail(state, "任意任务") == "无"


# ---------- 4. 持久化 roundtrip ----------


def test_memory_data_survives_save_load(tmp_cwd, tmp_path):
    """memory_data 随 FactoryState 持久化(save/load roundtrip)。"""
    db = tmp_path / "factory.db"
    state = _make_state(tmp_cwd)
    _record_to_memory(state, "[task-1] 持久化验证: done.")
    save_factory_state(state, str(db))

    loaded = load_factory_state("f-memory", str(db))
    assert loaded is not None
    mem = memory_from_dict(loaded.memory_data)
    assert mem is not None
    assert len(mem.working) == 1
    assert "持久化验证" in mem.working[0].content


def test_memory_roundtrip_preserves_compressed_recent(tmp_cwd, tmp_path):
    """working 超容量压缩到 recent 后,持久化 roundtrip 仍保留 recent 层。"""
    db = tmp_path / "factory.db"
    state = _make_state(tmp_cwd)
    # max_working=20,写 25 条触发压缩
    for i in range(25):
        _record_to_memory(state, f"[task-{i}] 批量任务{i}: done.")
    save_factory_state(state, str(db))

    loaded = load_factory_state("f-memory", str(db))
    mem = memory_from_dict(loaded.memory_data)
    assert len(mem.working) <= 20, "working 层应被压缩"
    assert len(mem.recent) >= 1, "压缩摘要应进 recent 层"


# ---------- 5. fail-open：损坏数据 ----------


def test_build_ctx_tail_corrupted_memory_fails_open(tmp_cwd):
    """memory_data 损坏(非法结构)时 fallback,不抛异常。"""
    state = _make_state(tmp_cwd)
    state.memory_data = {"working": "不是列表", "recent": 12345}
    state.context_summary = "B" * 200

    ctx = _build_ctx_tail(state, "任意任务")

    assert ctx == "B" * 150, "损坏时应 fallback 到旧截断路径"


def test_record_to_memory_failure_does_not_raise(tmp_cwd):
    """_record_to_memory 内部异常不抛出(fail-open)。"""
    state = _make_state(tmp_cwd)
    # 塞一个会让 memory_from_dict 返回 None 但 memory_to_dict 也可能出问题的值
    state.memory_data = {"working": object()}  # 不可序列化
    _record_to_memory(state, "测试内容")  # 不应抛异常


# ---------- 6. 上下文预算 ----------


def test_ctx_tail_respects_budget_with_long_history(tmp_cwd):
    """大量长记忆下,ctx_tail 仍不超 _CTX_BUDGET(防 M11.1 reasoning overflow)。"""
    state = _make_state(tmp_cwd)
    for i in range(10):
        _record_to_memory(state, f"[task-{i}] " + "很长的任务描述" * 30)

    ctx = _build_ctx_tail(state, "查询任务")

    assert len(ctx) <= _CTX_BUDGET
