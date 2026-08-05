"""M194.2/M194.3 · worker 规则注入预算与 history cap env 化 TDD 测试。

- build_worker_rules_text：max_chars=None（新缺省）时运行期读
  FLIPPED_WORKER_RULES_MAX_CHARS（默认 300，非法值回落 300）；显式传参优先。
- chat 通路预算解析 chat_rules_max_chars()：FLIPPED_CHAT_RULES_MAX_CHARS 优先，
  缺省/非法回落 FLIPPED_WORKER_RULES_MAX_CHARS 解析值。
- WorkerRuleStore._bump trim 改调 _history_cap()：运行期读
  FLIPPED_WORKER_RULES_HISTORY_CAP（默认 20，clamp [1,500]，非法值回落 20）。

测试风格沿用 test_m183_worker_rules.py（纯逻辑，零 FastAPI）。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from driving.worker_rules import (  # noqa: E402
    WorkerRule,
    WorkerRuleStore,
    build_worker_rules_text,
    chat_rules_max_chars,
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """防外部环境变量污染；各用例自行 setenv。"""
    monkeypatch.delenv("FLIPPED_WORKER_RULES_MAX_CHARS", raising=False)
    monkeypatch.delenv("FLIPPED_CHAT_RULES_MAX_CHARS", raising=False)
    monkeypatch.delenv("FLIPPED_WORKER_RULES_HISTORY_CAP", raising=False)


def _mk_rule(rid: str, text: str, *, priority: int = 50,
             scope: str = "worker") -> WorkerRule:
    return WorkerRule(id=rid, text=text, priority=priority, scope=scope)


def _three_rules() -> list[WorkerRule]:
    # 每条 "- AAAA" 长 6 字符；3 条全装需 6+7+7=20 字符预算
    return [_mk_rule("wr-a", "AAAA"), _mk_rule("wr-b", "BBBB"), _mk_rule("wr-c", "CCCC")]


# ====================================================================
# M194.2 · 注入预算 env 化
# ====================================================================

def test_env_max_chars_truncates_injection(monkeypatch):
    """FLIPPED_WORKER_RULES_MAX_CHARS=10 → 只装得下第 1 条，其余整条丢弃。"""
    monkeypatch.setenv("FLIPPED_WORKER_RULES_MAX_CHARS", "10")
    text, applied = build_worker_rules_text(_three_rules())
    assert len(text) <= 10, f"注入输出必须在预算内: {text!r}"
    assert applied == ["wr-a"], "超预算的规则整条丢弃"
    # 尾注 "…(略2条)" 长 6，+1 换行 = 7，6+7>10 装不下 → 直接截掉
    assert "略" not in text


def test_env_max_chars_tail_note_when_fits(monkeypatch):
    """预算够装尾注时追加 …(略N条)（截断语义回归）。"""
    monkeypatch.setenv("FLIPPED_WORKER_RULES_MAX_CHARS", "13")
    text, applied = build_worker_rules_text(_three_rules())
    # 第 1 条 6 字符；第 2 条 +7 → 13 恰好在预算内？6+7=13 ≤ 13 → 装上
    assert applied == ["wr-a", "wr-b"]
    text2, applied2 = build_worker_rules_text(_three_rules(), max_chars=12)
    # 12: 装 1 条（6），第 2 条 6+7=13>12 丢弃 2 条；尾注 6+1=7，6+7=13>12 不装
    assert applied2 == ["wr-a"]
    assert len(text2) <= 12


def test_explicit_max_chars_overrides_env(monkeypatch):
    """显式传参优先于 env（既有调用不破坏）。"""
    monkeypatch.setenv("FLIPPED_WORKER_RULES_MAX_CHARS", "10")
    text, applied = build_worker_rules_text(_three_rules(), max_chars=50)
    assert applied == ["wr-a", "wr-b", "wr-c"], "显式 max_chars=50 必须盖过 env=10"
    assert "略" not in text


def test_invalid_env_max_chars_falls_back_300(monkeypatch):
    """env 非法值（ValueError）→ 回落默认 300。"""
    monkeypatch.setenv("FLIPPED_WORKER_RULES_MAX_CHARS", "abc")
    text, applied = build_worker_rules_text(_three_rules())
    assert applied == ["wr-a", "wr-b", "wr-c"], "非法 env 必须回落 300（3 条全装）"


def test_default_300_without_env():
    """零 env 时行为与旧默认 300 一致（零行为变化）。"""
    long_rules = [_mk_rule(f"wr-{i}", "x" * 100) for i in range(5)]
    text, applied = build_worker_rules_text(long_rules)
    # 每条 "- " + 100 = 102；预算 300 装 2 条（102+103=205），第 3 条 205+103>300
    assert len(applied) == 2
    assert "…(略3条)" in text


def test_chat_rules_max_chars_independent(monkeypatch):
    """FLIPPED_CHAT_RULES_MAX_CHARS 独立：设置后与 worker 值不同时用 chat 值。"""
    monkeypatch.setenv("FLIPPED_WORKER_RULES_MAX_CHARS", "10")
    monkeypatch.setenv("FLIPPED_CHAT_RULES_MAX_CHARS", "50")
    assert chat_rules_max_chars() == 50


def test_chat_rules_max_chars_defaults_to_worker(monkeypatch):
    """chat env 缺省 → 回落 FLIPPED_WORKER_RULES_MAX_CHARS 解析值。"""
    monkeypatch.setenv("FLIPPED_WORKER_RULES_MAX_CHARS", "10")
    assert chat_rules_max_chars() == 10


def test_chat_rules_max_chars_invalid_falls_back(monkeypatch):
    """chat env 非法 → 回落 worker 解析值；双缺省 → 300。"""
    monkeypatch.setenv("FLIPPED_WORKER_RULES_MAX_CHARS", "10")
    monkeypatch.setenv("FLIPPED_CHAT_RULES_MAX_CHARS", "abc")
    assert chat_rules_max_chars() == 10
    monkeypatch.delenv("FLIPPED_WORKER_RULES_MAX_CHARS")
    monkeypatch.setenv("FLIPPED_CHAT_RULES_MAX_CHARS", "abc")
    assert chat_rules_max_chars() == 300


# ====================================================================
# M194.3 · history cap env 化
# ====================================================================

def test_history_cap_env_3(monkeypatch, tmp_path):
    """FLIPPED_WORKER_RULES_HISTORY_CAP=3 → 连续 4 次变更后 history 长度==3。"""
    monkeypatch.setenv("FLIPPED_WORKER_RULES_HISTORY_CAP", "3")
    store = WorkerRuleStore(tmp_path / "rules.json")
    for i in range(4):
        store.add(f"规则{i}")
    versions = store.versions()
    assert len(versions) == 3, f"history 必须被 cap 到 3: {len(versions)}"
    assert [v["version"] for v in versions] == [2, 3, 4], "保留最近 3 条快照"


def test_history_cap_clamp_to_1(monkeypatch, tmp_path):
    """cap=0 → clamp 到 [1,500] 下界 1。"""
    monkeypatch.setenv("FLIPPED_WORKER_RULES_HISTORY_CAP", "0")
    store = WorkerRuleStore(tmp_path / "rules.json")
    store.add("规则A")
    store.add("规则B")
    versions = store.versions()
    assert len(versions) == 1
    assert versions[0]["version"] == 2


def test_history_cap_invalid_falls_back_20(monkeypatch, tmp_path):
    """cap 非法值 → 回落默认 20。"""
    monkeypatch.setenv("FLIPPED_WORKER_RULES_HISTORY_CAP", "abc")
    store = WorkerRuleStore(tmp_path / "rules.json")
    for i in range(25):
        store.add(f"规则{i}")
    versions = store.versions()
    assert len(versions) == 20, f"非法 cap 必须回落 20: {len(versions)}"
    assert versions[-1]["version"] == 25


def test_history_cap_default_20(tmp_path):
    """零 env 时与旧常量行为一致（21 次变更 → 20 条）。"""
    store = WorkerRuleStore(tmp_path / "rules.json")
    for i in range(21):
        store.add(f"规则{i}")
    assert len(store.versions()) == 20
