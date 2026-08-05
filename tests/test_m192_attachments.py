"""M192.1 · 图像附件（chat/plan 多模态）后端 TDD 测试。

契约（PLAN.md M192，字段名一字不差）：
- SendMessageRequest.images: list[ImageAttachmentIn{name, media_type, data_base64}] | None
- 校验（images 非空时）：mode 仅 chat/plan；media_type 白名单 png/jpeg/webp/gif；
  张数 ≤ FLIPPED_IMG_MAX_COUNT(默认 4)；逐张 b64decode(validate=True) 且
  解码后 ≤ FLIPPED_IMG_MAX_BYTES(默认 2MB)，422 detail 含 name。
- 落盘 attachments_dir()/{session_id}/{uuid4.hex[:8]}{ext}；
  user message 事件 payload["attachments"] = [{name, media_type, path, bytes}]（不含 base64）。
- _run_chat(..., attachments=...)：vision 路由 + parts 组装（text + image_url data URL），
  读盘失败单张跳过，全部失败降级纯 str。
- resolve_vision_model_config()：proxy 健康且列模型 → proxy，否则 exo 直连；
  FLIPPED_VISION_MODEL env 覆盖。
- GET /api/v1/assistant/attachments/{session_id}/{filename}：200 字节一致；
  session 不存在 404；非法/穿越 filename 404。
- _events_to_turns：user turn 透传 attachments。

测试风格沿用 test_m175_refs_api.py / test_m166_token_stream.py：
同步测试函数 + TestClient + fake async _run_chat + httpx MockTransport。
"""
from __future__ import annotations

import base64
import json
import os
import sys

import httpx
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

# 1x1 红点 PNG（67 字节级小图，正常路径不触发大小闸）
_PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)
_PNG_B64 = base64.b64encode(_PNG_BYTES).decode("ascii")


def _img(name: str = "a.png", media_type: str = "image/png", data: str | None = None) -> dict:
    return {"name": name, "media_type": media_type,
            "data_base64": data if data is not None else _PNG_B64}


@pytest.fixture()
def client(monkeypatch, tmp_path):
    """隔离 DB + 隔离 FLIPPED_DATA_DIR（附件落盘到 tmp_path），返回 TestClient。"""
    monkeypatch.setenv("FLIPPED_MOCK_ORCHESTRATOR", "1")
    monkeypatch.setattr("api.main.FLIPPED_CHECKPOINT_DB", str(tmp_path / "cp.db"))
    monkeypatch.setenv("FLIPPED_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("FLIPPED_IMG_MAX_COUNT", raising=False)
    monkeypatch.delenv("FLIPPED_IMG_MAX_BYTES", raising=False)
    from api.main import app
    return TestClient(app)


def _new_session(client, mode: str = "chat") -> str:
    return client.post("/api/v1/assistant/sessions",
                       json={"title": "t", "mode": mode}).json()["id"]


def _send(client, sid: str, text: str, **extra):
    return client.post(f"/api/v1/assistant/sessions/{sid}/messages",
                       json={"text": text, **extra})


def _history(client, sid: str) -> list[dict]:
    r = client.get(f"/api/v1/assistant/sessions/{sid}/history")
    assert r.status_code == 200, r.text
    return r.json()


def _user_turns(turns: list[dict]) -> list[dict]:
    return [t for t in turns if t["role"] == "user"]


# ====================================================================
# 1 · 契约校验：media_type 非白名单 → 422
# ====================================================================

def test_media_type_not_whitelisted_422(client):
    sid = _new_session(client)
    r = _send(client, sid, "看图", images=[_img(media_type="image/svg+xml")])
    assert r.status_code == 422, r.text


# ====================================================================
# 2 · 契约校验：单张解码后超限 → 422 且 detail 含 name
# ====================================================================

def test_oversized_image_422_detail_contains_name(client, monkeypatch):
    monkeypatch.setenv("FLIPPED_IMG_MAX_BYTES", "4")  # PNG 解码后远超 4 字节
    sid = _new_session(client)
    r = _send(client, sid, "看图", images=[_img(name="big-cat.png")])
    assert r.status_code == 422, r.text
    assert "big-cat.png" in r.json()["detail"]


# ====================================================================
# 3 · 契约校验：第 5 张（> FLIPPED_IMG_MAX_COUNT 默认 4）→ 422
# ====================================================================

def test_fifth_image_422(client):
    sid = _new_session(client)
    r = _send(client, sid, "看图", images=[_img(name=f"{i}.png") for i in range(5)])
    assert r.status_code == 422, r.text


# ====================================================================
# 4 · 契约校验：agent/auto 带图 → 422「当前模式不支持图像附件（仅 chat/plan）」
# ====================================================================

def test_agent_mode_with_images_422(client):
    sid = _new_session(client, mode="agent")
    r = _send(client, sid, "看图", images=[_img()])
    assert r.status_code == 422, r.text
    assert "当前模式不支持图像附件（仅 chat/plan）" in r.json()["detail"]


def test_auto_mode_override_with_images_422(client):
    """chat 会话请求级 mode=auto 带图同样拒绝。"""
    sid = _new_session(client, mode="chat")
    r = _send(client, sid, "看图", mode="auto", images=[_img()])
    assert r.status_code == 422, r.text
    assert "当前模式不支持图像附件（仅 chat/plan）" in r.json()["detail"]


# ====================================================================
# 5 · 契约校验：非法 base64 → 422（detail 含 name）
# ====================================================================

def test_invalid_base64_422(client):
    sid = _new_session(client)
    r = _send(client, sid, "看图", images=[_img(name="bad.png", data="!!!not-base64!!!")])
    assert r.status_code == 422, r.text
    assert "bad.png" in r.json()["detail"]


# ====================================================================
# 6 · 落盘 + payload 元数据 + _run_chat 透传
# ====================================================================

def test_upload_persists_disk_and_payload_metadata(client, monkeypatch, tmp_path):
    sid = _new_session(client)
    called: dict = {}

    async def _fake_chat(session_id, task_id, description, model_alias, mode, **kwargs):
        called["attachments"] = kwargs.get("attachments")

    monkeypatch.setattr("api.main._run_chat", _fake_chat)
    r = _send(client, sid, "看图", images=[_img(name="x.png"), _img(name="y.png")])
    assert r.status_code == 200, r.text

    # _run_chat 透传 attachments
    atts = called["attachments"]
    assert isinstance(atts, list) and len(atts) == 2

    # user message 事件 payload 元数据（history turn 视图）
    users = _user_turns(_history(client, sid))
    assert len(users) == 1
    turn_atts = users[0]["attachments"]
    assert len(turn_atts) == 2
    for att, expect_name in zip(turn_atts, ["x.png", "y.png"]):
        assert att["name"] == expect_name
        assert att["media_type"] == "image/png"
        assert att["bytes"] == len(_PNG_BYTES)
        assert att["path"].startswith(f"{sid}/"), "path 形如 {session_id}/{fname}"
        assert "data_base64" not in att and "base64" not in att, "payload 不得含 base64"

    # 落盘字节一致
    data_dir = tmp_path / "data" / "attachments"
    for att in turn_atts:
        fpath = data_dir / att["path"]
        assert fpath.is_file(), f"落盘文件不存在: {fpath}"
        assert fpath.read_bytes() == _PNG_BYTES


def test_no_images_keeps_legacy_call_shape(client, monkeypatch):
    """无图消息：_run_chat 不收到 attachments kw（现状 str 路径零变化）。"""
    sid = _new_session(client)
    called: dict = {}

    async def _fake_chat(session_id, task_id, description, model_alias, mode, **kwargs):
        called.update(kwargs)

    monkeypatch.setattr("api.main._run_chat", _fake_chat)
    r = _send(client, sid, "普通消息")
    assert r.status_code == 200, r.text
    assert "attachments" not in called
    users = _user_turns(_history(client, sid))
    assert users[0]["attachments"] is None


# ====================================================================
# 7 · _run_chat parts 组装（mock httpx 断言 messages payload）
# ====================================================================

def _patch_httpx_capture(monkeypatch, captured: dict):
    """httpx.AsyncClient 注入 MockTransport，捕获 chat/completions 请求体。"""
    def _handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content.decode())
        return httpx.Response(200, json={
            "choices": [{"message": {"content": "看到了"}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1},
        })

    transport = httpx.MockTransport(_handler)
    real_client = httpx.AsyncClient

    def _factory(*args, **kwargs):
        kwargs["transport"] = transport
        return real_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", _factory)


def _write_attachment(tmp_path, sid: str, fname: str, raw: bytes = _PNG_BYTES) -> dict:
    """在 FLIPPED_DATA_DIR 下落盘一张附件，返回 payload 元数据 dict。"""
    p = tmp_path / "data" / "attachments" / sid
    p.mkdir(parents=True, exist_ok=True)
    (p / fname).write_bytes(raw)
    return {"name": fname, "media_type": "image/png",
            "path": f"{sid}/{fname}", "bytes": len(raw)}


def test_run_chat_builds_multimodal_parts(monkeypatch, tmp_path):
    """attachments 非空：vision 路由 + user content = [text, image_url, image_url]。"""
    import asyncio

    import api.main as main

    monkeypatch.setenv("FLIPPED_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("FLIPPED_CHAT_STREAM", "0")

    def _no_worker(alias="coder"):
        raise AssertionError("带图消息不得走 worker 路由")

    monkeypatch.setattr("driving.model_router.resolve_worker_model_config", _no_worker)
    monkeypatch.setattr(
        "driving.model_router.resolve_vision_model_config",
        lambda: ("http://vision.test/v1", "vision-4bit"),
    )
    captured: dict = {}
    _patch_httpx_capture(monkeypatch, captured)

    sid = main.store.create("m192-parts", mode="chat").id
    atts = [_write_attachment(tmp_path, sid, "aa11bb22.png"),
            _write_attachment(tmp_path, sid, "cc33dd44.png")]
    asyncio.run(main._run_chat(sid, "task-1", "看图说话", "coder", "chat",
                               rag_auto=False, map_auto=False, rules_auto=False,
                               attachments=atts))

    body = captured["body"]
    assert body["model"] == "vision-4bit", "带图消息必须走 vision model"
    content = body["messages"][1]["content"]
    assert isinstance(content, list), "user content 必须是 parts 数组"
    assert content[0] == {"type": "text", "text": "看图说话"}
    assert [p["type"] for p in content[1:]] == ["image_url", "image_url"]
    for part in content[1:]:
        url = part["image_url"]["url"]
        assert url.startswith("data:image/png;base64,"), "data URL 头正确"
        raw = base64.b64decode(url.split(",", 1)[1])
        assert raw == _PNG_BYTES


def test_run_chat_all_reads_fail_degrade_to_plain_str(monkeypatch, tmp_path):
    """全部读盘失败 → 纯 str 发送（降级不炸），仍走 vision 路由。"""
    import asyncio

    import api.main as main

    monkeypatch.setenv("FLIPPED_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("FLIPPED_CHAT_STREAM", "0")
    monkeypatch.setattr(
        "driving.model_router.resolve_vision_model_config",
        lambda: ("http://vision.test/v1", "vision-4bit"),
    )
    captured: dict = {}
    _patch_httpx_capture(monkeypatch, captured)

    sid = main.store.create("m192-degrade", mode="chat").id
    # 不落盘 → 读盘必失败
    atts = [{"name": "ghost.png", "media_type": "image/png",
             "path": f"{sid}/deadbeef.png", "bytes": 1}]
    asyncio.run(main._run_chat(sid, "task-1", "看图说话", "coder", "chat",
                               rag_auto=False, map_auto=False, rules_auto=False,
                               attachments=atts))

    body = captured["body"]
    assert body["model"] == "vision-4bit"
    assert body["messages"][1]["content"] == "看图说话", "全部失败必须降级为纯 str"


def test_run_chat_partial_read_failure_skips_single(monkeypatch, tmp_path):
    """单张读盘失败跳过（fail-open），其余正常组装。"""
    import asyncio

    import api.main as main

    monkeypatch.setenv("FLIPPED_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("FLIPPED_CHAT_STREAM", "0")
    monkeypatch.setattr(
        "driving.model_router.resolve_vision_model_config",
        lambda: ("http://vision.test/v1", "vision-4bit"),
    )
    captured: dict = {}
    _patch_httpx_capture(monkeypatch, captured)

    sid = main.store.create("m192-partial", mode="chat").id
    ok = _write_attachment(tmp_path, sid, "ok123456.png")
    ghost = {"name": "ghost.png", "media_type": "image/png",
             "path": f"{sid}/deadbeef.png", "bytes": 1}
    asyncio.run(main._run_chat(sid, "task-1", "看图", "coder", "chat",
                               rag_auto=False, map_auto=False, rules_auto=False,
                               attachments=[ok, ghost]))

    content = captured["body"]["messages"][1]["content"]
    assert isinstance(content, list)
    assert [p["type"] for p in content] == ["text", "image_url"], "失败单张跳过"


# ====================================================================
# 8 · vision 路由：resolve_vision_model_config
# ====================================================================

@pytest.fixture()
def _clean_vision_env(monkeypatch):
    monkeypatch.delenv("FLIPPED_VISION_MODEL", raising=False)
    monkeypatch.delenv("LITELLM_BASE_URL", raising=False)
    monkeypatch.delenv("FLIPPED_MODEL_BASE_URL", raising=False)


def test_vision_router_prefers_proxy_when_healthy(_clean_vision_env, monkeypatch):
    from driving import model_router

    monkeypatch.setattr(model_router, "is_endpoint_healthy", lambda url: True)
    monkeypatch.setattr(model_router, "is_model_available", lambda url, model: True)
    base, model = model_router.resolve_vision_model_config()
    assert base == model_router.DEFAULT_PROXY_URL
    assert model == "mlx-community/Qwen3-VL-4B-Instruct-4bit"


def test_vision_router_falls_back_to_exo_direct(_clean_vision_env, monkeypatch):
    from driving import model_router

    monkeypatch.setattr(model_router, "is_endpoint_healthy", lambda url: False)
    monkeypatch.setattr(model_router, "is_model_available", lambda url, model: False)
    base, model = model_router.resolve_vision_model_config()
    assert base == model_router.DEFAULT_EXO_URL
    assert model == "mlx-community/Qwen3-VL-4B-Instruct-4bit"


def test_vision_router_model_not_listed_falls_back(_clean_vision_env, monkeypatch):
    """proxy 健康但未列出 vision model → exo 直连。"""
    from driving import model_router

    monkeypatch.setattr(model_router, "is_endpoint_healthy", lambda url: True)
    monkeypatch.setattr(model_router, "is_model_available", lambda url, model: False)
    base, _model = model_router.resolve_vision_model_config()
    assert base == model_router.DEFAULT_EXO_URL


def test_vision_router_env_overrides(_clean_vision_env, monkeypatch):
    from driving import model_router

    monkeypatch.setenv("FLIPPED_VISION_MODEL", "mlx-community/Kimi-K2.6-4bit")
    monkeypatch.setenv("FLIPPED_MODEL_BASE_URL", "http://exo-custom:52415/v1")
    monkeypatch.setenv("LITELLM_BASE_URL", "http://proxy-custom:4000/v1")
    # proxy 分支：env 覆盖的 proxy URL + env 覆盖的 model
    monkeypatch.setattr(model_router, "is_endpoint_healthy", lambda url: True)
    monkeypatch.setattr(model_router, "is_model_available", lambda url, model: True)
    base, model = model_router.resolve_vision_model_config()
    assert base == "http://proxy-custom:4000/v1"
    assert model == "mlx-community/Kimi-K2.6-4bit"
    # exo 分支：env 覆盖的 direct URL + env 覆盖的 model
    monkeypatch.setattr(model_router, "is_endpoint_healthy", lambda url: False)
    base, model = model_router.resolve_vision_model_config()
    assert base == "http://exo-custom:52415/v1"
    assert model == "mlx-community/Kimi-K2.6-4bit"


# ====================================================================
# 9 · GET attachments 端点：200 / 404 / 防穿越
# ====================================================================

def _upload_one(client, monkeypatch, sid: str, name: str = "x.png") -> str:
    """发一张图，返回落盘 basename。"""
    async def _fake_chat(*args, **kwargs):
        return None

    monkeypatch.setattr("api.main._run_chat", _fake_chat)
    r = _send(client, sid, "看图", images=[_img(name=name)])
    assert r.status_code == 200, r.text
    users = _user_turns(_history(client, sid))
    path = users[0]["attachments"][0]["path"]
    return path.split("/", 1)[1]


def test_attachment_endpoint_200_bytes_equal(client, monkeypatch):
    sid = _new_session(client)
    fname = _upload_one(client, monkeypatch, sid)
    r = client.get(f"/api/v1/assistant/attachments/{sid}/{fname}")
    assert r.status_code == 200, r.text
    assert r.content == _PNG_BYTES
    assert r.headers["content-type"].startswith("image/png")


def test_attachment_endpoint_session_not_found_404(client, monkeypatch, tmp_path):
    r = client.get("/api/v1/assistant/attachments/no-such-session/x.png")
    assert r.status_code == 404


def test_attachment_endpoint_traversal_404(client, monkeypatch):
    """../ 穿越与非法字符一律 404（正则 + resolve 双闸）。"""
    sid = _new_session(client)
    _upload_one(client, monkeypatch, sid)
    # ".." 命中正则（点是合法字符）但 resolve 后逸出会话目录 → 404
    assert client.get(f"/api/v1/assistant/attachments/{sid}/..").status_code == 404
    # 非法字符（空格）→ 正则不匹配 → 404
    assert client.get(f"/api/v1/assistant/attachments/{sid}/evil%20file.png").status_code == 404
    # 斜杠穿越段 → 路由/正则均不接受 → 404
    assert client.get(f"/api/v1/assistant/attachments/{sid}/..%2Fsecret.png").status_code == 404
    # 会话内不存在文件 → 404
    assert client.get(f"/api/v1/assistant/attachments/{sid}/missing.png").status_code == 404


# ====================================================================
# 10 · _events_to_turns 透传 attachments
# ====================================================================

def test_events_to_turns_carries_attachments():
    from api.assistant import _events_to_turns
    from api.schemas import Event, EventType, Role

    atts = [{"name": "x.png", "media_type": "image/png", "path": "s/abcd1234.png", "bytes": 7}]
    evs = [
        Event(id="e-1", session_id="s", type=EventType.message,
              agent=Role.user, payload={"text": "看图", "attachments": atts}),
        Event(id="e-2", session_id="s", type=EventType.message,
              agent=Role.worker, payload={"text": "看到了"}),
    ]
    turns = _events_to_turns(evs)
    assert turns[0].role == "user"
    assert turns[0].attachments == atts
    assert turns[1].role == "assistant"
    assert turns[1].attachments is None
