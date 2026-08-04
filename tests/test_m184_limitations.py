"""M184 · known_limitations 系统性分析与消化 — scripts/limitations_report.py 测试（TDD）。

覆盖 CLI 五个子命令（import main(argv) 形式驱动，非 subprocess）：

1.  harvest 新建：条目数 / id 格式（L-{milestone}-{序号}）/ 默认人工字段
2.  harvest 打印摘要：harvested N limitations (A added, K stale)
3.  harvest 里程碑按 M 数字升序（与 STATE.json 字典序无关）
4.  harvest 幂等：二次跑无重复、0 added、updated_at 变化、条目稳定
5.  harvest 保留人工字段：手改 category/status/priority 等后重跑不丢
6.  harvest 新增合并：STATE 加一条 → added==1，新条目给默认值
7.  harvest 源移除：STATE 删一条 → 该条 wontfix + 注记「源已移除」（不重复追加）
8.  classify 六类关键词各命中一例 + 建议 priority/difficulty
9.  classify 未命中保持「未分类」
10. classify 不覆盖人工 priority/difficulty（仅默认值才覆盖）
11. classify 跳过已有 category 的条目
12. check 齐全 → exit 0 + 打印计数
13. check 缺失 → exit 1 + 打印缺失 id
14. check registry 文件不存在 → exit 1（load 不炸）
15. set-status 往返 + --note 落盘 + 打印「{id}: {old} → {new}」
16. set-status 未知 id → exit 1
17. report 五节标题齐 / 含全部 id / 统计数正确 / （待评估）占位
18. report 矩阵含 id / 路线图已消化节 / 候选池排除 resolved
19. 原子写：tmp + os.replace（mock 断言调用参数）
20. 坏 registry 文件 load 不炸（视为空注册表）
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

# 把 scripts/ 加入 sys.path 以便 import limitations_report 模块
_SCRIPTS_DIR = str(Path(__file__).resolve().parent.parent / "scripts")
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

import limitations_report  # noqa: E402


# --------------------------------------------------------------------
# 夹具：迷你 STATE.json（2 里程碑各 2 条，文本命中 classify 规则表）
# --------------------------------------------------------------------
MINI_MILESTONES = {
    "M171": {
        "title": "迷你里程碑一",
        "known_limitations": [
            "超大 repo 有一次性列举开销",  # → 性能 P2 中
            "图像附件未做，列后续候选",  # → 功能缺口 P1 中
        ],
    },
    "M172": {
        "title": "迷你里程碑二",
        "known_limitations": [
            "token 单活制过期即失效",  # → 安全 P0 中
            "黑盒不覆盖真 LLM 路径（证据在单测 mock 层）",  # → 测试覆盖 P2 低
        ],
    },
}


def _write_state(tmp_path: Path, milestones: dict) -> Path:
    p = tmp_path / "STATE.json"
    p.write_text(
        json.dumps({"milestones": milestones}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return p


def _mini_state(tmp_path: Path) -> Path:
    return _write_state(tmp_path, MINI_MILESTONES)


def _registry_path(tmp_path: Path) -> Path:
    return tmp_path / "data" / "limitations_registry.json"


def _load_registry(tmp_path: Path) -> dict:
    return json.loads(_registry_path(tmp_path).read_text(encoding="utf-8"))


def _harvest(tmp_path: Path) -> int:
    return limitations_report.main(
        [
            "harvest",
            "--state",
            str(_mini_state(tmp_path)),
            "--registry",
            str(_registry_path(tmp_path)),
        ]
    )


def _classify(tmp_path: Path) -> int:
    return limitations_report.main(
        ["classify", "--registry", str(_registry_path(tmp_path))]
    )


# --------------------------------------------------------------------
# 1. harvest 新建：条目数 / id 格式 / 默认字段
# --------------------------------------------------------------------
def test_harvest_creates_entries_with_ids_and_defaults(tmp_path, capsys):
    rc = _harvest(tmp_path)
    assert rc == 0
    reg = _load_registry(tmp_path)
    assert reg["version"] == 1
    assert reg["updated_at"]  # 非空 iso8601
    lims = reg["limitations"]
    assert len(lims) == 4
    assert [l["id"] for l in lims] == ["L-M171-1", "L-M171-2", "L-M172-1", "L-M172-2"]
    first = lims[0]
    assert first["milestone"] == "M171"
    assert first["text"] == "超大 repo 有一次性列举开销"
    # 默认人工字段
    assert first["category"] == "未分类"
    assert first["impact"] == ""
    assert first["priority"] == "P2"
    assert first["difficulty"] == "中"
    assert first["status"] == "open"
    assert first["resolution_note"] == ""
    assert first["target"] == ""


# --------------------------------------------------------------------
# 2. harvest 打印摘要
# --------------------------------------------------------------------
def test_harvest_prints_summary(tmp_path, capsys):
    _harvest(tmp_path)
    out = capsys.readouterr().out
    assert "harvested 4 limitations (4 added, 0 stale)" in out


# --------------------------------------------------------------------
# 3. harvest 里程碑按 M 数字升序（与字典序无关）
# --------------------------------------------------------------------
def test_harvest_orders_milestones_by_number(tmp_path, capsys):
    # 故意把 M172 放前面、M171 放后面
    milestones = {
        "M172": MINI_MILESTONES["M172"],
        "M171": MINI_MILESTONES["M171"],
    }
    state = _write_state(tmp_path, milestones)
    rc = limitations_report.main(
        ["harvest", "--state", str(state), "--registry", str(_registry_path(tmp_path))]
    )
    assert rc == 0
    reg = _load_registry(tmp_path)
    assert [l["milestone"] for l in reg["limitations"]] == ["M171", "M171", "M172", "M172"]


# --------------------------------------------------------------------
# 4. harvest 幂等：二次跑无重复、updated_at 变化、条目稳定
# --------------------------------------------------------------------
def test_harvest_idempotent_second_run(tmp_path, capsys):
    _harvest(tmp_path)
    first = _load_registry(tmp_path)
    rc = _harvest(tmp_path)
    assert rc == 0
    out = capsys.readouterr().out
    assert "harvested 4 limitations (0 added, 0 stale)" in out
    second = _load_registry(tmp_path)
    assert len(second["limitations"]) == 4  # 无重复
    assert second["limitations"] == first["limitations"]  # 条目稳定
    assert second["updated_at"] != first["updated_at"]  # 时间戳刷新


# --------------------------------------------------------------------
# 5. harvest 保留人工字段
# --------------------------------------------------------------------
def test_harvest_preserves_manual_fields(tmp_path, capsys):
    _harvest(tmp_path)
    reg = _load_registry(tmp_path)
    entry = reg["limitations"][0]
    assert entry["id"] == "L-M171-1"
    entry["category"] = "安全"
    entry["impact"] = "人工评估的影响"
    entry["priority"] = "P0"
    entry["difficulty"] = "高"
    entry["status"] = "in_progress"
    entry["resolution_note"] = "处理中"
    entry["target"] = "M185"
    _registry_path(tmp_path).write_text(
        json.dumps(reg, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    rc = _harvest(tmp_path)
    assert rc == 0
    reg2 = _load_registry(tmp_path)
    e2 = reg2["limitations"][0]
    assert e2["category"] == "安全"
    assert e2["impact"] == "人工评估的影响"
    assert e2["priority"] == "P0"
    assert e2["difficulty"] == "高"
    assert e2["status"] == "in_progress"
    assert e2["resolution_note"] == "处理中"
    assert e2["target"] == "M185"


# --------------------------------------------------------------------
# 6. harvest 新增合并：STATE 加一条 → added==1
# --------------------------------------------------------------------
def test_harvest_merges_new_state_entry(tmp_path, capsys):
    _harvest(tmp_path)
    milestones = json.loads(json.dumps(MINI_MILESTONES))  # 深拷贝
    milestones["M171"]["known_limitations"].append("重启后状态残留未清理")
    state = _write_state(tmp_path, milestones)
    rc = limitations_report.main(
        ["harvest", "--state", str(state), "--registry", str(_registry_path(tmp_path))]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "harvested 5 limitations (1 added, 0 stale)" in out
    reg = _load_registry(tmp_path)
    new_entry = reg["limitations"][2]
    assert new_entry["id"] == "L-M171-3"
    assert new_entry["text"] == "重启后状态残留未清理"
    assert new_entry["status"] == "open"
    assert new_entry["category"] == "未分类"


# --------------------------------------------------------------------
# 7. harvest 源移除：wontfix + 注记「源已移除」（不重复追加）
# --------------------------------------------------------------------
def test_harvest_marks_removed_source_wontfix(tmp_path, capsys):
    _harvest(tmp_path)
    milestones = json.loads(json.dumps(MINI_MILESTONES))
    milestones["M171"]["known_limitations"].pop()  # 删掉「图像附件未做，列后续候选」
    state = _write_state(tmp_path, milestones)
    rc = limitations_report.main(
        ["harvest", "--state", str(state), "--registry", str(_registry_path(tmp_path))]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "harvested 4 limitations (0 added, 1 stale)" in out
    reg = _load_registry(tmp_path)
    stale = [l for l in reg["limitations"] if l["id"] == "L-M171-2"]
    assert len(stale) == 1
    assert stale[0]["status"] == "wontfix"
    assert "源已移除" in stale[0]["resolution_note"]
    # 再跑一次：注记不重复追加
    limitations_report.main(
        ["harvest", "--state", str(state), "--registry", str(_registry_path(tmp_path))]
    )
    reg2 = _load_registry(tmp_path)
    stale2 = [l for l in reg2["limitations"] if l["id"] == "L-M171-2"][0]
    assert stale2["resolution_note"].count("源已移除") == 1


# --------------------------------------------------------------------
# 8. classify 六类关键词各命中一例 + 建议 priority/difficulty
# --------------------------------------------------------------------
def test_classify_fills_six_categories(tmp_path, capsys):
    milestones = {
        "M200": {
            "known_limitations": [
                "token 过期不刷新",  # 安全 P0 中
                "图像附件未做",  # 功能缺口 P1 中
                "超大 repo 列举开销",  # 性能 P2 中
                "黑盒不覆盖真 LLM 路径",  # 测试覆盖 P2 低
                "重启后状态残留",  # 数据一致性 P1 中
                "语义=既定取舍，向后兼容",  # 架构取舍 P2 低
            ]
        }
    }
    state = _write_state(tmp_path, milestones)
    limitations_report.main(
        ["harvest", "--state", str(state), "--registry", str(_registry_path(tmp_path))]
    )
    rc = _classify(tmp_path)
    assert rc == 0
    out = capsys.readouterr().out
    assert "classified 6 entries" in out
    reg = _load_registry(tmp_path)
    got = [(l["category"], l["priority"], l["difficulty"]) for l in reg["limitations"]]
    assert got == [
        ("安全", "P0", "中"),
        ("功能缺口", "P1", "中"),
        ("性能", "P2", "中"),
        ("测试覆盖", "P2", "低"),
        ("数据一致性", "P1", "中"),
        ("架构取舍", "P2", "低"),
    ]


# --------------------------------------------------------------------
# 9. classify 未命中保持「未分类」
# --------------------------------------------------------------------
def test_classify_keeps_unmatched_uncategorized(tmp_path, capsys):
    milestones = {"M200": {"known_limitations": ["上限 8 条、单文件 32KB"]}}
    state = _write_state(tmp_path, milestones)
    limitations_report.main(
        ["harvest", "--state", str(state), "--registry", str(_registry_path(tmp_path))]
    )
    rc = _classify(tmp_path)
    assert rc == 0
    out = capsys.readouterr().out
    assert "classified 0 entries" in out
    reg = _load_registry(tmp_path)
    assert reg["limitations"][0]["category"] == "未分类"


# --------------------------------------------------------------------
# 10. classify 不覆盖人工 priority/difficulty（仅默认值才覆盖）
# --------------------------------------------------------------------
def test_classify_respects_manual_priority_difficulty(tmp_path, capsys):
    _harvest(tmp_path)
    reg = _load_registry(tmp_path)
    entry = reg["limitations"][0]  # 「超大 repo 有一次性列举开销」→ 性能建议 P2/中
    entry["priority"] = "P0"  # 人工调高
    entry["difficulty"] = "高"
    _registry_path(tmp_path).write_text(
        json.dumps(reg, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    rc = _classify(tmp_path)
    assert rc == 0
    reg2 = _load_registry(tmp_path)
    e = reg2["limitations"][0]
    assert e["category"] == "性能"  # category 照填
    assert e["priority"] == "P0"  # 人工值不覆盖
    assert e["difficulty"] == "高"


# --------------------------------------------------------------------
# 11. classify 跳过已有 category 的条目
# --------------------------------------------------------------------
def test_classify_skips_already_categorized(tmp_path, capsys):
    _harvest(tmp_path)
    reg = _load_registry(tmp_path)
    reg["limitations"][0]["category"] = "架构取舍"  # 人工已分类
    _registry_path(tmp_path).write_text(
        json.dumps(reg, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    rc = _classify(tmp_path)
    assert rc == 0
    out = capsys.readouterr().out
    assert "classified 3 entries" in out  # 只处理剩下 3 条
    reg2 = _load_registry(tmp_path)
    assert reg2["limitations"][0]["category"] == "架构取舍"  # 不被规则改写


# --------------------------------------------------------------------
# 12. check 齐全 → exit 0
# --------------------------------------------------------------------
def test_check_ok(tmp_path, capsys):
    state = _mini_state(tmp_path)
    _harvest(tmp_path)
    rc = limitations_report.main(
        ["check", "--state", str(state), "--registry", str(_registry_path(tmp_path))]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "check ok: 4 limitations registered" in out


# --------------------------------------------------------------------
# 13. check 缺失 → exit 1 + 打印缺失 id
# --------------------------------------------------------------------
def test_check_missing_returns_1_and_prints_id(tmp_path, capsys):
    _harvest(tmp_path)
    milestones = json.loads(json.dumps(MINI_MILESTONES))
    milestones["M171"]["known_limitations"].append("新出现未登记的限制")
    state = _write_state(tmp_path, milestones)
    rc = limitations_report.main(
        ["check", "--state", str(state), "--registry", str(_registry_path(tmp_path))]
    )
    assert rc == 1
    out = capsys.readouterr().out
    assert "L-M171-3" in out  # 缺失条目的预期 id


# --------------------------------------------------------------------
# 14. check registry 文件不存在 → exit 1（load 不炸）
# --------------------------------------------------------------------
def test_check_missing_registry_file_returns_1(tmp_path, capsys):
    state = _mini_state(tmp_path)
    rc = limitations_report.main(
        [
            "check",
            "--state",
            str(state),
            "--registry",
            str(tmp_path / "nonexistent.json"),
        ]
    )
    assert rc == 1


# --------------------------------------------------------------------
# 15. set-status 往返 + --note 落盘 + 打印
# --------------------------------------------------------------------
def test_set_status_roundtrip_with_note(tmp_path, capsys):
    _harvest(tmp_path)
    rc = limitations_report.main(
        [
            "set-status",
            "L-M171-1",
            "resolved",
            "--note",
            "已在 M999 消化",
            "--registry",
            str(_registry_path(tmp_path)),
        ]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "L-M171-1: open → resolved" in out
    reg = _load_registry(tmp_path)
    e = reg["limitations"][0]
    assert e["status"] == "resolved"
    assert e["resolution_note"] == "已在 M999 消化"
    # 往返回 open
    rc2 = limitations_report.main(
        ["set-status", "L-M171-1", "open", "--registry", str(_registry_path(tmp_path))]
    )
    assert rc2 == 0
    out2 = capsys.readouterr().out
    assert "L-M171-1: resolved → open" in out2
    reg2 = _load_registry(tmp_path)
    assert reg2["limitations"][0]["status"] == "open"
    assert reg2["limitations"][0]["resolution_note"] == "已在 M999 消化"  # 不带 --note 不清空


# --------------------------------------------------------------------
# 16. set-status 未知 id → exit 1
# --------------------------------------------------------------------
def test_set_status_unknown_id_returns_1(tmp_path, capsys):
    _harvest(tmp_path)
    rc = limitations_report.main(
        [
            "set-status",
            "L-M999-9",
            "resolved",
            "--registry",
            str(_registry_path(tmp_path)),
        ]
    )
    assert rc == 1
    err = capsys.readouterr().err
    assert "L-M999-9" in err


# --------------------------------------------------------------------
# 17. report 五节标题齐 / 含全部 id / 统计数正确 / （待评估）占位
# --------------------------------------------------------------------
def _build_rich_registry(tmp_path: Path) -> Path:
    """harvest + classify + 一条 resolved，返回 registry 路径。"""
    _harvest(tmp_path)
    _classify(tmp_path)
    limitations_report.main(
        [
            "set-status",
            "L-M171-2",
            "resolved",
            "--note",
            "已在 M999 消化",
            "--registry",
            str(_registry_path(tmp_path)),
        ]
    )
    return _registry_path(tmp_path)


def test_report_structure_and_stats(tmp_path, capsys):
    reg_path = _build_rich_registry(tmp_path)
    out_md = tmp_path / "reports" / "limitations_analysis_20260804.md"
    rc = limitations_report.main(
        ["report", "--registry", str(reg_path), "--out", str(out_md)]
    )
    assert rc == 0
    md = out_md.read_text(encoding="utf-8")
    # 标题（日期取自 out 文件名）
    assert md.startswith("# 已知限制系统性分析报告（2026-08-04）")
    # 五节标题齐
    assert "## 1. 总览" in md
    assert "## 2. 全量明细" in md
    assert "## 3. 优先级×难度矩阵" in md
    assert "## 4. 分阶段路线图" in md
    assert "## 5. 跟踪机制说明" in md
    # 统计数正确（4 条：性能 P2/功能缺口 P1/安全 P0/测试覆盖 P2；1 resolved + 3 open）
    assert "**总数：4**" in md
    assert "| 性能 | 1 |" in md
    assert "| 功能缺口 | 1 |" in md
    assert "| 安全 | 1 |" in md
    assert "| 测试覆盖 | 1 |" in md
    assert "| P0 | 1 |" in md
    assert "| P1 | 1 |" in md
    assert "| P2 | 2 |" in md
    assert "| open | 3 |" in md
    assert "| resolved | 1 |" in md
    # 明细含全部 id
    for lid in ("L-M171-1", "L-M171-2", "L-M172-1", "L-M172-2"):
        assert f"### {lid} · " in md
    # impact 空 → （待评估）
    assert "（待评估）" in md
    # resolved 条目有处置注记
    assert "处置：已在 M999 消化" in md
    # 跟踪机制说明含 registry 路径与 check 用法
    assert "limitations_registry.json" in md
    assert "check" in md


# --------------------------------------------------------------------
# 18. report 矩阵含 id / 路线图已消化节 / 候选池排除 resolved
# --------------------------------------------------------------------
def test_report_matrix_and_roadmap(tmp_path, capsys):
    reg_path = _build_rich_registry(tmp_path)
    out_md = tmp_path / "reports" / "limitations_analysis_20260804.md"
    limitations_report.main(["report", "--registry", str(reg_path), "--out", str(out_md)])
    md = out_md.read_text(encoding="utf-8")
    # 矩阵节：P0 行含 L-M172-1（安全 P0 中）
    matrix_sec = md.split("## 3. 优先级×难度矩阵")[1].split("## 4.")[0]
    p0_row = next(line for line in matrix_sec.splitlines() if line.startswith("| P0 "))
    assert "L-M172-1" in p0_row
    p2_row = next(line for line in matrix_sec.splitlines() if line.startswith("| P2 "))
    assert "L-M171-1" in p2_row  # 性能 P2 中
    assert "L-M172-2" in p2_row  # 测试覆盖 P2 低
    # 路线图：已消化节含 resolved 条目
    digested = md.split("### 已消化")[1].split("###")[0]
    assert "L-M171-2" in digested
    assert "已在 M999 消化" in digested
    # 当前迭代 P0 节
    p0_sec = md.split("### 当前迭代 P0")[1].split("###")[0]
    assert "L-M172-1" in p0_sec
    # 近期 P1 节：L-M171-2 已 resolved → 空节
    p1_sec = md.split("### 近期 P1")[1].split("###")[0]
    assert "L-M171-2" not in p1_sec
    # 候选池 P2/wontfix：含两条 P2 open，不含 resolved
    pool_sec = md.split("### 候选池 P2/wontfix")[1].split("## 5.")[0]
    assert "L-M171-1" in pool_sec
    assert "L-M172-2" in pool_sec
    assert "L-M171-2" not in pool_sec


# --------------------------------------------------------------------
# 19. 原子写：tmp + os.replace（mock 断言调用）
# --------------------------------------------------------------------
def test_save_uses_atomic_os_replace(tmp_path, capsys, monkeypatch):
    calls = []

    def _fake_replace(src, dst):
        calls.append((src, dst))
        # 模拟真实 replace：把 tmp 挪到目标
        Path(dst).write_text(Path(src).read_text(encoding="utf-8"), encoding="utf-8")
        os.unlink(src)

    monkeypatch.setattr(os, "replace", _fake_replace)
    rc = _harvest(tmp_path)
    assert rc == 0
    reg_path = str(_registry_path(tmp_path))
    assert calls == [(f"{reg_path}.tmp", reg_path)]  # 先写 tmp 再 replace
    assert not Path(f"{reg_path}.tmp").exists()  # tmp 不残留
    assert _load_registry(tmp_path)["limitations"]  # 内容已落盘


# --------------------------------------------------------------------
# 20. 坏 registry 文件 load 不炸（视为空注册表）
# --------------------------------------------------------------------
def test_corrupt_registry_treated_as_empty(tmp_path, capsys):
    reg_path = _registry_path(tmp_path)
    reg_path.parent.mkdir(parents=True, exist_ok=True)
    reg_path.write_text("{not valid json!!!", encoding="utf-8")
    rc = _harvest(tmp_path)
    assert rc == 0
    out = capsys.readouterr().out
    assert "harvested 4 limitations (4 added, 0 stale)" in out  # 全量重建
    assert len(_load_registry(tmp_path)["limitations"]) == 4
