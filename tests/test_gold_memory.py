"""gold_memory 单元测试（M10.4-D）。"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from driving.gold_memory import (
    record_task_result,
    query_similar,
    build_memory_hint,
    clear_memory,
    stats,
    _signature,
)
from driving.factory_loop import FactoryTask, FactoryState, TaskResult


def _make_task(desc="实现登录页面", verify_cmd=None):
    return FactoryTask(id="t1", description=desc, verify_cmd=verify_cmd or ["true"])


def _make_state(design_style="dark"):
    return FactoryState(
        factory_id="f1", product_goal="goal", cwd="/tmp", roadmap=[],
        design_style=design_style,
    )


def _make_result(verified=True, stop_reason="verified", summary="ok"):
    task = _make_task()
    return TaskResult(task=task, verified=verified, stop_reason=stop_reason, summary=summary, iteration=1)


def test_empty_memory_returns_no_result():
    with tempfile.TemporaryDirectory() as d:
        db = f"{d}/gold.db"
        r = query_similar("任意任务", db_path=db)
        assert not r.found


def test_record_and_query_success():
    with tempfile.TemporaryDirectory() as d:
        db = f"{d}/gold.db"
        task = _make_task(verify_cmd=["python -m pytest tests/test_login.py"])
        state = _make_state()
        result = _make_result(verified=True)
        record_task_result(task, state, result, db)
        # 查询相似任务
        q = query_similar("实现登录页面", design_style="dark", db_path=db)
        assert q.found
        assert q.success_rate == 1.0
        assert "pytest" in q.recommended_verify_cmd


def test_signature_order_independent():
    """相同关键词不同顺序 → 相同签名。"""
    s1 = _signature("实现登录页面")
    s2 = _signature("登录页面实现")
    # 中文字符提取后排序，应相同
    assert s1 == s2


def test_record_failure():
    with tempfile.TemporaryDirectory() as d:
        db = f"{d}/gold.db"
        task = _make_task(verify_cmd=["false"])
        state = _make_state()
        result = _make_result(verified=False, stop_reason="verify_failed", summary="测试失败")
        record_task_result(task, state, result, db)
        q = query_similar("实现登录页面", db_path=db)
        assert q.found
        assert q.success_rate == 0.0
        assert "测试失败" in q.notes[0]


def test_success_rate_aggregation():
    with tempfile.TemporaryDirectory() as d:
        db = f"{d}/gold.db"
        task = _make_task(verify_cmd=["cmd1"])
        state = _make_state()
        # 记录 3 次：2 成功 1 失败（不同 verify_cmd）
        for i, (v, ok) in enumerate([("a", True), ("b", True), ("c", False)]):
            t = FactoryTask(id=f"t{i}", description="实现登录页面", verify_cmd=[v])
            r = TaskResult(task=t, verified=ok, stop_reason="verified" if ok else "fail", summary=f"r{i}", iteration=1)
            record_task_result(t, state, r, db)
        q = query_similar("实现登录页面", db_path=db)
        assert q.total_attempts == 3
        assert q.successful_attempts == 2
        assert q.success_rate == pytest.approx(2/3)


def test_upsert_replaces_duplicate():
    """相同 (signature, style, verify_cmd) 的记录被 upsert。"""
    with tempfile.TemporaryDirectory() as d:
        db = f"{d}/gold.db"
        task = _make_task(verify_cmd=["same_cmd"])
        state = _make_state()
        # 第一次失败
        record_task_result(task, state, _make_result(verified=False, summary="first"), db)
        # 第二次成功（相同 key，upsert）
        record_task_result(task, state, _make_result(verified=True, summary="second"), db)
        q = query_similar("实现登录页面", db_path=db)
        assert q.total_attempts == 1  # upsert 不新增
        assert q.success_rate == 1.0


def test_build_memory_hint_empty():
    with tempfile.TemporaryDirectory() as d:
        db = f"{d}/gold.db"
        assert build_memory_hint("新任务", db_path=db) == ""


def test_build_memory_hint_with_history():
    with tempfile.TemporaryDirectory() as d:
        db = f"{d}/gold.db"
        task = _make_task(verify_cmd=["python -m pytest"])
        state = _make_state()
        record_task_result(task, state, _make_result(verified=True), db)
        hint = build_memory_hint("实现登录页面", design_style="dark", db_path=db)
        assert "Gold Memory" in hint
        assert "成功" in hint
        assert "pytest" in hint


def test_stats():
    with tempfile.TemporaryDirectory() as d:
        db = f"{d}/gold.db"
        task = _make_task()
        state = _make_state()
        record_task_result(task, state, _make_result(verified=True), db)
        record_task_result(task, state, _make_result(verified=False), db)
        s = stats(db_path=db)
        assert s["total_entries"] == 1  # upsert 同 key
        assert s["successful"] == 0  # 最后一次是失败


def test_design_style_filter():
    """不同 design_style 的经验互不干扰。"""
    with tempfile.TemporaryDirectory() as d:
        db = f"{d}/gold.db"
        task = _make_task()
        # dark 风格记录成功
        record_task_result(task, _make_state("dark"), _make_result(verified=True), db)
        # minimalism 风格记录失败
        record_task_result(task, _make_state("minimalism"), _make_result(verified=False), db)
        # 查 dark
        q = query_similar("实现登录页面", design_style="dark", db_path=db)
        assert q.success_rate == 1.0
        # 查 minimalism
        q2 = query_similar("实现登录页面", design_style="minimalism", db_path=db)
        assert q2.success_rate == 0.0


def test_clear_memory():
    with tempfile.TemporaryDirectory() as d:
        db = f"{d}/gold.db"
        task = _make_task()
        state = _make_state()
        record_task_result(task, state, _make_result(), db)
        clear_memory(db)
        assert stats(db_path=db)["total_entries"] == 0


def test_semantic_search_finds_similar_different_words():
    """M11.2：不同用词但语义相似的任务能通过向量检索命中。

    MockEmbedding 按空格分词，英文描述有共享单词时余弦相似度 > 0。
    """
    from unittest.mock import patch, MagicMock
    import driving.gold_memory as gm

    # 构造一个简单的 mock embedding：返回基于关键词的向量
    class FakeEmbed:
        def embed(self, texts):
            vecs = []
            for t in texts:
                t = t.lower()
                # 3 维向量：login / page / form
                v = [0.0, 0.0, 0.0]
                if "login" in t or "signin" in t or "登录" in t:
                    v[0] = 1.0
                if "page" in t or "页面" in t or "页" in t:
                    v[1] = 1.0
                if "form" in t or "表单" in t:
                    v[2] = 1.0
                norm = sum(x * x for x in v) ** 0.5 or 1.0
                vecs.append([x / norm for x in v])
            return vecs

    with tempfile.TemporaryDirectory() as d:
        db = f"{d}/gold.db"
        # 记录一个 "create login page" 任务
        task = _make_task(desc="create login page", verify_cmd=["true"])
        state = _make_state()
        result = _make_result(verified=True, summary="login ok")

        with patch.object(gm, "_get_embedding_model", return_value=FakeEmbed()):
            record_task_result(task, state, result, db)
            # 用不同用词查询，但语义相同
            q = query_similar("build a signin page", design_style="dark", db_path=db)
            assert q.found  # 语义匹配命中
            assert q.success_rate == 1.0


def test_cosine_similarity():
    """M11.2：余弦相似度计算正确。"""
    from driving.gold_memory import _cosine_similarity
    assert _cosine_similarity([1, 0, 0], [1, 0, 0]) == pytest.approx(1.0)
    assert _cosine_similarity([1, 0, 0], [0, 1, 0]) == pytest.approx(0.0)
    assert _cosine_similarity([1, 1, 0], [1, 0, 0]) == pytest.approx(0.707, abs=0.01)
    assert _cosine_similarity([], [1, 0]) == 0.0
    assert _cosine_similarity([1, 0], [1, 0, 0]) == 0.0  # 维度不匹配
