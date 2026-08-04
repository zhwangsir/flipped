"""M182 · 企业微信 Bot Channel（B182 队）：应用回调 AES 加解密 + XML 解析 + 应用消息 sender。

协议（企业微信应用回调）：
- EncodingAESKey 43 字符 base64，key = b64decode(key + "=") 32 字节（AES-256-CBC），iv = key[:16]
- 明文 = random(16) + msg_len(4 字节网络序) + msg + corp_id，PKCS7 补齐
- 验签 sha1("".join(sorted([token, timestamp, nonce, encrypt]))) hexdigest 比对

pycryptodome 缺失时优雅降级：available()=False、configured()=False，绝不 import 即炸；
WeComCrypto 构造才 raise RuntimeError（给接线层一个明确信号）。
token/secret 全走 env（FLIPPED_BOT_WECOM_*），绝不硬编码；send_message 永不抛异常。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import struct
import time
import xml.etree.ElementTree as ET

from api.bot_channel import UnifiedMessage

try:
    from Crypto.Cipher import AES
    _AES_OK = True
except ImportError:  # pycryptodome 未装 → 全模块优雅降级
    AES = None
    _AES_OK = False

_API_BASE = "https://qyapi.weixin.qq.com"


def available() -> bool:
    """pycryptodome 可用性（False 时 wecom 通道整体降级为未配置）。"""
    return _AES_OK


class WeComCrypto:
    """企业微信回调加解密器：验签 + AES-256-CBC 加解密（corp_id 尾缀校验防伪）。"""

    def __init__(self, token: str, encoding_aes_key: str, corp_id: str):
        if not _AES_OK:
            raise RuntimeError("pycryptodome not installed")
        self._token = token
        self._key = base64.b64decode(encoding_aes_key + "=")  # 43 字符 + '=' → 32 字节
        self._corp_id = corp_id.encode("utf-8")

    def verify_signature(self, msg_signature: str, timestamp: str, nonce: str,
                         encrypt: str) -> bool:
        """URL/消息验签：sha1(sorted 拼接) hexdigest 与 msg_signature 常量时间比对。"""
        digest = hashlib.sha1(
            "".join(sorted([self._token, timestamp, nonce, encrypt])).encode("utf-8")
        ).hexdigest()
        return hmac.compare_digest(digest, msg_signature)

    def decrypt(self, encrypt_b64: str) -> str:
        """AES 解密 → 去 PKCS7 → 剥 random16/len 头 → corp_id 尾缀校验（不符 → ValueError）。"""
        cipher = AES.new(self._key, AES.MODE_CBC, self._key[:16])
        plain = cipher.decrypt(base64.b64decode(encrypt_b64))
        pad = plain[-1]
        plain = plain[:-pad]  # 去 PKCS7 尾
        msg_len = struct.unpack(">I", plain[16:20])[0]  # 4 字节网络序
        msg = plain[20:20 + msg_len]
        corp_id = plain[20 + msg_len:]
        if corp_id != self._corp_id:
            raise ValueError("corp_id mismatch")
        return msg.decode("utf-8")

    def encrypt(self, msg: str) -> str:
        """加密（测试与被动回复用）：random16+len+msg+corp_id → PKCS7 补齐 → AES → b64。"""
        msg_bytes = msg.encode("utf-8")
        plain = (os.urandom(16) + struct.pack(">I", len(msg_bytes))
                 + msg_bytes + self._corp_id)
        pad = 32 - len(plain) % 32
        plain += bytes([pad]) * pad
        cipher = AES.new(self._key, AES.MODE_CBC, self._key[:16])
        return base64.b64encode(cipher.encrypt(plain)).decode("utf-8")


def parse_callback_xml(xml_text: str) -> UnifiedMessage | None:
    """回调明文 XML → UnifiedMessage；非 text 消息/空 Content/畸形 XML → None。"""
    try:
        root = ET.fromstring(xml_text)
    except Exception:  # noqa: BLE001 畸形 XML 不炸
        return None
    if root is None or root.findtext("MsgType") != "text":
        return None
    content = root.findtext("Content")
    if not content:
        return None
    from_user = root.findtext("FromUserName") or ""
    return UnifiedMessage(
        platform="wecom",
        chat_id=from_user,
        user_id=from_user,
        user_name="",
        text=content,
        message_id=root.findtext("MsgId") or "",
    )


class WeComSender:
    """企业微信应用消息发送器：access_token 缓存（expires_in 提前 200s 刷新）。

    client 可注入 fake；返回值 (ok, err) 绝不上抛。
    """

    def __init__(self, corp_id: str, secret: str, agent_id: str, *, client=None):
        self._corp_id = corp_id
        self._secret = secret
        self._agent_id = agent_id
        self._client = client
        self._token: str | None = None
        self._token_expires_at: float = 0.0

    async def send_message(self, user_id: str, text: str) -> tuple[bool, str]:
        """发文本（截 2000）。errcode==0 → (True, "")；否则 (False, errmsg/异常)。"""
        try:
            if self._client is not None:
                return await self._send(self._client, user_id, text)
            import httpx  # 函数级 import：仅生产路径加载

            async with httpx.AsyncClient(timeout=15, trust_env=False) as client:
                return await self._send(client, user_id, text)
        except Exception as e:  # noqa: BLE001 网络/解析异常 → (False, str) 不上抛
            return (False, str(e) or type(e).__name__)  # 错误诊断信息绝不为空

    async def _send(self, client, user_id: str, text: str) -> tuple[bool, str]:
        token, err = await self._get_token(client)
        if token is None:
            return (False, err)
        resp = await client.post(
            f"{_API_BASE}/cgi-bin/message/send?access_token={token}",
            json={"touser": user_id, "msgtype": "text", "agentid": int(self._agent_id),
                  "text": {"content": text[:2000]}})
        if not (200 <= resp.status_code < 300):
            return (False, f"http {resp.status_code}")
        data = resp.json()
        if data.get("errcode") == 0:
            return (True, "")
        return (False, str(data.get("errmsg") or "unknown error"))

    async def _get_token(self, client) -> tuple[str | None, str]:
        """取 access_token：缓存未到期直接复用（提前 200s 刷新防边界过期）。"""
        if self._token is not None and time.time() < self._token_expires_at - 200:
            return (self._token, "")
        resp = await client.get(f"{_API_BASE}/cgi-bin/gettoken",
                                params={"corpid": self._corp_id, "corpsecret": self._secret})
        if not (200 <= resp.status_code < 300):
            return (None, f"http {resp.status_code}")
        data = resp.json()
        if data.get("errcode") not in (None, 0):
            return (None, str(data.get("errmsg") or "unknown error"))
        token = data.get("access_token")
        if not token:
            return (None, str(data.get("errmsg") or "no access_token"))
        self._token = token
        self._token_expires_at = time.time() + float(data.get("expires_in", 7200))
        return (token, "")


def configured() -> bool:
    """env 四件齐（TOKEN/AES_KEY/CORP_ID/SECRET 皆非空）且 pycryptodome 可用 → True。"""
    if not available():
        return False
    return all(os.environ.get(name, "").strip() for name in (
        "FLIPPED_BOT_WECOM_TOKEN", "FLIPPED_BOT_WECOM_AES_KEY",
        "FLIPPED_BOT_WECOM_CORP_ID", "FLIPPED_BOT_WECOM_SECRET"))


def agent_id() -> str:
    """env FLIPPED_BOT_WECOM_AGENT_ID，缺省 "0"。"""
    return os.environ.get("FLIPPED_BOT_WECOM_AGENT_ID", "0")
