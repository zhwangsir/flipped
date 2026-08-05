"""M187.1 · cron 表达式调度 TDD 测试（A 队后端）。

覆盖：
- validate_cron：合法子集（*、列表、范围、step、周日 0/7）与非法形态
  （字段数错、越界、倒序范围、step 0、字母、空串、*/*）
- cron_next：确定性用例（aware UTC 注入）——逐分钟/step/跨天/工作日/跨月/
  闰年 2/29 跳跃/永不触发 None/dom-dow OR 语义/周日 0=7 等价/naive-aware 对齐
- tasks.py 层：compute_next_run cron 分支（disabled → None；脏数据非法 cron →
  None 不炸）；add(cron=...) 落盘 reload 字段在
- main.py 端点层：kind=cron 合法 201 含 cron 字段；缺 cron/非法表达式/once 带
  cron 全 422；FLIPPED_TASKS=0 → 404

风格沿用 test_m178_tasks.py：同步测试 + TestClient + tmp 路径隔离注册表。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from api.cron import CronError, cron_next, validate_cron
from api.tasks import ScheduledTask, TaskRegistry, compute_next_run

UTC = timezone.utc
NOW = datetime(2026, 8, 5, 10, 30, 0, tzinfo=UTC)  # 2026-08-05 周三


# ====================================================================
# 1 · validate_cron：合法表达式
# ====================================================================

@pytest.mark.parametrize("expr", [
    "* * * * *",          # 每分钟
    "*/5 * * * *",        # step
    "0 9 * * 1-5",        # 工作日范围
    "0 0 1,15 * *",       # 列表
    "30 8-18/2 * * *",    # 范围带 step
    "0 0 * * 0",          # 周日 = 0
    "0 0 * * 7",          # 周日 = 7
    "5/10 * * * *",       # a/n 等价 a-max/n
])
def test_validate_cron_valid(expr):
    assert validate_cron(expr) is None


# ====================================================================
# 2 · validate_cron：非法表达式（CronError，消息含字段位置）
# ====================================================================

@pytest.mark.parametrize("expr", [
    "* * * *",            # 4 段
    "* * * * * *",        # 6 段
    "60 * * * *",         # 分越界
    "0 24 * * *",         # 时越界
    "0 0 0 * *",          # 日越界（下界 1）
    "0 0 * 13 *",         # 月越界
    "0 0 * * 8",          # 周越界
    "5-1 * * * *",        # 范围倒序
    "*/0 * * * *",        # step 为 0
    "a * * * *",          # 非法字符
    "",                   # 空串
    "*/* * * * *",        # step 非数字
    "0 0 1,,2 * *",       # 空段
])
def test_validate_cron_invalid(expr):
    with pytest.raises(CronError):
        validate_cron(expr)


def test_validate_cron_error_message_contains_field_position():
    with pytest.raises(CronError) as exc_info:
        validate_cron("0 24 * * *")
    assert "2" in str(exc_info.value), "消息须含出错字段位置（第 2 字段=时）"


def test_cron_error_is_value_error():
    assert issubclass(CronError, ValueError)


# ====================================================================
# 3 · cron_next：确定性计算（aware UTC 注入）
# ====================================================================

def test_next_every_minute_truncates_seconds():
    after = datetime(2026, 8, 5, 10, 30, 45, tzinfo=UTC)
    assert cron_next("* * * * *", after) == datetime(2026, 8, 5, 10, 31, 0, tzinfo=UTC)


def test_next_step_15_from_half_hour():
    assert cron_next("*/15 * * * *", NOW) == datetime(2026, 8, 5, 10, 45, tzinfo=UTC)


def test_next_daily_9am_rolls_to_tomorrow():
    assert cron_next("0 9 * * *", NOW) == datetime(2026, 8, 6, 9, 0, tzinfo=UTC)


def test_next_weekday_skips_weekend():
    friday = datetime(2026, 8, 7, 10, 0, tzinfo=UTC)
    assert friday.weekday() == 4, "2026-08-07 须为周五（用例前置校验）"
    assert cron_next("0 9 * * 1-5", friday) == datetime(2026, 8, 10, 9, 0, tzinfo=UTC)


def test_next_first_of_month():
    assert cron_next("0 0 1 * *", NOW) == datetime(2026, 9, 1, 0, 0, tzinfo=UTC)


def test_next_feb29_leaps_to_leap_year():
    after = datetime(2026, 1, 1, tzinfo=UTC)
    assert cron_next("0 0 29 2 *", after) == datetime(2028, 2, 29, 0, 0, tzinfo=UTC)


def test_next_impossible_date_returns_none():
    assert cron_next("0 0 30 2 *", datetime(2026, 1, 1, tzinfo=UTC)) is None


def test_next_dom_dow_or_semantics():
    # 每月 1 号或周一：after 周三 2026-08-05 → 周一 08-10 早于 09-01
    assert cron_next("0 0 1 * 1", NOW) == datetime(2026, 8, 10, 0, 0, tzinfo=UTC)


def test_next_sunday_7_equals_sunday_0():
    by7 = cron_next("0 0 * * 7", NOW)
    by0 = cron_next("0 0 * * 0", NOW)
    assert by7 == by0 == datetime(2026, 8, 9, 0, 0, tzinfo=UTC), "下个周日 2026-08-09"


def test_next_naive_after_returns_naive():
    result = cron_next("* * * * *", datetime(2026, 8, 5, 10, 30, 45))
    assert result is not None and result.tzinfo is None
    assert result == datetime(2026, 8, 5, 10, 31, 0)


def test_next_aware_after_preserves_tz():
    tz8 = timezone(timedelta(hours=8))
    after = datetime(2026, 8, 5, 18, 30, 45, tzinfo=tz8)
    result = cron_next("* * * * *", after)
    assert result is not None and result.tzinfo is tz8
    assert result == datetime(2026, 8, 5, 18, 31, 0, tzinfo=tz8)


def test_next_invalid_expr_raises():
    with pytest.raises(CronError):
        cron_next("banana", NOW)


# ====================================================================
# 4 · tasks.py 层：compute_next_run cron 分支 + add 落盘
# ====================================================================

def _task(**kw) -> ScheduledTask:
    defaults = dict(id="task-t0000001", title="t", prompt="p", created_at=NOW.isoformat())
    defaults.update(kw)
    return ScheduledTask(**defaults)


def test_compute_next_run_cron_disabled_returns_none():
    t = _task(kind="cron", cron="* * * * *", enabled=False)
    assert compute_next_run(t, NOW) is None


def test_compute_next_run_cron_dirty_data_returns_none_not_crash():
    t = _task(kind="cron", cron="not a cron")
    assert compute_next_run(t, NOW) is None, "落盘脏数据不得外抛异常"


def test_compute_next_run_cron_empty_returns_none():
    t = _task(kind="cron", cron=None)
    assert compute_next_run(t, NOW) is None


def test_compute_next_run_cron_returns_iso():
    t = _task(kind="cron", cron="*/15 * * * *")
    got = compute_next_run(t, NOW)
    # cron 按本地时区解释：结果 = cron_next(expr, NOW.astimezone())，同一时刻
    assert got == cron_next("*/15 * * * *", NOW.astimezone()).isoformat()
    assert datetime.fromisoformat(got) == datetime(2026, 8, 5, 10, 45, tzinfo=UTC)


def test_registry_add_cron_persists_and_reload(tmp_path):
    path = tmp_path / "tasks.json"
    reg = TaskRegistry(path)
    t = reg.add(title="巡检", prompt="p", kind="cron", cron="0 9 * * 1-5", now=NOW)
    assert t.cron == "0 9 * * 1-5"
    # 本地时区语义：next_run_at 落在本地 09:00（工作日），机器时区无关断言
    nxt = datetime.fromisoformat(t.next_run_at or "")
    local_nxt = nxt.astimezone()
    assert (local_nxt.hour, local_nxt.minute) == (9, 0)
    assert local_nxt.weekday() < 5
    assert nxt > NOW  # 严格未来时刻（aware 比较）
    reg2 = TaskRegistry(path)
    reloaded = reg2.get(t.id)
    assert reloaded is not None and reloaded.cron == "0 9 * * 1-5"
    assert reloaded == t, "reload 后全字段一致（含 cron）"


# ====================================================================
# 5 · main.py 端点层：创建路径
# ====================================================================

@pytest.fixture()
def registry(monkeypatch, tmp_path):
    """每个端点测试独立任务注册表（tmp 路径隔离，同 m178 惯例）。"""
    reg = TaskRegistry(tmp_path / "tasks.json")
    monkeypatch.setattr("api.main._TASK_REGISTRY", reg)
    monkeypatch.delenv("FLIPPED_TASKS", raising=False)
    monkeypatch.delenv("FLIPPED_TASKS_PATH", raising=False)
    return reg


@pytest.fixture()
def client(registry):
    from api.main import app
    with TestClient(app) as c:
        yield c


def test_create_cron_task_201_with_cron_field(client):
    r = client.post("/api/v1/tasks", json={
        "title": "晨报", "prompt": "写晨报", "kind": "cron", "cron": "0 9 * * 1-5"})
    assert r.status_code == 201, r.text
    data = r.json()
    assert data["kind"] == "cron" and data["cron"] == "0 9 * * 1-5"
    assert data["next_run_at"], "cron 任务创建即算 next_run_at"


def test_create_cron_task_missing_cron_422(client):
    r = client.post("/api/v1/tasks", json={"title": "t", "prompt": "p", "kind": "cron"})
    assert r.status_code == 422, r.text


def test_create_cron_task_invalid_expr_422(client):
    r = client.post("/api/v1/tasks", json={
        "title": "t", "prompt": "p", "kind": "cron", "cron": "0 24 * * *"})
    assert r.status_code == 422, r.text


def test_create_once_task_with_cron_422(client):
    run_at = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
    r = client.post("/api/v1/tasks", json={
        "title": "t", "prompt": "p", "kind": "once", "run_at": run_at, "cron": "* * * * *"})
    assert r.status_code == 422, r.text


def test_create_cron_task_feature_off_404(client, monkeypatch):
    monkeypatch.setenv("FLIPPED_TASKS", "0")
    r = client.post("/api/v1/tasks", json={
        "title": "t", "prompt": "p", "kind": "cron", "cron": "* * * * *"})
    assert r.status_code == 404, r.text
