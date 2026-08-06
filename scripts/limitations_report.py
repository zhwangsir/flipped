#!/usr/bin/env python3
"""M184 · known_limitations 系统性分析与消化（注册表 + 跟踪 + 报告 + CI 检查）。

把 STATE.json 各里程碑的 known_limitations 数组收敛成机器可读注册表
（data/limitations_registry.json），叠加分类/优先级/状态跟踪，并产出
markdown 系统性分析报告。纯 stdlib，argparse 子命令：

    harvest     STATE.json → registry（幂等合并，保留人工字段；源移除置 wontfix）
    classify    关键词规则表给「未分类」条目填 category + 建议 priority/difficulty
    check       STATE.json 与 registry 一致性检查（缺失 → exit 1，CI 钩子用）
    set-status  更新单条状态（open/in_progress/resolved/wontfix）+ 可选处置注记
    report      生成 markdown 分析报告（总览/明细/优先级×难度矩阵/路线图/机制说明）

退出码：0 成功；1 业务失败（check 缺失 / set-status 未知 id）；2 argparse 参数错误。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Sequence

DEFAULT_STATE_PATH = "STATE.json"
DEFAULT_REGISTRY_PATH = "data/limitations_registry.json"
DEFAULT_REPORT_DIR = "reports"

STATUSES = ("open", "in_progress", "resolved", "wontfix")
PRIORITIES = ("P0", "P1", "P2")
DIFFICULTIES = ("低", "中", "高")

# 新增条目的默认人工字段（harvest 对已有条目不覆盖这些字段）
FIELD_DEFAULTS = {
    "category": "未分类",
    "impact": "",
    "priority": "P2",
    "difficulty": "中",
    "status": "open",
    "resolution_note": "",
    "target": "",
}

# classify 关键词规则表：(category, keywords, 建议 priority, 建议 difficulty)
# 按序首个命中即停；priority/difficulty 仅当条目仍为默认值时才覆盖。
CLASSIFY_RULES = [
    ("安全", ["token", "加密", "密钥", "签名", "验证", "xss", "注入", "穿越"], "P0", "中"),
    ("功能缺口", ["未做", "未覆盖", "候选", "缺口", "不支持", "不可逆"], "P1", "中"),
    ("性能", ["性能", "开销", "超时", "慢", "内存", "超大"], "P2", "中"),
    ("测试覆盖", ["黑盒不覆盖", "单测", "mock", "不碰真实", "flaky"], "P2", "低"),
    ("数据一致性", ["持久化", "恢复", "残留", "污染", "重启"], "P1", "中"),
    ("架构取舍", ["取舍", "不动", "兼容", "向后", "语义=", "既定"], "P2", "低"),
]


# --------------------------------------------------------------------
# registry 读写（tmp + os.replace 原子写，坏文件回退空表不炸）
# --------------------------------------------------------------------
def _empty_registry() -> dict:
    return {"version": 1, "updated_at": "", "limitations": []}


def _load_registry(path: str) -> dict:
    """读 registry；文件缺失/坏 JSON/结构不符 → 回退空注册表（不炸）。"""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return _empty_registry()
    if not isinstance(data, dict) or not isinstance(data.get("limitations"), list):
        return _empty_registry()
    return data


def _save_registry(path: str, data: dict) -> None:
    """刷新 updated_at 并 tmp + os.replace 原子写（防并发/崩溃写坏）。"""
    data["updated_at"] = datetime.now().isoformat()
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    tmp = f"{path}.tmp"
    Path(tmp).write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    os.replace(tmp, path)


# --------------------------------------------------------------------
# STATE.json 遍历：里程碑按 M 数字升序，条目按数组出现序
# --------------------------------------------------------------------
def _milestone_sort_key(name: str) -> int:
    m = re.match(r"^M(\d+)", name)
    return int(m.group(1)) if m else 0


def _iter_state_limitations(state: dict):
    """产出 (milestone, 序号从1, text)，里程碑按 M 数字升序。"""
    milestones = state.get("milestones", {})
    for ms in sorted(milestones, key=_milestone_sort_key):
        entry = milestones[ms]
        if not isinstance(entry, dict):
            continue
        known = entry.get("known_limitations") or []
        for idx, text in enumerate(known, 1):
            yield ms, idx, text


# --------------------------------------------------------------------
# harvest：STATE.json → registry 幂等合并
# --------------------------------------------------------------------
def _cmd_harvest(args: argparse.Namespace) -> int:
    state = json.loads(Path(args.state).read_text(encoding="utf-8"))
    reg = _load_registry(args.registry)

    # 已有条目按 (milestone, text) 精确匹配入池（同 key 多条按序消费）
    pools: dict = {}
    for lim in reg["limitations"]:
        key = (lim.get("milestone"), lim.get("text"))
        pools.setdefault(key, []).append(lim)

    merged = []
    added = 0
    for ms, idx, text in _iter_state_limitations(state):
        pool = pools.get((ms, text))
        if pool:
            entry = pool.pop(0)  # 保留人工字段
            entry["id"] = f"L-{ms}-{idx}"
            entry["milestone"] = ms
            entry["text"] = text
        else:
            entry = {
                "id": f"L-{ms}-{idx}",
                "milestone": ms,
                "text": text,
                **FIELD_DEFAULTS,
            }
            added += 1
        merged.append(entry)

    # 源已移除：registry 有而 STATE 无 → 保留但置 wontfix + 注记
    stale = 0
    for pool in pools.values():
        for entry in pool:
            stale += 1
            entry["status"] = "wontfix"
            note = entry.get("resolution_note", "")
            if "源已移除" not in note:
                entry["resolution_note"] = f"{note}；源已移除" if note else "源已移除"
            merged.append(entry)

    reg["limitations"] = merged
    _save_registry(args.registry, reg)
    print(f"harvested {len(merged)} limitations ({added} added, {stale} stale)")
    return 0


# --------------------------------------------------------------------
# classify：关键词规则表填 category + 建议 priority/difficulty
# --------------------------------------------------------------------
def _classify_text(text: str):
    """按序首个命中即停；无命中返回 None。"""
    low = text.lower()
    for category, keywords, priority, difficulty in CLASSIFY_RULES:
        for kw in keywords:
            if kw.lower() in low:
                return category, priority, difficulty
    return None


def _cmd_classify(args: argparse.Namespace) -> int:
    reg = _load_registry(args.registry)
    classified = 0
    for lim in reg["limitations"]:
        if lim.get("category") != "未分类":
            continue
        hit = _classify_text(lim.get("text", ""))
        if hit is None:
            continue
        category, priority, difficulty = hit
        lim["category"] = category
        # 建议值仅当仍为默认值时才覆盖（不踩人工调过的字段）
        if lim.get("priority", "P2") == "P2":
            lim["priority"] = priority
        if lim.get("difficulty", "中") == "中":
            lim["difficulty"] = difficulty
        classified += 1
    _save_registry(args.registry, reg)
    print(f"classified {classified} entries")
    return 0


# --------------------------------------------------------------------
# check：STATE.json 现行条目必须全部登记在 registry（CI 钩子用）
# --------------------------------------------------------------------
def _cmd_check(args: argparse.Namespace) -> int:
    state = json.loads(Path(args.state).read_text(encoding="utf-8"))
    reg = _load_registry(args.registry)
    registered = {
        (lim.get("milestone"), lim.get("text")) for lim in reg["limitations"]
    }
    missing = []
    for ms, idx, text in _iter_state_limitations(state):
        if (ms, text) not in registered:
            missing.append((f"L-{ms}-{idx}", text))
    if missing:
        print("missing limitations in registry:")
        for lid, text in missing:
            print(f"  - {lid} {text[:60]}")
        return 1

    # M185.4 · registry 真实性校验（消化 L-M184-2）：存在性之外再验字段可信。
    violations: list[str] = []
    seen_ids: set[str] = set()
    for lim in reg["limitations"]:
        lid = str(lim.get("id", ""))
        # 1. id 格式 ^L-M{n}-{i}$ 且 id 里程碑段 == milestone 字段
        m = re.fullmatch(r"L-(M\d+)-(\d+)", lid)
        if not m:
            violations.append(f"{lid or '(empty)'}: id 格式非法（期望 L-M<n>-<i>）")
        else:
            if lid in seen_ids:
                violations.append(f"{lid}: id 重复")
            seen_ids.add(lid)
            if m.group(1) != str(lim.get("milestone", "")):
                violations.append(
                    f"{lid}: id 里程碑段({m.group(1)})与 milestone 字段"
                    f"({lim.get('milestone')})不符")
        # 2. 枚举字段合法
        status = lim.get("status")
        if status not in STATUSES:
            violations.append(f"{lid}: status 非法（{status}∉{STATUSES}）")
        priority = lim.get("priority")
        if priority not in PRIORITIES:
            violations.append(f"{lid}: priority 非法（{priority}∉{PRIORITIES}）")
        difficulty = lim.get("difficulty")
        if difficulty not in DIFFICULTIES:
            violations.append(
                f"{lid}: difficulty 非法（{difficulty}∉{DIFFICULTIES}）")
        # 3. 已处置条目必须有注记
        if status in ("resolved", "wontfix") and not str(
                lim.get("resolution_note", "")).strip():
            violations.append(f"{lid}: {status} 缺 resolution_note")
        # 4. M195.2 · target 存在性校验（消化 L-M185-3）：
        #    target 为 ^M\d+$ 格式时必须指向 STATE.json 真实存在的里程碑；
        #    「后续里程碑」等非 M 格式跳过（不约束自由文本）。
        target = str(lim.get("target") or "").strip()
        if re.fullmatch(r"M\d+", target):
            known_ms = set(state.get("milestones", {}).keys())
            if target not in known_ms:
                violations.append(
                    f"{lid}: target 指向不存在的里程碑（{target}）")
    if violations:
        print("registry violations:")
        for v in violations:
            print(f"  - {v}")
        return 1
    print(f"check ok: {len(reg['limitations'])} limitations registered")
    return 0


# --------------------------------------------------------------------
# set-status：更新单条状态（+可选处置注记）
# --------------------------------------------------------------------
def _cmd_set_status(args: argparse.Namespace) -> int:
    reg = _load_registry(args.registry)
    for lim in reg["limitations"]:
        if lim.get("id") == args.id:
            old = lim.get("status", "open")
            lim["status"] = args.status
            if args.note is not None:
                lim["resolution_note"] = args.note
            _save_registry(args.registry, reg)
            print(f"{args.id}: {old} → {args.status}")
            return 0
    print(f"error: limitation id not found: {args.id}", file=sys.stderr)
    return 1


# --------------------------------------------------------------------
# report：markdown 系统性分析报告（结构钉死五节）
# --------------------------------------------------------------------
def _report_date(out_path: str) -> str:
    """报告日期：优先取 out 文件名里的 YYYYMMDD，否则取今天。"""
    m = re.search(r"(\d{4})(\d{2})(\d{2})", os.path.basename(out_path))
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    return datetime.now().strftime("%Y-%m-%d")


def _truncate(text: str, limit: int = 60) -> str:
    return text[:limit] + "…" if len(text) > limit else text


def _render_report(reg: dict, registry_path: str, report_date: str) -> str:
    lims = reg["limitations"]
    lines = [f"# 已知限制系统性分析报告（{report_date}）", ""]

    # ---- 1. 总览 ----
    lines += ["## 1. 总览", "", f"**总数：{len(lims)}**", ""]
    cat_counts: dict = {}
    for lim in lims:
        cat = lim.get("category", "未分类")
        cat_counts[cat] = cat_counts.get(cat, 0) + 1
    lines += ["| 分类 | 数量 |", "| --- | --- |"]
    for cat, n in sorted(cat_counts.items(), key=lambda kv: (-kv[1], kv[0])):
        lines.append(f"| {cat} | {n} |")
    lines.append("")
    prio_counts = {p: 0 for p in PRIORITIES}
    for lim in lims:
        if lim.get("priority") in prio_counts:
            prio_counts[lim["priority"]] += 1
    lines += ["| 优先级 | 数量 |", "| --- | --- |"]
    for p in PRIORITIES:
        lines.append(f"| {p} | {prio_counts[p]} |")
    lines.append("")
    status_counts = {s: 0 for s in STATUSES}
    for lim in lims:
        if lim.get("status") in status_counts:
            status_counts[lim["status"]] += 1
    lines += ["| 状态 | 数量 |", "| --- | --- |"]
    for s in STATUSES:
        lines.append(f"| {s} | {status_counts[s]} |")
    lines.append("")

    # ---- 2. 全量明细 ----
    lines += ["## 2. 全量明细", ""]
    for lim in lims:
        lines.append(f"### {lim.get('id')} · {lim.get('milestone')}")
        lines.append("")
        lines.append("| 分类 | 优先级 | 难度 | 状态 | 目标 |")
        lines.append("| --- | --- | --- | --- | --- |")
        lines.append(
            "| {cat} | {prio} | {diff} | {status} | {target} |".format(
                cat=lim.get("category", "未分类"),
                prio=lim.get("priority", "P2"),
                diff=lim.get("difficulty", "中"),
                status=lim.get("status", "open"),
                target=lim.get("target") or "—",
            )
        )
        lines.append("")
        lines.append(f"> {lim.get('text', '')}")
        lines.append("")
        impact = lim.get("impact") or "（待评估）"
        lines.append(f"影响：{impact}")
        lines.append("")
        note = lim.get("resolution_note", "")
        if note:
            lines.append(f"处置：{note}")
            lines.append("")

    # ---- 3. 优先级×难度矩阵 ----
    lines += ["## 3. 优先级×难度矩阵", ""]
    lines.append("| 优先级 \\ 难度 | " + " | ".join(DIFFICULTIES) + " |")
    lines.append("| --- | --- | --- | --- |")
    for p in PRIORITIES:
        cells = []
        for d in DIFFICULTIES:
            ids = [
                lim["id"]
                for lim in lims
                if lim.get("priority") == p and lim.get("difficulty") == d
            ]
            cells.append(", ".join(ids) if ids else "—")
        lines.append(f"| {p} | " + " | ".join(cells) + " |")
    lines.append("")

    # ---- 4. 分阶段路线图 ----
    lines += ["## 4. 分阶段路线图", ""]
    resolved = [l for l in lims if l.get("status") == "resolved"]
    p0 = [
        l
        for l in lims
        if l.get("priority") == "P0" and l.get("status") not in ("resolved", "wontfix")
    ]
    p1 = [
        l
        for l in lims
        if l.get("priority") == "P1" and l.get("status") not in ("resolved", "wontfix")
    ]
    pool = [
        l
        for l in lims
        if (l.get("priority") == "P2" and l.get("status") != "resolved")
        or l.get("status") == "wontfix"
    ]

    def _roadmap_items(entries) -> list:
        items = []
        for lim in entries:
            item = f"- {lim['id']} {_truncate(lim.get('text', ''))}"
            if lim.get("target"):
                item += f" → {lim['target']}"
            items.append(item)
        return items or ["（无）"]

    lines.append("### 已消化")
    lines.append("")
    if resolved:
        for lim in resolved:
            note = lim.get("resolution_note") or _truncate(lim.get("text", ""))
            lines.append(f"- {lim['id']} {note}")
    else:
        lines.append("（无）")
    lines.append("")
    lines.append("### 当前迭代 P0")
    lines.append("")
    lines += _roadmap_items(p0)
    lines.append("")
    lines.append("### 近期 P1")
    lines.append("")
    lines += _roadmap_items(p1)
    lines.append("")
    lines.append("### 候选池 P2/wontfix")
    lines.append("")
    lines += _roadmap_items(pool)
    lines.append("")

    # ---- 5. 跟踪机制说明 ----
    lines += [
        "## 5. 跟踪机制说明",
        "",
        f"- 注册表文件：`{registry_path}`（version=1，tmp+os.replace 原子写）",
        "- 新增/同步：`python scripts/limitations_report.py harvest`"
        "（STATE.json → registry 幂等合并，保留人工字段，源移除置 wontfix）",
        "- 一致性检查：`python scripts/limitations_report.py check`"
        "（STATE.json 有而 registry 无 → exit 1 打印缺失清单）",
        "- 状态流转：`python scripts/limitations_report.py set-status <id>"
        " <open|in_progress|resolved|wontfix> [--note 处置注记]`",
        "- CI 钩子建议：在 `scripts/quality_gate.sh` 或 CI 流水线中加入"
        " `python scripts/limitations_report.py check`，"
        "防止新里程碑的 known_limitations 漏登记",
        "",
    ]
    return "\n".join(lines)


def _update_report_index(out: str, report_date: str, total: int) -> None:
    """M195.2 · 报告索引（消化 L-M184-4）：reports/index.md 按文件名去重维护。

    每行：- [文件名](文件名) — YYYY-MM-DD · N 条。同文件重复生成只更新不追加。
    索引文件与报告同目录（out 的 parent）。
    """
    index_path = Path(out).parent / "index.md"
    name = os.path.basename(out)
    entry = f"- [{name}]({name}) — {report_date} · {total} 条"
    lines: list[str] = []
    if index_path.exists():
        lines = index_path.read_text(encoding="utf-8").splitlines()
    header = "# 已知限制分析报告索引"
    if not lines or lines[0].strip() != header:
        lines = [header, ""] + [l for l in lines if l.strip().startswith("- ")]
    kept = [l for l in lines if not l.startswith(f"- [{name}](")]
    kept.append(entry)
    # 保持头部在前，条目按文件名排序（文件名含日期 → 时间序）
    head = [l for l in kept if not l.startswith("- [")]
    items = sorted(l for l in kept if l.startswith("- ["))
    index_path.write_text("\n".join(head + items) + "\n", encoding="utf-8")


def _cmd_report(args: argparse.Namespace) -> int:
    out = args.out or os.path.join(
        DEFAULT_REPORT_DIR,
        f"limitations_analysis_{datetime.now():%Y%m%d}.md",
    )
    reg = _load_registry(args.registry)
    md = _render_report(reg, args.registry, _report_date(out))
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_text(md, encoding="utf-8")
    _update_report_index(out, _report_date(out), len(reg["limitations"]))
    print(f"report written: {out} ({len(reg['limitations'])} limitations)")
    return 0


# --------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    """构造 CLI 参数解析器（五个子命令）。"""
    p = argparse.ArgumentParser(
        prog="limitations_report.py",
        description="known_limitations 系统性分析与消化（M184：注册表/分类/检查/状态/报告）",
    )
    sub = p.add_subparsers(dest="command", required=True)

    ph = sub.add_parser("harvest", help="STATE.json → registry 幂等合并")
    ph.add_argument("--state", default=DEFAULT_STATE_PATH, help="STATE.json 路径")
    ph.add_argument(
        "--registry", default=DEFAULT_REGISTRY_PATH, help="registry JSON 路径"
    )
    ph.set_defaults(func=_cmd_harvest)

    pc = sub.add_parser("classify", help="关键词规则表填充分类与建议优先级/难度")
    pc.add_argument(
        "--registry", default=DEFAULT_REGISTRY_PATH, help="registry JSON 路径"
    )
    pc.set_defaults(func=_cmd_classify)

    pchk = sub.add_parser("check", help="STATE.json 与 registry 一致性检查（CI 钩子）")
    pchk.add_argument("--state", default=DEFAULT_STATE_PATH, help="STATE.json 路径")
    pchk.add_argument(
        "--registry", default=DEFAULT_REGISTRY_PATH, help="registry JSON 路径"
    )
    pchk.set_defaults(func=_cmd_check)

    ps = sub.add_parser("set-status", help="更新单条限制的状态")
    ps.add_argument("id", help="限制条目 id（如 L-M171-1）")
    ps.add_argument("status", choices=STATUSES, help="目标状态")
    ps.add_argument("--note", default=None, help="处置注记（写入 resolution_note）")
    ps.add_argument(
        "--registry", default=DEFAULT_REGISTRY_PATH, help="registry JSON 路径"
    )
    ps.set_defaults(func=_cmd_set_status)

    pr = sub.add_parser("report", help="生成 markdown 系统性分析报告")
    pr.add_argument(
        "--registry", default=DEFAULT_REGISTRY_PATH, help="registry JSON 路径"
    )
    pr.add_argument(
        "--out",
        default=None,
        help="报告输出路径（默认 reports/limitations_analysis_<YYYYMMDD>.md）",
    )
    pr.set_defaults(func=_cmd_report)

    return p


def main(argv: Sequence[str] | None = None) -> int:
    """CLI 入口。返回退出码（0 成功 / 1 业务失败）。"""
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
