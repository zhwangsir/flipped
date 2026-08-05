"""M191.3 · cron 英文名（JAN/MON）+ @宏 TDD 测试（B 队调度域）。

契约（PLAN.md M191.3 节，字段名一字不差）：
- _MACROS：@yearly/@annually/@monthly/@weekly/@daily/@midnight/@hourly 展开为标准
  5 字段；大小写不敏感；未知 @ 宏 → CronError「不支持的宏」。
- _MONTHS/_DOWS：月/周字段 token 级名映射（列表/范围/step 底数全形态，大小写
  不敏感）；分/时/日字段不映射；未知名 → 既有「含非法字符」CronError（含字段位置）。
- SUN=0 与 7 等价走既有归一；validate_cron/cron_next 签名不变；纯数字不回归。

风格沿用 test_m187_cron.py：同步测试 + 固定 aware UTC after 断言确定值。
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from api.cron import CronError, cron_next, validate_cron

UTC = timezone.utc
NOW = datetime(2026, 8, 5, 10, 30, 0, tzinfo=UTC)  # 2026-08-05 周三


# ====================================================================
# 1 · @宏：validate + cron_next 确定值
# ====================================================================

def test_macro_daily_next_midnight():
    assert validate_cron("@daily") is None
    assert cron_next("@daily", NOW) == datetime(2026, 8, 6, 0, 0, tzinfo=UTC)


def test_macro_midnight_equals_daily():
    assert validate_cron("@midnight") is None
    assert cron_next("@midnight", NOW) == datetime(2026, 8, 6, 0, 0, tzinfo=UTC)


def test_macro_hourly_next_whole_hour():
    assert validate_cron("@hourly") is None
    assert cron_next("@hourly", NOW) == datetime(2026, 8, 5, 11, 0, tzinfo=UTC)


def test_macro_weekly_next_sunday():
    assert validate_cron("@weekly") is None
    assert cron_next("@weekly", NOW) == datetime(2026, 8, 9, 0, 0, tzinfo=UTC), "下周日 2026-08-09"


def test_macro_monthly_first_of_next_month():
    assert validate_cron("@monthly") is None
    assert cron_next("@monthly", NOW) == datetime(2026, 9, 1, 0, 0, tzinfo=UTC)


def test_macro_yearly_and_annually():
    for expr in ("@yearly", "@annually"):
        assert validate_cron(expr) is None
        assert cron_next(expr, NOW) == datetime(2027, 1, 1, 0, 0, tzinfo=UTC)


def test_macro_case_insensitive():
    assert validate_cron("@DAILY") is None
    assert cron_next("@DAILY", NOW) == datetime(2026, 8, 6, 0, 0, tzinfo=UTC)


def test_macro_unknown_raises_with_message():
    with pytest.raises(CronError) as exc_info:
        validate_cron("@biweekly")
    assert "不支持的宏" in str(exc_info.value)


def test_macro_strip_surrounding_whitespace():
    assert validate_cron("  @daily  ") is None


# ====================================================================
# 2 · 月名（_MONTHS）：单名/范围/列表/大小写
# ====================================================================

def test_month_name_single_jan_crosses_year():
    assert validate_cron("0 0 1 JAN *") is None
    # after 2026-08-05 → 下个 1 月 1 号为 2027-01-01
    assert cron_next("0 0 1 JAN *", NOW) == datetime(2027, 1, 1, 0, 0, tzinfo=UTC)


def test_month_name_lowercase():
    assert cron_next("0 0 1 jan *", NOW) == datetime(2027, 1, 1, 0, 0, tzinfo=UTC)


def test_month_name_sep_next_month():
    assert cron_next("0 0 1 SEP *", NOW) == datetime(2026, 9, 1, 0, 0, tzinfo=UTC)


def test_month_name_range_jan_mar():
    assert validate_cron("0 0 1 JAN-MAR *") is None
    after = datetime(2026, 1, 15, 0, 0, tzinfo=UTC)
    assert cron_next("0 0 1 JAN-MAR *", after) == datetime(2026, 2, 1, 0, 0, tzinfo=UTC)


def test_month_name_list_jan_jul():
    assert validate_cron("0 0 1 JAN,JUL *") is None
    assert cron_next("0 0 1 JAN,JUL *", NOW) == datetime(2027, 1, 1, 0, 0, tzinfo=UTC)


# ====================================================================
# 3 · 周名（_DOWS）：范围/列表/大小写/SUN=0=7 等价
# ====================================================================

def test_dow_range_mon_fri_skips_weekend():
    friday = datetime(2026, 8, 7, 10, 0, tzinfo=UTC)
    assert friday.weekday() == 4, "2026-08-07 须为周五（用例前置校验）"
    assert cron_next("0 9 * * MON-FRI", friday) == datetime(2026, 8, 10, 9, 0, tzinfo=UTC)


def test_dow_sun_equals_0_and_7():
    by_name = cron_next("0 0 * * SUN", NOW)
    by0 = cron_next("0 0 * * 0", NOW)
    by7 = cron_next("0 0 * * 7", NOW)
    assert by_name == by0 == by7 == datetime(2026, 8, 9, 0, 0, tzinfo=UTC)


def test_dow_list_mon_wed_fri():
    assert validate_cron("0 9 * * MON,WED,FRI") is None
    # NOW=周三 10:30，当天 9:00 已过 → 周五 2026-08-07 09:00
    assert cron_next("0 9 * * MON,WED,FRI", NOW) == datetime(2026, 8, 7, 9, 0, tzinfo=UTC)


def test_dow_range_lowercase():
    assert validate_cron("0 9 * * mon-fri") is None
    friday = datetime(2026, 8, 7, 10, 0, tzinfo=UTC)
    assert cron_next("0 9 * * mon-fri", friday) == datetime(2026, 8, 10, 9, 0, tzinfo=UTC)


# ====================================================================
# 4 · step 兼容：*/n、范围带 step、名单独带 step（a/n 等价 a-max/n）
# ====================================================================

def test_step_star_still_works():
    after = datetime(2026, 8, 5, 10, 30, 45, tzinfo=UTC)
    assert validate_cron("*/2 * * * *") is None
    assert cron_next("*/2 * * * *", after) == datetime(2026, 8, 5, 10, 32, tzinfo=UTC)


def test_step_on_named_range():
    assert validate_cron("0 9-18/2 * * MON-FRI") is None
    # 时 {9,11,13,15,17}；NOW=周三 10:30 → 当天 11:00
    assert cron_next("0 9-18/2 * * MON-FRI", NOW) == datetime(2026, 8, 5, 11, 0, tzinfo=UTC)


def test_step_on_single_name_means_name_to_max():
    assert validate_cron("0 0 * * MON/2") is None
    # MON/2 = 1-7/2 → {MON,WED,FRI,SUN}；NOW=周三 10:30 → 周五 2026-08-07 00:00
    assert cron_next("0 0 * * MON/2", NOW) == datetime(2026, 8, 7, 0, 0, tzinfo=UTC)


# ====================================================================
# 5 · 未知名：既有「含非法字符」CronError，消息含字段位置
# ====================================================================

def test_unknown_dow_name_raises_field5():
    with pytest.raises(CronError) as exc_info:
        validate_cron("0 0 * * FUNDAY")
    assert "第5字段" in str(exc_info.value)


def test_unknown_month_name_raises_field4():
    with pytest.raises(CronError) as exc_info:
        validate_cron("0 0 1 FOO *")
    assert "第4字段" in str(exc_info.value)


def test_names_not_mapped_in_other_fields():
    # 分/时/日字段不做名映射：MON 出现在分字段 → 非法字符
    with pytest.raises(CronError):
        validate_cron("MON * * * *")


# ====================================================================
# 6 · 不回归：纯数字表达式行为不变
# ====================================================================

def test_numeric_forms_unchanged():
    assert cron_next("0 9 * * *", NOW) == datetime(2026, 8, 6, 9, 0, tzinfo=UTC)
    assert cron_next("*/15 * * * *", NOW) == datetime(2026, 8, 5, 10, 45, tzinfo=UTC)
    assert cron_next("0 9 * * 1-5", datetime(2026, 8, 7, 10, 0, tzinfo=UTC)) == \
        datetime(2026, 8, 10, 9, 0, tzinfo=UTC)
