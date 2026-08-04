"""M182 · Bot Channel 纯逻辑 TDD 测试（B182 队）。

- BotSessionRegistry：bind/resolve、user_name 持久化、持久化往返、坏 JSON/非 dict 回退空
- ChannelStats：三计数 + last_error + 时间戳、status/all_statuses（按 platform 排序）、
  坏文件回退空不炸
- wait_for_reply：新 assistant turn 出现即返回 / 超时 None / get_history 异常重试至超时
- handle_inbound：全流程（建会话→bind→dispatch→reply 发送+outbound 记账）/
  已绑定复用不新建 / 超时兜底文案 / 异常吞掉 record_error 返回 False
- env 路径与超时常量：默认值 + env 覆盖 + 非法值回退

风格沿用 test_m178_tasks.py：同步测试函数 + asyncio.run 包裹 async 场景，绝不碰真网络。
"""
from __future__ import annotations

import asyncio
import json

from api.bot_channel import (
    BotSessionRegistry,
    ChannelStats,
    UnifiedMessage,
    bot_db_path,
    bot_reply_timeout_s,
    bot_stats_db_path,
    handle_inbound,
    wait_for_reply,
)

# ====================================================================
# 1 · BotSessionRegistry（tmp_path 隔离）
# ====================================================================

def test_registry_bind_resolve_roundtrip(tmp_path):
    reg = BotSessionRegistry(tmp_path / "bot_sessions.json")
    assert reg.resolve("telegram", "42") is None, "未绑定 → None"
    reg.bind("telegram", "42", "sess-a")
    assert reg.resolve("telegram", "42") == "sess-a"
    data = json.loads((tmp_path / "bot_sessions.json").read_text(encoding="utf-8"))
    assert data["telegram:42"]["session_id"] == "sess-a"
    assert data["telegram:42"]["user_name"] == "", "user_name 缺省空串"
    assert data["telegram:42"]["bound_at"] > 0


def test_registry_bind_with_user_name_and_rebind(tmp_path):
    reg = BotSessionRegistry(tmp_path / "bot_sessions.json")
    reg.bind("telegram", "42", "sess-a", user_name="alice")
    data = json.loads((tmp_path / "bot_sessions.json").read_text(encoding="utf-8"))
    assert data["telegram:42"]["user_name"] == "alice"
    reg.bind("telegram", "42", "sess-b", user_name="alice2")
    assert reg.resolve("telegram", "42") == "sess-b", "重复 bind → 覆盖旧 session_id"


def test_registry_platform_chat_isolated(tmp_path):
    reg = BotSessionRegistry(tmp_path / "bot_sessions.json")
    reg.bind("telegram", "42", "sess-tg")
    reg.bind("wecom", "42", "sess-wx")
    assert reg.resolve("telegram", "42") == "sess-tg"
    assert reg.resolve("wecom", "42") == "sess-wx", "platform+chat_id 复合键互不串"
    assert reg.resolve("wecom", "43") is None


def test_registry_persistence_roundtrip(tmp_path):
    path = tmp_path / "bot_sessions.json"
    BotSessionRegistry(path).bind("wecom", "u1", "sess-x", user_name="bob")
    reg2 = BotSessionRegistry(path)  # 全新实例从磁盘恢复
    assert reg2.resolve("wecom", "u1") == "sess-x"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["wecom:u1"]["user_name"] == "bob"


def test_registry_load_corrupt_json_returns_empty(tmp_path):
    path = tmp_path / "bot_sessions.json"
    path.write_text("{not json", encoding="utf-8")
    reg = BotSessionRegistry(path)  # 坏文件不炸
    assert reg.resolve("telegram", "42") is None


def test_registry_load_non_dict_json_returns_empty(tmp_path):
    path = tmp_path / "bot_sessions.json"
    path.write_text('["telegram:42"]', encoding="utf-8")
    reg = BotSessionRegistry(path)  # 结构非 dict → 空注册表不炸
    assert reg.resolve("telegram", "42") is None


# ====================================================================
# 2 · ChannelStats（tmp_path 隔离）
# ====================================================================

def test_stats_record_all_counters_and_timestamps(tmp_path):
    stats = ChannelStats(tmp_path / "bot_stats.json")
    stats.record_inbound("telegram")
    stats.record_inbound("telegram")
    stats.record_outbound("telegram")
    stats.record_error("telegram", "boom")
    st = stats.status("telegram", configured=True)
    assert st.platform == "telegram"
    assert st.enabled is True and st.configured is True
    assert st.inbound_count == 2 and st.outbound_count == 1 and st.error_count == 1
    assert st.last_inbound_at is not None and st.last_outbound_at is not None
    assert st.last_inbound_at > 0 and st.last_outbound_at > 0
    assert st.last_error == "boom"


def test_stats_persisted_to_disk_and_reload(tmp_path):
    path = tmp_path / "bot_stats.json"
    ChannelStats(path).record_inbound("wecom")
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["wecom"]["inbound_count"] == 1
    stats2 = ChannelStats(path)  # 重启重载
    assert stats2.status("wecom", configured=False).inbound_count == 1


def test_stats_status_unknown_platform_zero_filled(tmp_path):
    stats = ChannelStats(tmp_path / "bot_stats.json")
    st = stats.status("wecom", configured=False, enabled=False)
    assert st.platform == "wecom"
    assert st.inbound_count == 0 and st.outbound_count == 0 and st.error_count == 0
    assert st.last_inbound_at is None and st.last_outbound_at is None
    assert st.last_error == ""
    assert st.enabled is False and st.configured is False


def test_stats_all_statuses_sorted_and_zero_filled(tmp_path):
    stats = ChannelStats(tmp_path / "bot_stats.json")
    stats.record_inbound("wecom")
    out = stats.all_statuses({"telegram": True, "wecom": False})
    assert [s.platform for s in out] == ["telegram", "wecom"], "必须按 platform 字典序排序"
    tg, wx = out
    assert tg.configured is True and tg.enabled is True
    assert tg.inbound_count == 0, "未记录平台计数零填充"
    assert wx.configured is False and wx.inbound_count == 1
    assert wx.enabled is False, "configured=False → enabled 强制 False"


def test_stats_all_statuses_disabled_env(tmp_path):
    stats = ChannelStats(tmp_path / "bot_stats.json")
    out = stats.all_statuses({"telegram": True}, enabled=False)
    assert out[0].enabled is False and out[0].configured is True


def test_stats_load_corrupt_json_returns_empty(tmp_path):
    path = tmp_path / "bot_stats.json"
    path.write_text("{broken", encoding="utf-8")
    stats = ChannelStats(path)  # 坏文件不炸
    st = stats.status("telegram", configured=True)
    assert st.inbound_count == 0


def test_stats_last_error_overwritten_and_error_alone(tmp_path):
    stats = ChannelStats(tmp_path / "bot_stats.json")
    stats.record_error("telegram", "first")
    stats.record_error("telegram", "second")
    st = stats.status("telegram", configured=True)
    assert st.error_count == 2 and st.last_error == "second"
    assert st.last_inbound_at is None, "仅 record_error 不动 inbound 时间戳"


# ====================================================================
# 3 · wait_for_reply（asyncio.run 包裹，interval_s=0.01 加速）
# ====================================================================

def _turns(*specs):
    return [{"role": r, "text": t} for r, t in specs]


def test_wait_for_reply_returns_new_assistant_text():
    calls = {"n": 0}

    async def get_history(_sid):
        calls["n"] += 1
        if calls["n"] < 3:
            return _turns(("user", "hi"))
        return _turns(("user", "hi"), ("assistant", "你好，已完成"))

    async def _run():
        return await wait_for_reply(get_history, "sess-1", baseline_turns=1,
                                    timeout_s=5.0, interval_s=0.01)
    assert asyncio.run(_run()) == "你好，已完成"
    assert calls["n"] == 3, "第 3 次轮询出新 assistant turn"


def test_wait_for_reply_ignores_stale_assistant_and_user_tail():
    async def get_history(_sid):
        # baseline 之后新增的是 user turn → 不满足（尾条必须 assistant）
        return _turns(("assistant", "旧回复"), ("user", "q1"), ("user", "q2"))

    async def _run():
        return await wait_for_reply(get_history, "sess-1", baseline_turns=1,
                                    timeout_s=0.05, interval_s=0.01)
    assert asyncio.run(_run()) is None, "尾条非 assistant → 超时 None"


def test_wait_for_reply_empty_assistant_text_not_accepted():
    async def get_history(_sid):
        return _turns(("user", "hi"), ("assistant", ""))

    async def _run():
        return await wait_for_reply(get_history, "sess-1", baseline_turns=1,
                                    timeout_s=0.05, interval_s=0.01)
    assert asyncio.run(_run()) is None, "assistant 空 text 不算有效回复"


def test_wait_for_reply_timeout_returns_none():
    async def get_history(_sid):
        return _turns(("user", "hi"))  # 永不新增

    async def _run():
        return await wait_for_reply(get_history, "sess-1", baseline_turns=1,
                                    timeout_s=0.05, interval_s=0.01)
    assert asyncio.run(_run()) is None


def test_wait_for_reply_history_errors_retried_until_success():
    calls = {"n": 0}

    async def get_history(_sid):
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError("transient io")
        return _turns(("user", "hi"), ("assistant", "ok"))

    async def _run():
        return await wait_for_reply(get_history, "sess-1", baseline_turns=1,
                                    timeout_s=5.0, interval_s=0.01)
    assert asyncio.run(_run()) == "ok", "get_history 异常必须吞掉继续重试"
    assert calls["n"] == 3


def test_wait_for_reply_history_errors_until_timeout():
    async def get_history(_sid):
        raise RuntimeError("always down")

    async def _run():
        return await wait_for_reply(get_history, "sess-1", baseline_turns=0,
                                    timeout_s=0.05, interval_s=0.01)
    assert asyncio.run(_run()) is None, "持续异常 → 超时 None 不上抛"


# ====================================================================
# 4 · handle_inbound（四注入 fake，断言全链路与记账）
# ====================================================================

def _msg(platform="telegram", chat_id="42", user_id="7", user_name="alice",
         text="帮我跑个任务", message_id="m-1"):
    return UnifiedMessage(platform=platform, chat_id=chat_id, user_id=user_id,
                          user_name=user_name, text=text, message_id=message_id)


def test_handle_inbound_full_flow(tmp_path):
    registry = BotSessionRegistry(tmp_path / "bot_sessions.json")
    stats = ChannelStats(tmp_path / "bot_stats.json")
    created, dispatched, sent = [], [], []

    async def create_session(title):
        created.append(title)
        return "sess-new"

    async def dispatch(sid, text):
        dispatched.append((sid, text))

    async def await_reply(sid):
        return "任务完成 ✅"

    async def send_reply(text):
        sent.append(text)
        return (True, "")

    async def _run():
        return await handle_inbound(_msg(), registry=registry, stats=stats,
                                    create_session=create_session, dispatch=dispatch,
                                    await_reply=await_reply, send_reply=send_reply)
    assert asyncio.run(_run()) is True
    assert created == ["bot:telegram:alice"], "会话标题 = bot:{platform}:{user_name}"
    assert registry.resolve("telegram", "42") == "sess-new", "新会话必须 bind"
    assert dispatched == [("sess-new", "帮我跑个任务")]
    assert sent == ["任务完成 ✅"]
    st = stats.status("telegram", configured=True)
    assert st.inbound_count == 1 and st.outbound_count == 1 and st.error_count == 0


def test_handle_inbound_title_fallback_to_user_id(tmp_path):
    registry = BotSessionRegistry(tmp_path / "bot_sessions.json")
    stats = ChannelStats(tmp_path / "bot_stats.json")
    created = []

    async def create_session(title):
        created.append(title)
        return "sess-1"

    async def _run():
        return await handle_inbound(
            _msg(user_name="", user_id="u-9"), registry=registry, stats=stats,
            create_session=create_session, dispatch=lambda s, t: asyncio.sleep(0),
            await_reply=lambda s: asyncio.sleep(0, result="r"),
            send_reply=lambda t: asyncio.sleep(0, result=(True, "")))
    assert asyncio.run(_run()) is True
    assert created == ["bot:telegram:u-9"], "user_name 空 → 回退 user_id"


def test_handle_inbound_reuses_bound_session(tmp_path):
    registry = BotSessionRegistry(tmp_path / "bot_sessions.json")
    stats = ChannelStats(tmp_path / "bot_stats.json")
    registry.bind("telegram", "42", "sess-old")
    created, dispatched = [], []

    async def create_session(title):
        created.append(title)
        return "sess-should-not-happen"

    async def dispatch(sid, text):
        dispatched.append(sid)

    async def _run():
        return await handle_inbound(_msg(), registry=registry, stats=stats,
                                    create_session=create_session, dispatch=dispatch,
                                    await_reply=lambda s: asyncio.sleep(0, result="r"),
                                    send_reply=lambda t: asyncio.sleep(0, result=(True, "")))
    assert asyncio.run(_run()) is True
    assert created == [], "已绑定会话不得新建"
    assert dispatched == ["sess-old"]


def test_handle_inbound_timeout_fallback_sent_and_counted(tmp_path):
    registry = BotSessionRegistry(tmp_path / "bot_sessions.json")
    stats = ChannelStats(tmp_path / "bot_stats.json")
    sent = []

    async def send_reply(text):
        sent.append(text)
        return (True, "")

    async def _run():
        return await handle_inbound(
            _msg(), registry=registry, stats=stats,
            create_session=lambda t: asyncio.sleep(0, result="sess-1"),
            dispatch=lambda s, t: asyncio.sleep(0),
            await_reply=lambda s: asyncio.sleep(0, result=None),  # 超时
            send_reply=send_reply)
    assert asyncio.run(_run()) is True
    assert sent == ["任务已受理，处理时间较长，稍后可在控制台查看结果。"], "超时发兜底文案"
    st = stats.status("telegram", configured=True)
    assert st.outbound_count == 1 and st.error_count == 0, "兜底发送成功记 outbound"


def test_handle_inbound_reply_truncated_4000(tmp_path):
    registry = BotSessionRegistry(tmp_path / "bot_sessions.json")
    stats = ChannelStats(tmp_path / "bot_stats.json")
    sent = []

    async def send_reply(text):
        sent.append(text)
        return (True, "")

    async def _run():
        return await handle_inbound(
            _msg(), registry=registry, stats=stats,
            create_session=lambda t: asyncio.sleep(0, result="sess-1"),
            dispatch=lambda s, t: asyncio.sleep(0),
            await_reply=lambda s: asyncio.sleep(0, result="长" * 5000),
            send_reply=send_reply)
    assert asyncio.run(_run()) is True
    assert len(sent[0]) == 4000, "回复必须截断到 4000 字符"


def test_handle_inbound_send_failure_records_error(tmp_path):
    registry = BotSessionRegistry(tmp_path / "bot_sessions.json")
    stats = ChannelStats(tmp_path / "bot_stats.json")

    async def _run():
        return await handle_inbound(
            _msg(), registry=registry, stats=stats,
            create_session=lambda t: asyncio.sleep(0, result="sess-1"),
            dispatch=lambda s, t: asyncio.sleep(0),
            await_reply=lambda s: asyncio.sleep(0, result="r"),
            send_reply=lambda t: asyncio.sleep(0, result=(False, "http 401")))
    assert asyncio.run(_run()) is False, "发送失败 → False"
    st = stats.status("telegram", configured=True)
    assert st.outbound_count == 0 and st.error_count == 1
    assert st.last_error == "http 401"


def test_handle_inbound_dispatch_exception_swallowed(tmp_path):
    registry = BotSessionRegistry(tmp_path / "bot_sessions.json")
    stats = ChannelStats(tmp_path / "bot_stats.json")

    async def dispatch(_sid, _text):
        raise RuntimeError("dispatch exploded")

    async def _run():
        return await handle_inbound(
            _msg(), registry=registry, stats=stats,
            create_session=lambda t: asyncio.sleep(0, result="sess-1"),
            dispatch=dispatch,
            await_reply=lambda s: asyncio.sleep(0, result="r"),
            send_reply=lambda t: asyncio.sleep(0, result=(True, "")))
    assert asyncio.run(_run()) is False, "任何异常吞掉返回 False"
    st = stats.status("telegram", configured=True)
    assert st.error_count == 1 and st.last_error == "dispatch exploded"


def test_handle_inbound_timeout_fallback_send_failure_records_error(tmp_path):
    registry = BotSessionRegistry(tmp_path / "bot_sessions.json")
    stats = ChannelStats(tmp_path / "bot_stats.json")

    async def _run():
        return await handle_inbound(
            _msg(), registry=registry, stats=stats,
            create_session=lambda t: asyncio.sleep(0, result="sess-1"),
            dispatch=lambda s, t: asyncio.sleep(0),
            await_reply=lambda s: asyncio.sleep(0, result=None),
            send_reply=lambda t: asyncio.sleep(0, result=(False, "net down")))
    assert asyncio.run(_run()) is False
    st = stats.status("telegram", configured=True)
    assert st.error_count == 1 and st.last_error == "net down"


# ====================================================================
# 5 · env 路径与超时常量
# ====================================================================

def test_env_paths_default_and_override(monkeypatch, tmp_path):
    monkeypatch.delenv("FLIPPED_BOT_DB", raising=False)
    monkeypatch.delenv("FLIPPED_BOT_STATS_DB", raising=False)
    assert str(bot_db_path()).endswith("data/bot_sessions.json")
    assert str(bot_stats_db_path()).endswith("data/bot_stats.json")
    monkeypatch.setenv("FLIPPED_BOT_DB", str(tmp_path / "x.json"))
    monkeypatch.setenv("FLIPPED_BOT_STATS_DB", str(tmp_path / "y.json"))
    assert bot_db_path() == tmp_path / "x.json"
    assert bot_stats_db_path() == tmp_path / "y.json"


def test_reply_timeout_default_override_and_invalid(monkeypatch):
    monkeypatch.delenv("FLIPPED_BOT_REPLY_TIMEOUT_S", raising=False)
    assert bot_reply_timeout_s() == 90.0
    monkeypatch.setenv("FLIPPED_BOT_REPLY_TIMEOUT_S", "12.5")
    assert bot_reply_timeout_s() == 12.5
    monkeypatch.setenv("FLIPPED_BOT_REPLY_TIMEOUT_S", "not-a-number")
    assert bot_reply_timeout_s() == 90.0, "非法 env 值回退 90"
