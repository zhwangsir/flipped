"""M182 · Telegram Bot Channel TDD 测试（B182 队）。

- verify_secret：对/错/None 头/空 expected
- parse_update：正常文本 / 无 message / 非文本（photo）/ edited_message 忽略 /
  chat_id·user_id·message_id int→str / username·first_name 回退
- TelegramSender（fake client 注入，绝不碰真网络）：200 ok=true / http 401 /
  ok=false description / 网络异常 (False, str) 不上抛 / text 截 4000
- configured()/secret_configured()：env 有/无
"""
from __future__ import annotations

import asyncio

from api.bot_telegram import (
    TelegramSender,
    configured,
    parse_update,
    secret_configured,
    verify_secret,
)

# ====================================================================
# 1 · verify_secret
# ====================================================================

def test_verify_secret_match():
    assert verify_secret("s3cret-value", "s3cret-value") is True


def test_verify_secret_mismatch_and_prefix():
    assert verify_secret("wrong", "s3cret-value") is False
    assert verify_secret("s3cret", "s3cret-value") is False, "前缀不得放行"


def test_verify_secret_none_header():
    assert verify_secret(None, "s3cret-value") is False


def test_verify_secret_empty_expected_rejects_all():
    assert verify_secret("anything", "") is False, "expected 空 → 一律 False"
    assert verify_secret("", "") is False


# ====================================================================
# 2 · parse_update
# ====================================================================

def _text_update(**overrides):
    body = {
        "update_id": 100,
        "message": {
            "message_id": 55,
            "from": {"id": 777, "username": "alice", "first_name": "Alice"},
            "chat": {"id": 424242, "type": "private"},
            "text": "你好 bot",
        },
    }
    for key, value in overrides.items():
        body[key] = value
    return body


def test_parse_update_normal_text():
    msg = parse_update(_text_update())
    assert msg is not None
    assert msg.platform == "telegram"
    assert msg.chat_id == "424242", "chat.id int → str"
    assert msg.user_id == "777", "from.id int → str"
    assert msg.user_name == "alice", "username 优先"
    assert msg.text == "你好 bot"
    assert msg.message_id == "55", "message_id int → str"


def test_parse_update_user_name_fallbacks():
    body = _text_update()
    body["message"]["from"] = {"id": 777, "first_name": "Alice"}
    assert parse_update(body).user_name == "Alice", "无 username → first_name"
    body["message"]["from"] = {"id": 777}
    assert parse_update(body).user_name == "", "皆无 → 空串"


def test_parse_update_no_message_returns_none():
    assert parse_update({"update_id": 100}) is None
    assert parse_update({}) is None


def test_parse_update_edited_message_ignored():
    body = {"update_id": 100, "edited_message": _text_update()["message"]}
    assert parse_update(body) is None, "edited_message 必须忽略"
    body2 = {"update_id": 100, "channel_post": _text_update()["message"]}
    assert parse_update(body2) is None, "channel_post 必须忽略"


def test_parse_update_non_text_returns_none():
    body = _text_update()
    del body["message"]["text"]
    body["message"]["photo"] = [{"file_id": "x"}]
    assert parse_update(body) is None, "photo 无 text → None"
    body2 = _text_update()
    body2["message"]["text"] = ""
    assert parse_update(body2) is None, "空 text → None"
    body3 = _text_update()
    body3["message"]["text"] = 12345
    assert parse_update(body3) is None, "非 str text → None"


# ====================================================================
# 3 · TelegramSender（fake client 注入）
# ====================================================================

class _FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {"ok": True, "result": {}}

    def json(self):
        return self._payload


class _FakeClient:
    """模拟注入的 httpx.AsyncClient：记录调用、按队列返回响应或抛异常。"""

    def __init__(self, *steps):
        self._steps = list(steps)
        self.calls = []

    async def post(self, url, json=None):
        self.calls.append((url, json))
        step = self._steps.pop(0)
        if isinstance(step, Exception):
            raise step
        return step


def test_sender_success():
    client = _FakeClient(_FakeResponse(200, {"ok": True, "result": {"message_id": 1}}))
    sender = TelegramSender("tok-test", client=client)

    async def _run():
        return await sender.send_message("424242", "你好")
    ok, err = asyncio.run(_run())
    assert (ok, err) == (True, "")
    url, payload = client.calls[0]
    assert url == "https://api.telegram.org/bottok-test/sendMessage"
    assert payload == {"chat_id": "424242", "text": "你好"}


def test_sender_http_error():
    client = _FakeClient(_FakeResponse(401, {"ok": False, "description": "Unauthorized"}))
    sender = TelegramSender("tok-test", client=client)

    async def _run():
        return await sender.send_message("1", "hi")
    assert asyncio.run(_run()) == (False, "http 401")


def test_sender_api_ok_false():
    client = _FakeClient(_FakeResponse(200, {"ok": False, "description": "chat not found"}))
    sender = TelegramSender("tok-test", client=client)

    async def _run():
        return await sender.send_message("1", "hi")
    assert asyncio.run(_run()) == (False, "chat not found")


def test_sender_network_exception_not_raised():
    client = _FakeClient(OSError("connection refused"))
    sender = TelegramSender("tok-test", client=client)

    async def _run():
        return await sender.send_message("1", "hi")
    ok, err = asyncio.run(_run())
    assert ok is False
    assert "connection refused" in err, "网络异常 → (False, str(e)) 绝不上抛"


def test_sender_text_truncated_4000():
    client = _FakeClient(_FakeResponse(200, {"ok": True}))
    sender = TelegramSender("tok-test", client=client)

    async def _run():
        return await sender.send_message("1", "长" * 5000)
    ok, _ = asyncio.run(_run())
    assert ok is True
    assert len(client.calls[0][1]["text"]) == 4000, "发送文本必须截 4000"


# ====================================================================
# 4 · configured / secret_configured（env）
# ====================================================================

def test_configured_env_presence(monkeypatch):
    monkeypatch.delenv("FLIPPED_BOT_TELEGRAM_TOKEN", raising=False)
    assert configured() is False
    monkeypatch.setenv("FLIPPED_BOT_TELEGRAM_TOKEN", "tok-x")
    assert configured() is True
    monkeypatch.setenv("FLIPPED_BOT_TELEGRAM_TOKEN", "   ")
    assert configured() is False, "纯空白 token 视为未配置"


def test_secret_configured_default_and_value(monkeypatch):
    monkeypatch.delenv("FLIPPED_BOT_TELEGRAM_SECRET", raising=False)
    assert secret_configured() == ""
    monkeypatch.setenv("FLIPPED_BOT_TELEGRAM_SECRET", "s3cret")
    assert secret_configured() == "s3cret"
