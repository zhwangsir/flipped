#!/usr/bin/env python3
"""M99 Gold Memory 学习闭环实战验证脚本。

验证 Gold Memory 自学习闭环:
  任务A失败 → record_task_result 写回 SQLite → 相似任务B失败时
  analyze_failure_with_memory 查询命中A的经验(history_hint 非空)。

机制说明(源码核对,以源码为准):
  - record_task_result(task, state, result, db_path) 写回 gold_memory 表,
    存储 task_signature(关键词签名) + task_vector(embedding 向量) + summary/stop_reason。
  - analyze_failure_with_memory(stop_reason, summary, ..., task_description, db_path)
    内部先调 analyze_failure(regex 模式匹配,定 cause/confidence/related_rules),
    再调 query_similar_failures(task_description, db_path) 做语义检索:
      先用向量余弦相似度(≥0.5) Top-K,无向量/无命中时 fallback 到签名精确匹配。
    命中历史失败时把提示注入 RcaResult.history_hint(字段:历史条数+stop_reason统计+最近summary)。
  - analyze_failure_with_memory 本身不调 LLM(仅 regex + Gold Memory 查询);
    但 _embed 依赖 sentence-transformers 模型。本脚本 mock driving.gold_memory._embed,
    保证"实现登录页面"↔"创建登录页"跨描述语义匹配可确定性命中(不依赖模型安装,也不调真实模型)。
  - related_rules 来自 RCA regex 多规则匹配(非 Gold Memory);history_hint 才来自 Gold Memory。

闭环场景:
  步骤1 — 任务A("实现登录页面")失败写回,验证 gold_memory 有 1 条 success=0 记录
  步骤2 — 相似任务B("创建登录页")查询命中,验证 history_hint 非空含任务A信息、related_rules 非空
  步骤3 — 不相似任务("实现数据库迁移脚本")不命中,验证 history_hint 为空(负向验证)
  步骤4 — 再写回 2 条登录失败(不同 verify_cmd),验证共 3 条、查询仍命中 3 条历史

用法:
  cd /Users/wangzhenyu/Desktop/ALLProject/flipped && python scripts/verify_m99_gold_memory_loop.py
"""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent

# M164 · venv 自举：若 .venv 存在且当前不是 venv Python，自动重启自己。
# 否则用系统 Python 跑会因缺 langgraph 等依赖崩溃（scripts 设计为可 cron/直接跑，不能假设 venv 已激活）。
_VENV_PY = str(ROOT / ".venv" / "bin" / "python3")
if os.path.exists(_VENV_PY) and os.path.realpath(sys.executable) != os.path.realpath(_VENV_PY):
    os.execv(_VENV_PY, [_VENV_PY] + sys.argv)

# sys.path 注入 src/(对齐 tests/test_gold_memory.py 与 verify_m93_e2e.py 的做法)
sys.path.insert(0, str(ROOT / "src"))


# ============================================================
# mock embedding:让相似中文描述确定性命中
# ============================================================
# 每个中文字符映射到唯一维度;余弦相似度 = 共享字符数 / (sqrt(|A|) * sqrt(|B|))。
# "实现登录页面"(6字) 与 "创建登录页"(5字) 共享"登录页"3字 → sim≈0.55 ≥ 0.5 命中。
# "实现登录页面" 与 "实现数据库迁移脚本"(9字) 仅共享"实现"2字 → sim≈0.27 < 0.5 不命中。
# (注:实/现/创/建 是 _signature 的停用词,签名匹配无法跨描述命中,故必须走向量语义检索)
_EMBED_DIM = 0x9FFF - 0x4E00 + 1  # 20992,覆盖 CJK 统一汉字区,零碰撞


def _mock_embed(text: str) -> list[float]:
    """模拟 embedding:中文字符 bag-of-chars 映射到唯一维度。"""
    vec = [0.0] * _EMBED_DIM
    for ch in text:
        if "\u4e00" <= ch <= "\u9fff":
            vec[ord(ch) - 0x4E00] += 1.0
    return vec


# ============================================================
# 辅助构造(字段以源码为准:TaskResult.verified 非 success;design_style 在 FactoryState)
# ============================================================

def _make_task(desc: str, verify_cmd: list[str]):
    from driving.factory_loop import FactoryTask
    # id 用默认 uuid 工厂即可,UNIQUE 约束基于 (task_signature, design_style, verify_cmd)
    return FactoryTask(description=desc, verify_cmd=verify_cmd)


def _make_state(design_style: str = "modern"):
    from driving.factory_loop import FactoryState
    return FactoryState(
        factory_id="f-m99",
        product_goal="验证Gold Memory闭环",
        cwd="/tmp",
        roadmap=[],
        design_style=design_style,
    )


def _make_result(task, verified: bool, stop_reason: str, summary: str):
    from driving.factory_loop import TaskResult
    return TaskResult(
        task=task,
        verified=verified,
        stop_reason=stop_reason,
        summary=summary,
        iteration=1,
    )


def _count(db_path: str, where: str = "") -> int:
    with sqlite3.connect(db_path) as conn:
        cur = conn.execute(f"SELECT COUNT(*) FROM gold_memory {where}".strip())
        return cur.fetchone()[0]


def _reset_rca_counter() -> None:
    """重置 RCA 连续失败计数器,隔离各步骤(M91.2 全局计数器会跨调用累积)。"""
    try:
        from driving.rca import reset_failure_counter
        reset_failure_counter()
    except Exception:
        pass


# ============================================================
# 步骤1:任务A失败写回 Gold Memory
# ============================================================

def step1_writeback(db_path: str) -> dict:
    _reset_rca_counter()
    from driving.gold_memory import record_task_result
    task = _make_task("实现登录页面", ["pytest"])
    state = _make_state("modern")
    result = _make_result(
        task, verified=False, stop_reason="verify_failed",
        summary="RCA: syntax_error in login.py",
    )
    record_task_result(task, state, result, db_path=db_path)
    n_fail = _count(db_path, "WHERE success=0")
    n_total = _count(db_path)
    passed = (n_fail == 1 and n_total == 1)
    return {
        "step": 1,
        "name": "任务A失败写回 Gold Memory",
        "passed": passed,
        "detail": f"写回后 success=0 记录数={n_fail}(期望1), 总记录数={n_total}(期望1)",
    }


# ============================================================
# 步骤2:相似任务B查询命中任务A的经验
# ============================================================

def step2_similar_hit(db_path: str) -> dict:
    _reset_rca_counter()
    from driving.rca import analyze_failure_with_memory
    from driving.gold_memory import query_similar_failures
    # summary 含 SyntaxError + ImportError + verify_failed → 触发多规则,使 related_rules 非空
    rca = analyze_failure_with_memory(
        stop_reason="verify_failed",
        summary="SyntaxError: invalid syntax; ImportError: No module named 'auth'",
        task_description="创建登录页",
        db_path=db_path,
    )
    hint = rca.history_hint or ""
    cause_ok = rca.cause is not None
    conf_ok = isinstance(rca.confidence, float)
    # history_hint 应含任务A的 summary 信息(syntax_error)或描述关键词
    hint_ok = bool(hint) and (
        "syntax_error" in hint.lower() or "登录" in hint or "login" in hint.lower()
    )
    rules_ok = isinstance(rca.related_rules, list) and len(rca.related_rules) >= 1
    # 直接调查询函数复核命中条数
    failures = query_similar_failures("创建登录页", db_path=db_path, limit=5)
    hit_count = len(failures)
    passed = cause_ok and conf_ok and hint_ok and rules_ok and hit_count >= 1
    return {
        "step": 2,
        "name": "相似任务B查询命中历史经验",
        "passed": passed,
        "detail": (
            f"cause={rca.cause.value if cause_ok else 'N/A'}, "
            f"confidence={rca.confidence:.2f}, "
            f"history_hint非空且含任务A信息={hint_ok}, "
            f"related_rules={rca.related_rules}(非空={rules_ok}), "
            f"query_similar_failures命中={hit_count}条, "
            f"hint片段={hint[:80]!r}"
        ),
    }


# ============================================================
# 步骤3:不相似任务不命中(负向验证)
# ============================================================

def step3_dissimilar_miss(db_path: str) -> dict:
    _reset_rca_counter()
    from driving.rca import analyze_failure_with_memory
    from driving.gold_memory import query_similar_failures
    rca = analyze_failure_with_memory(
        stop_reason="verify_failed",
        summary="SyntaxError: invalid syntax",
        task_description="实现数据库迁移脚本",
        db_path=db_path,
    )
    hint = rca.history_hint or ""
    hint_clean = (not hint) or (
        "登录" not in hint
        and "syntax_error" not in hint.lower()
        and "login" not in hint.lower()
    )
    # 直接调查询函数复核:数据库任务不应命中登录历史
    failures = query_similar_failures("实现数据库迁移脚本", db_path=db_path, limit=5)
    miss_count = len(failures)
    passed = hint_clean and miss_count == 0
    return {
        "step": 3,
        "name": "不相似任务不命中(负向验证)",
        "passed": passed,
        "detail": (
            f"history_hint={hint!r}"
            f"({'空或不含登录关键词' if hint_clean else '误命中登录经验'}), "
            f"query_similar_failures命中={miss_count}条(期望0)"
        ),
    }


# ============================================================
# 步骤4:多次写回后统计 + 再次查询命中
# ============================================================

def step4_multi_writeback(db_path: str) -> dict:
    _reset_rca_counter()
    from driving.gold_memory import record_task_result, stats, query_similar_failures
    from driving.rca import analyze_failure_with_memory
    # 再写回 2 条登录相关失败(不同 verify_cmd → UNIQUE 约束允许新增行)
    for cmd in [["python -m pytest"], ["npm test"]]:
        task = _make_task("实现登录页面", cmd)
        state = _make_state("modern")
        result = _make_result(
            task, verified=False, stop_reason="verify_failed",
            summary="RCA: syntax_error in login.py",
        )
        record_task_result(task, state, result, db_path=db_path)
    n_total = _count(db_path)
    n_fail = _count(db_path, "WHERE success=0")
    s = stats(db_path)
    # 查询应命中 3 条历史失败
    failures = query_similar_failures("创建登录页", db_path=db_path, limit=5)
    hit_count = len(failures)
    rca = analyze_failure_with_memory(
        stop_reason="verify_failed",
        summary="SyntaxError: invalid syntax",
        task_description="创建登录页",
        db_path=db_path,
    )
    hint = rca.history_hint or ""
    count_ok = (n_total == 3 and n_fail == 3)
    stats_ok = (s["total_entries"] == 3 and s["failed"] == 3)
    hint_ok = bool(hint) and hit_count >= 3
    passed = count_ok and stats_ok and hint_ok
    return {
        "step": 4,
        "name": "多次写回后统计与查询",
        "passed": passed,
        "detail": (
            f"总记录数={n_total}(期望3), failed={n_fail}(期望3), "
            f"stats={s}, "
            f"query_similar_failures命中={hit_count}条(期望≥3), "
            f"history_hint非空={bool(hint)}, hint片段={hint[:80]!r}"
        ),
    }


# ============================================================
# 主入口
# ============================================================

def main() -> int:
    # 用临时 DB,不污染真实 Gold Memory(data/gold_memory.db)
    tmpdir = tempfile.mkdtemp(prefix="m99_gold_")
    db_path = os.path.join(tmpdir, "gold_memory.db")
    print("M99 Gold Memory 学习闭环验证")
    print(f"临时 DB: {db_path}")
    print("=" * 64)

    # 全程 mock driving.gold_memory._embed,保证语义检索确定性命中
    # (record_task_result 写入时 _embed,query_similar_failures 查询时 _embed,均走 mock)
    with patch("driving.gold_memory._embed", _mock_embed):
        results = []
        for fn in (step1_writeback, step2_similar_hit,
                   step3_dissimilar_miss, step4_multi_writeback):
            try:
                r = fn(db_path)
            except Exception as e:  # noqa: BLE001
                r = {
                    "step": 0,
                    "name": getattr(fn, "__doc__", fn.__name__).strip().splitlines()[0],
                    "passed": False,
                    "detail": f"异常: {type(e).__name__}: {e}",
                }
            results.append(r)
            mark = "✅ PASS" if r["passed"] else "❌ FAIL"
            print(f"{mark} 步骤{r['step']}: {r['name']}")
            print(f"        {r['detail']}")

    all_passed = all(r["passed"] for r in results)
    print("=" * 64)
    print(f"汇总: {'全部通过 ✅' if all_passed else '存在失败 ❌'}")
    print("JSON 结果:")
    print(json.dumps(results, ensure_ascii=False, indent=2))

    # 清理临时目录
    shutil.rmtree(tmpdir, ignore_errors=True)
    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
