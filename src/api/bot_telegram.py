"""M182 · Telegram Bot Channel（B182 队）：webhook 验签 + update 解析 + sendMessage sender。

token/secret 全走 env（FLIPPED_BOT_TELEGRAM_TOKEN / FLIPPED_BOT_TELEGRAM_SECRET），
绝不硬编码；生产路径 httpx.AsyncClient(timeout=15, trust_env=False)（内网代理教训），
测试经 client 参数注入 fake，绝不碰真网络。send_message 永不抛异常。
"""
from __future__ import annotations

import hmac
import os

from api.bot_channel import UnifiedMessage

_API_BASE = "https://api.telegram.org"


def verify_secret(header: str | None, expected: str) -> bool:
    """校验 X-Telegram-Bot-Api-Secret-Token 头：expected 空 → 一律 False（无 oracle）。"""
    if not expected or header is None:
        return False
    return hmac.compare_digest(header, expected)


def parse_update(body: dict) -> UnifiedMessage | None:
    """Telegram webhook JSON → UnifiedMessage；非文本/无 message/结构漂移 → None。

    只看 body["message"]（edited_message / channel_post 等一律忽略）；
    message.text 必填（非 str 或空串 → None）；数字 id 统一 str 化。
    """
    if not isinstance(body, dict):
        return None
    message = body.get("message")
    if not isinstance(message, dict):
        return None
    text = message.get("text")
    if not isinstance(text, str) or not text:
        return None
    chat = message.get("chat") or {}
    sender = message.get("from") or {}
    return UnifiedMessage(
        platform="telegram",
        chat_id=str(chat.get("id", "")),
        user_id=str(sender.get("id", "")),
        user_name=sender.get("username") or sender.get("first_name") or "",
        text=text,
        message_id=str(message.get("message_id", "")),
    )


class TelegramSender:
    """Telegram sendMessage 发送器：client 可注入 fake；返回值 (ok, err) 绝不上抛。"""

    def __init__(self, token: str, *, client=None):
        self._token = token
        self._client = client

    async def send_message(self, chat_id: str, text: str) -> tuple[bool, str]:
        """发文本（截 4000）。2xx 且 ok=true → (True, "")；否则 (False, 原因)。"""
        url = f"{_API_BASE}/bot{self._token}/sendMessage"
        payload = {"chat_id": chat_id, "text": text[:4000]}
        try:
            if self._client is not None:
                return await self._post(self._client, url, payload)
            import httpx  # 函数级 import：纯逻辑模块保持轻量，仅生产路径加载

            async with httpx.AsyncClient(timeout=15, trust_env=False) as client:
                return await self._post(client, url, payload)
        except Exception as e:  # noqa: BLE001 网络/解析异常 → (False, str) 不上抛
            return (False, str(e) or type(e).__name__)  # 错误诊断信息绝不为空

    @staticmethod
    async def _post(client, url: str, payload: dict) -> tuple[bool, str]:
        resp = await client.post(url, json=payload)
        if not (200 <= resp.status_code < 300):
            return (False, f"http {resp.status_code}")
        data = resp.json()
        if data.get("ok"):
            return (True, "")
        return (False, str(data.get("description") or "unknown error"))


def configured() -> bool:
    """env FLIPPED_BOT_TELEGRAM_TOKEN 非空（去空白）→ True。"""
    return bool(os.environ.get("FLIPPED_BOT_TELEGRAM_TOKEN", "").strip())


def secret_configured() -> str:
    """env FLIPPED_BOT_TELEGRAM_SECRET 缺省 ""（空 → webhook 验签一律拒绝）。"""
    return os.environ.get("FLIPPED_BOT_TELEGRAM_SECRET", "")
