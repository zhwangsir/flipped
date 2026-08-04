"""M181.1 · 移动远程控制 TDD 测试（B 队）。

纯逻辑（tmp_path 隔离，时钟经 now 注入）：
- RemoteRegistry：issue 字段+落盘、同 session 单活、resolve 未知/过期（purge+落盘）、
  revoke 幂等、持久化往返、坏 JSON/非 list 结构不炸
- detect_lan_ip：真实调用（不 mock），接受 127.0.0.1 回退
- qr_svg：真 segno 出 SVG；mobile_page_html：含 token 且零外部资源

端点（TestClient with 管理，FLIPPED_REMOTE_DB 指 tmp + 单例 reset，FLIPPED_TASKS=0 防
scheduler 干扰）：无会话 400 / 指定 404 / 缺省取最新 200 字段齐 / 显式 session +
回环 host_note / state 200 / state 无效 404 / message 转发（fake _run_chat 回显进
turns）/ decision 无 pending 409 透传 / 页面 200 含 token + 无效 404 失效页 /
qr.svg 内容类型 / DELETE 幂等且撤销后 state 404。

风格沿用 test_m178_tasks.py / test_m176_goal_api.py：同步测试函数 + TestClient
+ fake async，绝不碰真 LLM。
"""
from __future__ import annotations

import json
import time

import pytest
from fastapi.testclient import TestClient

from api.remote import RemoteRegistry, detect_lan_ip, mobile_page_html, qr_svg

# ====================================================================
# 1 · RemoteRegistry（纯逻辑，tmp 路径隔离）
# ====================================================================

def test_issue_token_fields_and_persisted(tmp_path):
    path = tmp_path / "remote_tokens.json"
    reg = RemoteRegistry(path, ttl_s=1800)
    tok = reg.issue("sess-a", now=1000.0)
    assert isinstance(tok.token, str) and len(tok.token) >= 24, "token_urlsafe(24) → 32 字符"
    assert tok.session_id == "sess-a"
    assert tok.created_at == 1000.0
    assert tok.expires_at == 1000.0 + 1800
    assert path.exists(), "issue 后必须落盘"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(data, list) and data[0]["token"] == tok.token


def test_issue_same_session_single_active(tmp_path):
    reg = RemoteRegistry(tmp_path / "remote_tokens.json")
    old = reg.issue("sess-a", now=1000.0)
    new = reg.issue("sess-a", now=1001.0)
    assert old.token != new.token
    assert reg.resolve(old.token, now=1002.0) is None, "同 session 重复签发 → 旧 token 失效（单活）"
    revived = reg.resolve(new.token, now=1002.0)
    assert revived is not None and revived.token == new.token


def test_resolve_unknown_token_returns_none(tmp_path):
    reg = RemoteRegistry(tmp_path / "remote_tokens.json")
    reg.issue("sess-a", now=1000.0)
    assert reg.resolve("tok-never-issued", now=1001.0) is None


def test_resolve_expired_purges_and_persists(tmp_path):
    path = tmp_path / "remote_tokens.json"
    reg = RemoteRegistry(path, ttl_s=100)
    tok = reg.issue("sess-a", now=1000.0)
    assert reg.resolve(tok.token, now=1000.0 + 101) is None, "过期 token → None"
    # 过期 purge 已落盘；再 issue 别的 token 后文件里不得有旧 token
    reg.issue("sess-b", now=2000.0)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert tok.token not in [t["token"] for t in data], "过期 token 必须被 purge 出持久化文件"


def test_revoke_existing_then_unknown(tmp_path):
    reg = RemoteRegistry(tmp_path / "remote_tokens.json")
    tok = reg.issue("sess-a", now=1000.0)
    assert reg.revoke(tok.token) is True
    assert reg.resolve(tok.token, now=1000.0) is None, "撤销后立即不可解析"
    assert reg.revoke(tok.token) is False, "重复撤销 → False"
    assert reg.revoke("tok-nope") is False


def test_persistence_roundtrip(tmp_path):
    path = tmp_path / "remote_tokens.json"
    reg = RemoteRegistry(path, ttl_s=1800)
    tok = reg.issue("sess-a", now=1000.0)
    reg2 = RemoteRegistry(path, ttl_s=1800)  # 全新实例从磁盘恢复
    tok2 = reg2.resolve(tok.token, now=1001.0)
    assert tok2 is not None
    assert tok2.session_id == "sess-a"
    assert tok2.created_at == tok.created_at and tok2.expires_at == tok.expires_at


def test_load_corrupt_json_returns_empty(tmp_path):
    path = tmp_path / "remote_tokens.json"
    path.write_text("{not json at all", encoding="utf-8")
    reg = RemoteRegistry(path)  # 坏文件不炸
    assert reg.resolve("tok-x", now=1.0) is None


def test_load_non_list_json_returns_empty(tmp_path):
    path = tmp_path / "remote_tokens.json"
    path.write_text('{"tokens": []}', encoding="utf-8")
    reg = RemoteRegistry(path)  # 结构非 list → 空注册表不炸
    assert reg.resolve("tok-x", now=1.0) is None


# ====================================================================
# 2 · detect_lan_ip / qr_svg / mobile_page_html（纯逻辑）
# ====================================================================

def test_detect_lan_ip_returns_nonempty_string():
    ip = detect_lan_ip()  # 真实调用不 mock；无网/沙箱 → 127.0.0.1 回退
    assert isinstance(ip, str) and ip, "必须返回非空字符串（允许回环回退）"


def test_qr_svg_returns_svg_string():
    svg = qr_svg("http://192.168.1.2:8011/remote/tok-abc")
    assert isinstance(svg, str)
    assert svg.startswith("<svg"), "segno xmldecl=False → 以 <svg 开头"


def test_mobile_page_html_self_contained_and_has_token():
    html = mobile_page_html("tok-AbC_123-x")
    assert "tok-AbC_123-x" in html, "token 必须渲入页面 JS 常量"
    assert "<script src" not in html, "零外部资源：不得引用外部 script"
    assert "<link" not in html, "零外部资源：不得引用外部样式表"
    assert 'name="viewport"' in html, "移动优先：viewport meta 必须存在"
    assert "innerHTML" not in html, "动态文本一律 textContent，禁 innerHTML"


# ====================================================================
# 3 · REST 端点（TestClient，注册表指 tmp 路径 + 单例 reset）
# ====================================================================

@pytest.fixture()
def remote_env(monkeypatch, tmp_path):
    """每测试独立远程注册表：FLIPPED_REMOTE_DB 指 tmp，单例 reset，关 scheduler。

    FLIPPED_SESSION_STORE_PATH 也指 tmp：全量回归时 conftest 的共享临时库文件
    会被先前测试的 shutdown save() 累积污染，lifespan load() 又并回内存，
    导致"无会话 400"拿到旧会话（同 test_api_mode_mcp.py 的隔离模式）。
    """
    monkeypatch.setenv("FLIPPED_REMOTE_DB", str(tmp_path / "remote_tokens.json"))
    monkeypatch.setenv("FLIPPED_SESSION_STORE_PATH", str(tmp_path / "sessions.json"))
    monkeypatch.setenv("FLIPPED_TASKS", "0")
    monkeypatch.delenv("FLIPPED_REMOTE_HOST", raising=False)
    monkeypatch.setattr("api.main._REMOTE_REGISTRY", None)
    return tmp_path


@pytest.fixture()
def client(remote_env):
    from api.main import app
    with TestClient(app, base_url="http://127.0.0.1:8011") as c:
        yield c


def _new_session(client: TestClient, title: str = "远程测试", mode: str = "chat") -> str:
    r = client.post("/api/v1/sessions", params={"title": title, "mode": mode})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _issue(client: TestClient, **body) -> dict:
    r = client.post("/api/v1/remote/sessions", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def test_issue_no_session_400(client):
    r = client.post("/api/v1/remote/sessions", json={})
    assert r.status_code == 400, r.text
    assert r.json()["detail"] == "no session available"


def test_issue_unknown_session_404(client):
    r = client.post("/api/v1/remote/sessions", json={"session_id": "sess-nope"})
    assert r.status_code == 404, r.text


def test_issue_defaults_to_latest_session(client, monkeypatch):
    monkeypatch.setenv("FLIPPED_REMOTE_HOST", "192.0.2.1")  # 固定 host，断言确定
    _new_session(client, title="旧会话")
    time.sleep(0.01)  # 防同微秒 created_at 字典序打平
    sid_new = _new_session(client, title="新会话")
    data = _issue(client)
    assert data["session_id"] == sid_new, "缺省必须取最新会话"
    assert data["session_title"] == "新会话"
    assert len(data["token"]) >= 24
    assert data["url"] == f"http://192.0.2.1:8011/remote/{data['token']}"
    assert data["qr_url"] == f"/api/v1/remote/{data['token']}/qr.svg"
    assert data["expires_at"] > time.time()
    assert data["host_note"] == "", "非回环 host 不带提示"


def test_issue_explicit_session_and_loopback_host_note(client, monkeypatch):
    monkeypatch.setenv("FLIPPED_REMOTE_HOST", "127.0.0.1")
    sid_old = _new_session(client, title="旧会话")
    time.sleep(0.01)
    _new_session(client, title="新会话")
    data = _issue(client, session_id=sid_old)
    assert data["session_id"] == sid_old, "显式指定优先于最新缺省"
    assert data["host_note"], "回环 host 必须带提示"
    assert "0.0.0.0" in data["host_note"] and "FLIPPED_REMOTE_HOST" in data["host_note"]


def test_state_valid_token_200(client):
    sid = _new_session(client)
    token = _issue(client, session_id=sid)["token"]
    r = client.get(f"/api/v1/remote/{token}/state")
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["session_id"] == sid and data["title"] == "远程测试"
    assert data["mode"] == "chat" and data["status"] == "idle"
    assert data["pending_approval"] is None
    assert data["turns"] == [], "新会话无 message 事件 → 空 turns"


def test_state_invalid_token_404(client):
    r = client.get("/api/v1/remote/tok-gone/state")
    assert r.status_code == 404, r.text
    assert r.json()["detail"] == "remote token invalid", "不区分未知/过期，无 oracle"


def test_message_forward_and_echo_in_turns(client, monkeypatch):
    from api.main import RUNNING_TASKS
    from api.schemas import EventType, Role

    async def _fake_chat(session_id, task_id, description, model_alias, mode):
        from api.main import bus
        bus.emit(session_id, EventType.message, Role.worker, {"text": "fake 助手回显"})

    monkeypatch.setattr("api.main._run_chat", _fake_chat)
    sid = _new_session(client)  # mode=chat → _run_chat 通路
    token = _issue(client, session_id=sid)["token"]

    r = client.post(f"/api/v1/remote/{token}/message", json={"text": "远程补充一句"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["session_id"] == sid and body["task_id"].startswith("task-")

    # 等后台 fake 协程跑完（轮询 RUNNING_TASKS 弹出，同 test_m176 模式）
    deadline = time.time() + 5
    while time.time() < deadline and RUNNING_TASKS.get(sid) is not None:
        time.sleep(0.01)
    assert RUNNING_TASKS.get(sid) is None, "fake _run_chat 未及时结束"

    r2 = client.get(f"/api/v1/remote/{token}/state")
    assert r2.status_code == 200, r2.text
    turns = [(t["role"], t["text"]) for t in r2.json()["turns"]]
    assert ("user", "远程补充一句") in turns, "远程消息必须以 user turn 落库"
    assert ("assistant", "fake 助手回显") in turns, "fake 助手回显必须出现在 turns"


def test_message_invalid_token_404(client):
    r = client.post("/api/v1/remote/tok-gone/message", json={"text": "hi"})
    assert r.status_code == 404, r.text


def test_decision_without_pending_approval_409(client):
    sid = _new_session(client)
    token = _issue(client, session_id=sid)["token"]
    r = client.post(f"/api/v1/remote/{token}/decision", json={"decision": "approve"})
    assert r.status_code == 409, f"无 pending approval_request → 409 透传自 _do_decision: {r.text}"


def test_decision_invalid_token_404(client):
    r = client.post("/api/v1/remote/tok-gone/decision", json={"decision": "reject"})
    assert r.status_code == 404, r.text


def test_page_valid_200_invalid_404(client):
    sid = _new_session(client)
    token = _issue(client, session_id=sid)["token"]
    r = client.get(f"/remote/{token}")
    assert r.status_code == 200, r.text
    assert "text/html" in r.headers["content-type"]
    assert token in r.text, "页面必须渲入 token"
    r2 = client.get("/remote/tok-gone")
    assert r2.status_code == 404, r2.text
    assert "链接已失效" in r2.text, "无效 token → 404 失效页"


def test_qr_svg_endpoint_200_svg(client):
    sid = _new_session(client)
    token = _issue(client, session_id=sid)["token"]
    r = client.get(f"/api/v1/remote/{token}/qr.svg")
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("image/svg+xml")
    assert r.text.startswith("<svg")
    assert client.get("/api/v1/remote/tok-gone/qr.svg").status_code == 404


def test_revoke_then_state_404_and_revoke_idempotent(client):
    sid = _new_session(client)
    token = _issue(client, session_id=sid)["token"]
    r = client.delete(f"/api/v1/remote/{token}")
    assert r.status_code == 200 and r.json() == {"ok": True}
    assert client.get(f"/api/v1/remote/{token}/state").status_code == 404, "撤销后 state 必须 404"
    r2 = client.delete(f"/api/v1/remote/{token}")
    assert r2.status_code == 200 and r2.json() == {"ok": True}, "重复 DELETE 幂等 200"
