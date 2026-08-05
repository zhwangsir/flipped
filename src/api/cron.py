"""M187.1 · cron 表达式解析与下次触发计算（纯逻辑模块）。

人类子集：5 字段（分 时 日 月 周），支持 * , - / 数字；周 0-7（0/7=周日）。
M191.3：月/周字段支持英文三字母名（JAN/MON，大小写不敏感；列表/范围/step 底数
全形态），支持 @ 宏（@daily 等，大小写不敏感；未知宏 → CronError「不支持的宏」）。
零 FastAPI、零 main import、零第三方依赖（项目零依赖惯例，requirements.txt 无 croniter）。

- validate_cron：合法性校验，非法 → CronError（消息含出错字段位置）
- cron_next：首个严格 > after 的触发时刻；after 截断到分钟再 +1min 起搜；
  dom/dow Vixie 语义（两者均受限 → OR；其一为 * → 另一个说了算）；
  字段跳跃算法（月→日→时→分逐级进位，不逐分钟暴力）；
  搜索上限 4 年，找不到 → None（如 "0 0 30 2 *"）；
  after aware → 返回同 tz aware；naive → naive（对齐 tasks._parse_dt 惯例）。
"""
from __future__ import annotations

from datetime import datetime, timedelta

# (字段名, 下界, 上界)——顺序即表达式字段序
_FIELDS = [
    ("分", 0, 59),
    ("时", 0, 23),
    ("日", 1, 31),
    ("月", 1, 12),
    ("周", 0, 7),
]

_SEARCH_LIMIT_DAYS = 366 * 4  # 搜索上限 4 年（覆盖闰年 2/29 跳跃）

# M191.3 · 月/周英文名映射（三字母，大小写不敏感）与 @ 宏展开表
_MONTHS = {"JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
           "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12}
_DOWS = {"SUN": 0, "MON": 1, "TUE": 2, "WED": 3, "THU": 4, "FRI": 5, "SAT": 6}
_MACROS = {"@yearly": "0 0 1 1 *", "@annually": "0 0 1 1 *",
           "@monthly": "0 0 1 * *", "@weekly": "0 0 * * 0",
           "@daily": "0 0 * * *", "@midnight": "0 0 * * *",
           "@hourly": "0 * * * *"}


class CronError(ValueError):
    """cron 表达式非法（字段数错/越界/倒序/step 0/非法字符/空段）。"""


def _parse_num(text: str, pos: int, name: str) -> int:
    if not text.isdigit():
        raise CronError(f"第{pos}字段({name})含非法字符: {text!r}")
    return int(text)


def _parse_field(part: str, pos: int, name: str, lo: int, hi: int,
                 names: dict[str, int] | None = None) -> tuple[set[int], bool]:
    """解析单字段 → (允许值集合, 是否裸 `*`)。裸 `*` 供 dom/dow Vixie 语义判定。

    M191.3：names 非 None 时（月/周字段）对 base 做 token 级名映射——范围两端点
    各自映射、单值整体映射（大小写不敏感）；step 底数保持纯数字。未知名原样交给
    _parse_num，自然触发既有「含非法字符」CronError。
    """
    if not part:
        raise CronError(f"第{pos}字段({name})为空段")

    def _map_name(text: str) -> str:
        if names is not None and text.upper() in names:
            return str(names[text.upper()])
        return text

    values: set[int] = set()
    for item in part.split(","):
        if not item:
            raise CronError(f"第{pos}字段({name})含空段: {part!r}")
        base, slash, step_text = item.partition("/")
        if slash:
            step = _parse_num(step_text, pos, name)
            if step < 1:
                raise CronError(f"第{pos}字段({name})step 必须 >=1: {item!r}")
        else:
            step = 1
        if base == "*":
            start, end = lo, hi
        elif "-" in base:
            a_text, _, b_text = base.partition("-")
            start = _parse_num(_map_name(a_text), pos, name)
            end = _parse_num(_map_name(b_text), pos, name)
            if start > end:
                raise CronError(f"第{pos}字段({name})范围倒序: {base!r}")
        else:
            start = _parse_num(_map_name(base), pos, name)
            end = hi if slash else start  # a/n 等价 a-max/n
        if start < lo or end > hi:
            raise CronError(f"第{pos}字段({name})值越界: {base!r} 不在 {lo}-{hi}")
        values.update(range(start, end + 1, step))
    if name == "周":
        values = {0 if v == 7 else v for v in values}  # 周日 0/7 等价
    return values, part == "*"


def _parse(expr: str) -> tuple[set[int], set[int], set[int], set[int], set[int], bool, bool]:
    """解析整表达式 → (分,时,日,月,周, 日裸*, 周裸*)；非法 → CronError。

    M191.3：strip 后以 @ 开头 → 整串（大小写不敏感）命中 _MACROS 则展开为
    标准 5 字段继续解析；未命中 → CronError「不支持的宏」。
    """
    if not isinstance(expr, str):
        raise CronError("cron 表达式必须是字符串")
    expr = expr.strip()
    if expr.startswith("@"):
        macro = _MACROS.get(expr.lower())
        if macro is None:
            raise CronError(f"不支持的宏: {expr!r}")
        expr = macro
    parts = expr.split()
    if len(parts) != 5:
        raise CronError(f"cron 表达式必须是 5 字段（分 时 日 月 周），实际 {len(parts)} 段")
    parsed = [_parse_field(part, i + 1, name, lo, hi,
                           names=_MONTHS if name == "月" else (_DOWS if name == "周" else None))
              for i, (part, (name, lo, hi)) in enumerate(zip(parts, _FIELDS))]
    (minutes, _), (hours, _), (doms, dom_star), (months, _), (dows, dow_star) = parsed
    return minutes, hours, doms, months, dows, dom_star, dow_star


def validate_cron(expr: str) -> None:
    """校验 cron 表达式合法性；非法 → CronError（消息含出错字段位置），合法 → None。"""
    _parse(expr)


def _cron_dow(t: datetime) -> int:
    """datetime → cron 周几（周日=0，周一=1 … 周六=6）。"""
    return (t.weekday() + 1) % 7


def _day_match(t: datetime, doms: set[int], dows: set[int],
               dom_star: bool, dow_star: bool) -> bool:
    """Vixie 语义：日/周均受限（非*）→ OR；其一为 * → 另一个说了算。"""
    if dom_star and dow_star:
        return True
    dom_ok = t.day in doms
    dow_ok = _cron_dow(t) in dows
    if dom_star:
        return dow_ok
    if dow_star:
        return dom_ok
    return dom_ok or dow_ok


def _next_month(t: datetime) -> datetime:
    """跳到下个月 1 号 00:00（月级进位）。"""
    if t.month == 12:
        return t.replace(year=t.year + 1, month=1, day=1, hour=0, minute=0)
    return t.replace(month=t.month + 1, day=1, hour=0, minute=0)


def cron_next(expr: str, after: datetime) -> datetime | None:
    """首个严格 > after 的触发时刻；4 年上限内找不到 → None。

    after 截断到分钟再 +1min 起搜；aware/naive 与 after 对齐。
    非法表达式 → CronError（调用方 compute_next_run 负责容错转 None）。
    """
    minutes, hours, doms, months, dows, dom_star, dow_star = _parse(expr)
    t = after.replace(second=0, microsecond=0) + timedelta(minutes=1)
    limit = t + timedelta(days=_SEARCH_LIMIT_DAYS)
    while t <= limit:
        if t.month not in months:
            t = _next_month(t)
            continue
        if not _day_match(t, doms, dows, dom_star, dow_star):
            t = (t + timedelta(days=1)).replace(hour=0, minute=0)
            continue
        if t.hour not in hours:
            t = (t + timedelta(hours=1)).replace(minute=0)
            continue
        if t.minute not in minutes:
            t = t + timedelta(minutes=1)
            continue
        return t
    return None
