"""M185 · P0 限制消化 — 单测（TDD）。

覆盖四条 P0 限制的纯逻辑层：

1.  build scopes=("all",) 只注入 all 规则（chat 通路语义）
2.  build scopes=("worker",) 只注入 worker 规则
3.  build 缺省 scopes 不变（("worker","all")，M183 回归）
4.  build scopes 空集命中 → ("", [])
5.  WORKER_RULES_CHAT_HEADER 常量存在且非空
6.  snapshot 含 semantics 固定文本（STATS_SEMANTICS）
7.  snapshot entry 派生 success_rate（success/(success+failure)）
8.  snapshot 零 outcome → success_rate is None
9.  落盘文件不含派生字段（success_rate/semantics 不落盘）
10. stats 加载旧格式文件（无派生字段）不炸且 snapshot 正常
11. check 增强：合法 registry → exit 0
12. check 增强：非法 status → exit 1 且打印违规 id
13. check 增强：非法 priority → exit 1
14. check 增强：非法 difficulty → exit 1
15. check 增强：resolved 无 resolution_note → exit 1
16. check 增强：wontfix 无 resolution_note → exit 1
17. check 增强：id 格式坏（非 L-M{n}-{i}）→ exit 1
18. check 增强：id milestone 段与条目 milestone 不符 → exit 1
19. check 增强：重复 id → exit 1
20. check 增强：open 无 resolution_note 不违规（合法常态）
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from driving.worker_rules import (
    STATS_SEMANTICS,
    WORKER_RULES_CHAT_HEADER,
    WorkerRule,
    WorkerRuleStats,
    build_worker_rules_text,
)

# scripts/ 加入 sys.path 以便 import limitations_report（同 test_m184 范式）
_SCRIPTS_DIR = str(Path(__file__).resolve().parent.parent / "scripts")
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

import limitations_report  # noqa: E402


def _rule(rid: str, text: str, *, scope: str = "worker", priority: int = 50,
          enabled: bool = True) -> WorkerRule:
    return WorkerRule(id=rid, text=text, scope=scope, source="manual",
                      enabled=enabled, priority=priority, created_at=1.0)


# --------------------------------------------------------------------
# 1-5. build_worker_rules_text scopes 参数化（M185.1）
# --------------------------------------------------------------------
def test_build_scopes_all_only_injects_all_rules():
    rules = [
        _rule("wr-a", "全局规则甲", scope="all", priority=10),
        _rule("wr-b", "worker 专属乙", scope="worker", priority=90),
    ]
    text, applied = build_worker_rules_text(rules, scopes=("all",))
    assert "全局规则甲" in text
    assert "worker 专属乙" not in text
    assert applied == ["wr-a"]


def test_build_scopes_worker_only_injects_worker_rules():
    rules = [
        _rule("wr-a", "全局规则甲", scope="all", priority=10),
        _rule("wr-b", "worker 专属乙", scope="worker", priority=90),
    ]
    text, applied = build_worker_rules_text(rules, scopes=("worker",))
    assert "worker 专属乙" in text
    assert "全局规则甲" not in text
    assert applied == ["wr-b"]


def test_build_default_scopes_unchanged_m183_regression():
    rules = [
        _rule("wr-a", "全局规则甲", scope="all", priority=10),
        _rule("wr-b", "worker 专属乙", scope="worker", priority=90),
    ]
    text, applied = build_worker_rules_text(rules)
    assert "全局规则甲" in text and "worker 专属乙" in text
    # priority desc：乙(90) 在 甲(10) 前
    assert text.index("worker 专属乙") < text.index("全局规则甲")
    assert applied == ["wr-b", "wr-a"]


def test_build_scopes_no_match_returns_empty():
    rules = [_rule("wr-b", "worker 专属乙", scope="worker")]
    text, applied = build_worker_rules_text(rules, scopes=("all",))
    assert text == "" and applied == []


def test_chat_header_constant_nonempty():
    assert isinstance(WORKER_RULES_CHAT_HEADER, str) and WORKER_RULES_CHAT_HEADER.strip()


# --------------------------------------------------------------------
# 6-10. Stats snapshot 语义显式化 + success_rate（M185.2）
# --------------------------------------------------------------------
def _stats(tmp_path: Path) -> WorkerRuleStats:
    return WorkerRuleStats(tmp_path / "stats.json")


def test_snapshot_contains_semantics_text(tmp_path):
    s = _stats(tmp_path)
    s.record_applied(["wr-a"])
    snap = s.snapshot()
    assert snap["semantics"] == STATS_SEMANTICS
    assert "applied" in snap["semantics"] and "success" in snap["semantics"]


def test_snapshot_success_rate_derived(tmp_path):
    s = _stats(tmp_path)
    s.record_applied(["wr-a", "wr-a", "wr-a", "wr-a"])
    s.record_outcome(["wr-a"], True)
    s.record_outcome(["wr-a"], True)
    s.record_outcome(["wr-a"], True)
    s.record_outcome(["wr-a"], False)
    snap = s.snapshot()
    entry = snap["stats"]["wr-a"]
    assert entry["applied"] == 4
    assert entry["success"] == 3 and entry["failure"] == 1
    assert entry["success_rate"] == pytest.approx(0.75)


def test_snapshot_zero_outcome_success_rate_none(tmp_path):
    s = _stats(tmp_path)
    s.record_applied(["wr-a"])
    snap = s.snapshot()
    assert snap["stats"]["wr-a"]["success_rate"] is None


def test_persisted_file_has_no_derived_fields(tmp_path):
    s = _stats(tmp_path)
    s.record_applied(["wr-a"])
    s.record_outcome(["wr-a"], True)
    raw = json.loads((tmp_path / "stats.json").read_text(encoding="utf-8"))
    assert "semantics" not in raw
    assert "success_rate" not in raw["stats"]["wr-a"]
    # 落盘形状仍是 M183 三字段 + total_runs
    assert raw["stats"]["wr-a"] == {"applied": 1, "success": 1, "failure": 0}


def test_stats_loads_legacy_file_and_derives(tmp_path):
    (tmp_path / "stats.json").write_text(json.dumps({
        "stats": {"wr-a": {"applied": 2, "success": 1, "failure": 1}},
        "total_runs": 2,
    }), encoding="utf-8")
    snap = _stats(tmp_path).snapshot()
    assert snap["stats"]["wr-a"]["success_rate"] == pytest.approx(0.5)
    assert snap["semantics"] == STATS_SEMANTICS


# --------------------------------------------------------------------
# 11-20. check 增强 registry 真实性校验（M185.4）
# --------------------------------------------------------------------
_MINI_MILESTONES = {
    "M171": {"title": "迷你一", "known_limitations": ["限制甲", "限制乙"]},
}


def _write_state(tmp_path: Path, milestones: dict) -> Path:
    p = tmp_path / "STATE.json"
    p.write_text(json.dumps({"milestones": milestones}, ensure_ascii=False),
                 encoding="utf-8")
    return p


def _registry_path(tmp_path: Path) -> Path:
    return tmp_path / "data" / "limitations_registry.json"


def _write_registry(tmp_path: Path, limitations: list[dict]) -> Path:
    p = _registry_path(tmp_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"version": 1, "updated_at": "", "limitations": limitations},
                            ensure_ascii=False), encoding="utf-8")
    return p


def _valid_entry(lid: str = "L-M171-1", milestone: str = "M171", text: str = "限制甲",
                 **overrides) -> dict:
    entry = {
        "id": lid, "milestone": milestone, "text": text,
        "category": "功能缺口", "impact": "", "priority": "P1", "difficulty": "中",
        "status": "open", "resolution_note": "", "target": "",
    }
    entry.update(overrides)
    return entry


def _run_check(tmp_path: Path, capsys) -> tuple[int, str]:
    rc = limitations_report.main([
        "check", "--state", str(_write_state(tmp_path, _MINI_MILESTONES)),
        "--registry", str(_registry_path(tmp_path)),
    ])
    return rc, capsys.readouterr().out


def test_check_valid_registry_passes(tmp_path, capsys):
    _write_registry(tmp_path, [
        _valid_entry(),
        _valid_entry("L-M171-2", text="限制乙", status="resolved",
                     resolution_note="M185 消化"),
    ])
    rc, out = _run_check(tmp_path, capsys)
    assert rc == 0
    assert "check ok" in out


def test_check_bad_status_fails(tmp_path, capsys):
    _write_registry(tmp_path, [
        _valid_entry(status="doing"),
        _valid_entry("L-M171-2", text="限制乙"),
    ])
    rc, out = _run_check(tmp_path, capsys)
    assert rc == 1
    assert "L-M171-1" in out and "status" in out


def test_check_bad_priority_fails(tmp_path, capsys):
    _write_registry(tmp_path, [
        _valid_entry(priority="P9"),
        _valid_entry("L-M171-2", text="限制乙"),
    ])
    rc, out = _run_check(tmp_path, capsys)
    assert rc == 1 and "L-M171-1" in out and "priority" in out


def test_check_bad_difficulty_fails(tmp_path, capsys):
    _write_registry(tmp_path, [
        _valid_entry(difficulty="巨难"),
        _valid_entry("L-M171-2", text="限制乙"),
    ])
    rc, out = _run_check(tmp_path, capsys)
    assert rc == 1 and "L-M171-1" in out and "difficulty" in out


def test_check_resolved_without_note_fails(tmp_path, capsys):
    _write_registry(tmp_path, [
        _valid_entry(status="resolved", resolution_note=""),
        _valid_entry("L-M171-2", text="限制乙"),
    ])
    rc, out = _run_check(tmp_path, capsys)
    assert rc == 1 and "L-M171-1" in out and "resolution_note" in out


def test_check_wontfix_without_note_fails(tmp_path, capsys):
    _write_registry(tmp_path, [
        _valid_entry(status="wontfix", resolution_note=""),
        _valid_entry("L-M171-2", text="限制乙"),
    ])
    rc, out = _run_check(tmp_path, capsys)
    assert rc == 1 and "L-M171-1" in out


def test_check_bad_id_format_fails(tmp_path, capsys):
    _write_registry(tmp_path, [
        _valid_entry("M171-1"),
        _valid_entry("L-M171-2", text="限制乙"),
    ])
    rc, out = _run_check(tmp_path, capsys)
    assert rc == 1 and "id" in out


def test_check_id_milestone_mismatch_fails(tmp_path, capsys):
    _write_registry(tmp_path, [
        _valid_entry("L-M999-1", milestone="M171"),
        _valid_entry("L-M171-2", text="限制乙"),
    ])
    rc, out = _run_check(tmp_path, capsys)
    assert rc == 1 and "milestone" in out


def test_check_duplicate_id_fails(tmp_path, capsys):
    _write_registry(tmp_path, [
        _valid_entry(),
        _valid_entry(text="限制乙"),  # 同 id L-M171-1
    ])
    rc, out = _run_check(tmp_path, capsys)
    assert rc == 1 and "重复" in out


def test_check_open_without_note_is_valid(tmp_path, capsys):
    """open 无注记是常态（未处置），不得误报。"""
    _write_registry(tmp_path, [
        _valid_entry(status="open", resolution_note=""),
        _valid_entry("L-M171-2", text="限制乙", status="in_progress",
                     resolution_note=""),
    ])
    rc, out = _run_check(tmp_path, capsys)
    assert rc == 0
