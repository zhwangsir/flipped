"""M182 · 企业微信 Bot Channel TDD 测试（B182 队）。

- WeComCrypto：key 派生 32 字节 / verify_signature 固定测试向量（硬编码 sha1，不镜像实现）
  / encrypt→decrypt 往返（含中文）/ corp_id 尾缀篡改 → ValueError
- parse_callback_xml：text 正常 / 非 text（event）→ None / 空 Content → None /
  缺 MsgId → "" / 畸形 XML → None
- WeComSender（fake client 注入，绝不碰真网络）：gettoken→send 成功 /
  gettoken errcode 非 0 / send errcode 非 0 / token 缓存（第二次 send 不再 gettoken）/
  网络异常 (False, str) 不上抛 / text 截 2000
- configured()：env 四件缺一 → False；agent_id() 缺省 "0"

EncodingAESKey 用 43 字符固定值（b64decode(key + "=") → 32 字节），协议自测。
"""
from __future__ import annotations

import asyncio

import pytest

from api import bot_wecom
from api.bot_wecom import (
    WeComCrypto,
    WeComSender,
    agent_id,
    available,
    configured,
    parse_callback_xml,
)

pytestmark = pytest.mark.skipif(not available(), reason="pycryptodome not installed")

_TOKEN = "tok123"
_AES_KEY = "abcdefghijklmnopqrstuvwxyz0123456789ABCDEFG"  # 43 字符 base64 → 32 字节
_CORP_ID = "corp-abc-123"


def _crypto(corp_id=_CORP_ID):
    return WeComCrypto(_TOKEN, _AES_KEY, corp_id)


# ====================================================================
# 1 · WeComCrypto
# ====================================================================

def test_available_true_with_pycryptodome():
    assert bot_wecom.available() is True, "本 venv 已装 pycryptodome，必须可用"


def test_crypto_key_derived_32_bytes():
    c = _crypto()
    assert len(c._key) == 32, "b64decode(aes_key + '=') 必须 32 字节（AES-256）"


def test_verify_signature_fixed_vector():
    c = _crypto()
    # 预计算向量：sha1("1700000000ENCTEXTn123tok123")，sorted 拼接，非镜像实现
    assert c.verify_signature(
        "9808024636ffa1a6113191809a4880090b870b46",
        "1700000000", "n123", "ENCTEXT") is True


def test_verify_signature_mismatch():
    c = _crypto()
    assert c.verify_signature("0" * 40, "1700000000", "n123", "ENCTEXT") is False
    assert c.verify_signature(
        "9808024636ffa1a6113191809a4880090b870b46",
        "1700000001", "n123", "ENCTEXT") is False, "timestamp 改动 → 验签失败"


def test_encrypt_decrypt_roundtrip_with_chinese():
    c = _crypto()
    cipher = c.encrypt("你好企业微信，任务已完成 ✅")
    assert isinstance(cipher, str) and cipher
    assert c.decrypt(cipher) == "你好企业微信，任务已完成 ✅"


def test_decrypt_corp_id_tampered_raises():
    cipher = _crypto().encrypt("secret msg")
    with pytest.raises(ValueError):
        _crypto(corp_id="corp-evil").decrypt(cipher), "corp_id 尾缀不符 → ValueError"


# ====================================================================
# 2 · parse_callback_xml
# ====================================================================

_XML = """<xml>
<ToUserName><![CDATA[corp-abc-123]]></ToUserName>
<FromUserName><![CDATA[user42]]></FromUserName>
<CreateTime>1700000000</CreateTime>
<MsgType><![CDATA[text]]></MsgType>
<Content><![CDATA[你好企业微信]]></Content>
<MsgId>1234567890</MsgId>
<AgentID>1</AgentID>
</xml>"""


def test_parse_callback_xml_text_message():
    msg = parse_callback_xml(_XML)
    assert msg is not None
    assert msg.platform == "wecom"
    assert msg.chat_id == "user42", "chat_id = FromUserName"
    assert msg.user_id == "user42"
    assert msg.user_name == "", "企业微信回调无用户名 → 空串"
    assert msg.text == "你好企业微信"
    assert msg.message_id == "1234567890"


def test_parse_callback_xml_non_text_returns_none():
    event_xml = _XML.replace("<MsgType><![CDATA[text]]></MsgType>",
                             "<MsgType><![CDATA[event]]></MsgType>")
    assert parse_callback_xml(event_xml) is None, "event 消息不处理"


def test_parse_callback_xml_empty_content_returns_none():
    empty = _XML.replace("<Content><![CDATA[你好企业微信]]></Content>",
                         "<Content><![CDATA[]]></Content>")
    assert parse_callback_xml(empty) is None, "空 Content → None"
    no_content = _XML.replace("<Content><![CDATA[你好企业微信]]></Content>\n", "")
    assert parse_callback_xml(no_content) is None, "缺 Content → None"


def test_parse_callback_xml_missing_msgid_defaults_empty():
    no_id = _XML.replace("<MsgId>1234567890</MsgId>\n", "")
    msg = parse_callback_xml(no_id)
    assert msg is not None and msg.message_id == "", "MsgId 缺省 → 空串"


def test_parse_callback_xml_malformed_returns_none():
    assert parse_callback_xml("<xml><broken") is None, "畸形 XML → None 不上抛"
    assert parse_callback_xml("") is None
    assert parse_callback_xml("not xml at all") is None


# ====================================================================
# 3 · WeComSender（fake client 注入）
# ====================================================================

class _FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}

    def json(self):
        return self._payload


def _token_ok(token="token-1"):
    return _FakeResponse(200, {"errcode": 0, "access_token": token, "expires_in": 7200})


def _send_ok():
    return _FakeResponse(200, {"errcode": 0, "errmsg": "ok"})


class _FakeClient:
    """模拟注入的 httpx.AsyncClient：get/post 分队列返回，记录全部调用。"""

    def __init__(self, get_steps=(), post_steps=()):
        self._get_steps = list(get_steps)
        self._post_steps = list(post_steps)
        self.get_calls = []
        self.post_calls = []

    async def get(self, url, params=None):
        self.get_calls.append((url, params))
        step = self._get_steps.pop(0)
        if isinstance(step, Exception):
            raise step
        return step

    async def post(self, url, json=None):
        self.post_calls.append((url, json))
        step = self._post_steps.pop(0)
        if isinstance(step, Exception):
            raise step
        return step


def test_sender_gettoken_then_send_success():
    client = _FakeClient(get_steps=[_token_ok()], post_steps=[_send_ok()])
    sender = WeComSender("corp-abc-123", "secret-x", "1", client=client)

    async def _run():
        return await sender.send_message("user42", "你好")
    assert asyncio.run(_run()) == (True, "")
    g_url, g_params = client.get_calls[0]
    assert g_url == "https://qyapi.weixin.qq.com/cgi-bin/gettoken"
    assert g_params == {"corpid": "corp-abc-123", "corpsecret": "secret-x"}
    p_url, p_json = client.post_calls[0]
    assert p_url == ("https://qyapi.weixin.qq.com/cgi-bin/message/send"
                     "?access_token=token-1")
    assert p_json == {"touser": "user42", "msgtype": "text", "agentid": 1,
                      "text": {"content": "你好"}}


def test_sender_gettoken_errcode_nonzero():
    client = _FakeClient(get_steps=[
        _FakeResponse(200, {"errcode": 40001, "errmsg": "invalid credential"})])
    sender = WeComSender("corp-abc-123", "secret-x", "1", client=client)

    async def _run():
        return await sender.send_message("user42", "hi")
    assert asyncio.run(_run()) == (False, "invalid credential")
    assert client.post_calls == [], "取 token 失败不得继续 send"


def test_sender_send_errcode_nonzero():
    client = _FakeClient(
        get_steps=[_token_ok()],
        post_steps=[_FakeResponse(200, {"errcode": 60011, "errmsg": "no privilege"})])
    sender = WeComSender("corp-abc-123", "secret-x", "1", client=client)

    async def _run():
        return await sender.send_message("user42", "hi")
    assert asyncio.run(_run()) == (False, "no privilege")


def test_sender_token_cached_across_sends():
    client = _FakeClient(get_steps=[_token_ok()],
                         post_steps=[_send_ok(), _send_ok()])
    sender = WeComSender("corp-abc-123", "secret-x", "1", client=client)

    async def _run():
        r1 = await sender.send_message("user42", "第一条")
        r2 = await sender.send_message("user42", "第二条")
        return r1, r2
    r1, r2 = asyncio.run(_run())
    assert r1 == (True, "") and r2 == (True, "")
    assert len(client.get_calls) == 1, "token 缓存：第二次 send 不得再调 gettoken"
    assert len(client.post_calls) == 2


def test_sender_network_exception_not_raised():
    client = _FakeClient(get_steps=[OSError("dns failure")])
    sender = WeComSender("corp-abc-123", "secret-x", "1", client=client)

    async def _run():
        return await sender.send_message("user42", "hi")
    ok, err = asyncio.run(_run())
    assert ok is False and "dns failure" in err, "网络异常 → (False, str(e)) 不上抛"


def test_sender_text_truncated_2000():
    client = _FakeClient(get_steps=[_token_ok()], post_steps=[_send_ok()])
    sender = WeComSender("corp-abc-123", "secret-x", "1", client=client)

    async def _run():
        return await sender.send_message("user42", "长" * 3000)
    ok, _ = asyncio.run(_run())
    assert ok is True
    assert len(client.post_calls[0][1]["text"]["content"]) == 2000, "企业微信文本截 2000"


# ====================================================================
# 4 · configured / agent_id（env）
# ====================================================================

_WECOM_ENV = ("FLIPPED_BOT_WECOM_TOKEN", "FLIPPED_BOT_WECOM_AES_KEY",
              "FLIPPED_BOT_WECOM_CORP_ID", "FLIPPED_BOT_WECOM_SECRET")


def _set_all_wecom_env(monkeypatch):
    monkeypatch.setenv("FLIPPED_BOT_WECOM_TOKEN", "t")
    monkeypatch.setenv("FLIPPED_BOT_WECOM_AES_KEY", "k")
    monkeypatch.setenv("FLIPPED_BOT_WECOM_CORP_ID", "c")
    monkeypatch.setenv("FLIPPED_BOT_WECOM_SECRET", "s")


def test_configured_requires_all_four_envs(monkeypatch):
    for name in _WECOM_ENV:
        monkeypatch.delenv(name, raising=False)
    assert configured() is False
    _set_all_wecom_env(monkeypatch)
    assert configured() is True
    monkeypatch.delenv("FLIPPED_BOT_WECOM_SECRET")
    assert configured() is False, "四件缺一件 → False"


def test_agent_id_default_and_override(monkeypatch):
    monkeypatch.delenv("FLIPPED_BOT_WECOM_AGENT_ID", raising=False)
    assert agent_id() == "0"
    monkeypatch.setenv("FLIPPED_BOT_WECOM_AGENT_ID", "1000002")
    assert agent_id() == "1000002"
