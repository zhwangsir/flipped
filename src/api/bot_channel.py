"""M182 · Bot Channel 核心纯逻辑（B182 队）：统一消息 / 身份映射 / 状态监控 / 入站编排。

本模块零 FastAPI import、零 main/assistant import——全部外部能力（建会话、派发、
等回复、回发）经参数注入，单测用 fake，生产由 main.py M182 区块接线（主代理 Phase 3）。

持久化惯例复刻 remote.py / tasks.py：JSON 文件 + tmp & os.replace 原子写，
坏文件/结构漂移回退空不炸（防坏文件拖垮启动）。
"""
from __future__ import annotations

import asyncio
import json
import os
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path


@dataclass
class UnifiedMessage:
    """一条平台无关的入站消息（各平台 parser 产出，handle_inbound 消费）。"""

    platform: str      # "telegram" / "wecom"
    chat_id: str       # 会话标识（telegram chat.id / wecom FromUserName）
    user_id: str       # 用户标识
    user_name: str     # 可空，空串兜底
    text: str          # 文本内容（parser 保证非空）
    message_id: str    # 平台消息 id，缺省 ""


@dataclass
class ChannelStatus:
    """单平台通道状态快照（GET /bot/channels 响应形状，C 队消费）。"""

    platform: str
    enabled: bool          # env 开关且 configured
    configured: bool       # 平台所需 env 齐备
    inbound_count: int
    outbound_count: int
    error_count: int
    last_inbound_at: float | None
    last_outbound_at: float | None
    last_error: str


def bot_db_path() -> Path:
    """身份映射 JSON 路径：env FLIPPED_BOT_DB，缺省 data/bot_sessions.json。"""
    return Path(os.environ.get("FLIPPED_BOT_DB", "data/bot_sessions.json"))


def bot_stats_db_path() -> Path:
    """通道统计 JSON 路径：env FLIPPED_BOT_STATS_DB，缺省 data/bot_stats.json。"""
    return Path(os.environ.get("FLIPPED_BOT_STATS_DB", "data/bot_stats.json"))


def bot_reply_timeout_s() -> float:
    """等回复超时秒数：env FLIPPED_BOT_REPLY_TIMEOUT_S，缺省 90，非法值回退 90。"""
    try:
        return float(os.environ.get("FLIPPED_BOT_REPLY_TIMEOUT_S", "90"))
    except ValueError:
        return 90.0


class BotSessionRegistry:
    """身份映射注册表：f"{platform}:{chat_id}" → session_id（JSON dict 持久化）。

    值形状 {"session_id":..., "user_name":..., "bound_at":...}；
    文件不存在/JSON 损坏/结构非 dict → 空注册表不炸；bind 即落盘（原子写）。
    """

    def __init__(self, path: Path):
        self._path = Path(path)
        self._bindings: dict[str, dict] = {}
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001 坏文件不炸，回退空表
            return
        if isinstance(data, dict):
            self._bindings = {str(k): v for k, v in data.items() if isinstance(v, dict)}

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = f"{self._path}.tmp"
        Path(tmp).write_text(
            json.dumps(self._bindings, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, self._path)

    @staticmethod
    def _key(platform: str, chat_id: str) -> str:
        return f"{platform}:{chat_id}"

    def resolve(self, platform: str, chat_id: str) -> str | None:
        """按 platform+chat_id 查已绑定 session_id，未绑定 → None。"""
        entry = self._bindings.get(self._key(platform, chat_id))
        if not isinstance(entry, dict):
            return None
        sid = entry.get("session_id")
        return sid if isinstance(sid, str) and sid else None

    def bind(self, platform: str, chat_id: str, session_id: str, user_name: str = "") -> None:
        """绑定（或覆盖）会话映射并落盘。"""
        self._bindings[self._key(platform, chat_id)] = {
            "session_id": session_id,
            "user_name": user_name,
            "bound_at": time.time(),
        }
        self._save()

    def latest_chat_id(self, platform: str) -> str | None:
        """该平台最近绑定的 chat_id（bound_at 最大）；无绑定 → None（测试消息投递目标）。"""
        best_ts = -1.0
        best_chat: str | None = None
        prefix = f"{platform}:"
        for key, entry in self._bindings.items():
            if not key.startswith(prefix):
                continue
            ts = entry.get("bound_at")
            ts = float(ts) if isinstance(ts, (int, float)) else 0.0
            if best_chat is None or ts > best_ts:
                best_ts, best_chat = ts, key[len(prefix):]
        return best_chat


_STATS_KEYS = ("inbound_count", "outbound_count", "error_count",
               "last_inbound_at", "last_outbound_at", "last_error")


class ChannelStats:
    """通道状态统计：三计数 + 末次时间戳 + 末次错误（JSON dict 持久化，原子写）。

    文件形状 {platform: {inbound_count, outbound_count, error_count,
    last_inbound_at, last_outbound_at, last_error}}；坏文件回退空不炸。
    """

    def __init__(self, path: Path):
        self._path = Path(path)
        self._stats: dict[str, dict] = {}
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001 坏文件不炸，回退空表
            return
        if isinstance(data, dict):
            self._stats = {str(k): v for k, v in data.items() if isinstance(v, dict)}

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = f"{self._path}.tmp"
        Path(tmp).write_text(
            json.dumps(self._stats, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, self._path)

    def _entry(self, platform: str) -> dict:
        """取平台条目（缺省零填充模板，写路径先调本方法再改字段）。"""
        return self._stats.setdefault(platform, {
            "inbound_count": 0, "outbound_count": 0, "error_count": 0,
            "last_inbound_at": None, "last_outbound_at": None, "last_error": "",
        })

    def record_inbound(self, platform: str) -> None:
        e = self._entry(platform)
        e["inbound_count"] += 1
        e["last_inbound_at"] = time.time()
        self._save()

    def record_outbound(self, platform: str) -> None:
        e = self._entry(platform)
        e["outbound_count"] += 1
        e["last_outbound_at"] = time.time()
        self._save()

    def record_error(self, platform: str, err: str = "") -> None:
        e = self._entry(platform)
        e["error_count"] += 1
        e["last_error"] = err
        self._save()

    def status(self, platform: str, *, configured: bool, enabled: bool = True) -> ChannelStatus:
        """单平台状态快照：计数零填充；enabled = 开关 and configured。"""
        e = self._stats.get(platform, {})
        return ChannelStatus(
            platform=platform,
            enabled=enabled and configured,
            configured=configured,
            inbound_count=e.get("inbound_count", 0),
            outbound_count=e.get("outbound_count", 0),
            error_count=e.get("error_count", 0),
            last_inbound_at=e.get("last_inbound_at"),
            last_outbound_at=e.get("last_outbound_at"),
            last_error=e.get("last_error", ""),
        )

    def all_statuses(self, configured: dict[str, bool], *, enabled: bool = True) -> list[ChannelStatus]:
        """全平台状态列表，按 platform 字典序排序（configured 未列的平台不出现）。"""
        return [self.status(p, configured=c, enabled=enabled)
                for p, c in sorted(configured.items())]


async def wait_for_reply(
    get_history: Callable[[str], Awaitable[list[dict]]],
    session_id: str,
    baseline_turns: int,
    timeout_s: float,
    interval_s: float = 1.0,
) -> str | None:
    """轮询会话历史，等 baseline 之后新增的 assistant 非空回复。

    get_history(sid) 返回 turn dict 列表（至少含 role/text）。
    条件：len(turns) > baseline_turns 且尾条 role=="assistant" 且 text 非空 → 返回该 text。
    超时 → None；get_history 异常吞掉继续重试直到超时（瞬时 I/O 抖动不致命）。
    """
    deadline = time.monotonic() + timeout_s
    while True:
        try:
            turns = await get_history(session_id)
            if len(turns) > baseline_turns:
                tail = turns[-1]
                if tail.get("role") == "assistant":
                    text = tail.get("text") or ""
                    if text:
                        return text
        except Exception:  # noqa: BLE001 历史读取瞬时失败 → 下一轮重试
            pass
        if time.monotonic() >= deadline:
            return None
        await asyncio.sleep(interval_s)


async def handle_inbound(
    msg: UnifiedMessage,
    *,
    registry: BotSessionRegistry,
    stats: ChannelStats,
    create_session: Callable[[str], Awaitable[str]],
    dispatch: Callable[[str, str], Awaitable[None]],
    await_reply: Callable[[str], Awaitable[str | None]],
    send_reply: Callable[[str], Awaitable[tuple[bool, str]]],
    timeout_fallback: str = "任务已受理，处理时间较长，稍后可在控制台查看结果。",
) -> bool:
    """入站消息全链路编排（全注入保纯，零框架依赖）。

    流程：resolve → 未绑定则 create_session(f"bot:{platform}:{user_name or user_id}")
    并 bind → record_inbound → dispatch → await_reply → 有回复 send_reply(截 4000)，
    超时发 timeout_fallback；发送成功 record_outbound，失败 record_error。
    任何异常 → record_error(platform, str(e)) 吞掉返回 False；全成功返回 True。
    """
    try:
        sid = registry.resolve(msg.platform, msg.chat_id)
        if sid is None:
            sid = await create_session(f"bot:{msg.platform}:{msg.user_name or msg.user_id}")
            registry.bind(msg.platform, msg.chat_id, sid, user_name=msg.user_name)
        stats.record_inbound(msg.platform)
        await dispatch(sid, msg.text)
        reply = await await_reply(sid)
        text = reply[:4000] if reply else timeout_fallback
        ok, err = await send_reply(text)
        if ok:
            stats.record_outbound(msg.platform)
            return True
        stats.record_error(msg.platform, err)
        return False
    except Exception as e:  # noqa: BLE001 任何异常吞掉，webhook 侧永远 200/False
        stats.record_error(msg.platform, str(e))
        return False
