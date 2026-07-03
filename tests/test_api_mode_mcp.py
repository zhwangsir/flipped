"""M7.3/M7.4 — MCP 端点 + 模式路由（对话/规划）后端集成测试。"""
import time

from fastapi.testclient import TestClient

import api.main as main
from api.main import API_PREFIX, app


def _new_session(c: TestClient, title: str = "t") -> str:
    return c.post(f"{API_PREFIX}/sessions", params={"title": title}).json()["id"]


# ---------- M7.3 MCP 端点 ----------

def test_mcp_servers_list(monkeypatch, tmp_path):
    monkeypatch.setenv("FLIPPED_MCP_CONFIG_PATH", str(tmp_path / "m.json"))
    with TestClient(app) as c:
        r = c.get(f"{API_PREFIX}/mcp/servers")
        assert r.status_code == 200
        servers = r.json()
        names = {s["name"] for s in servers}
        assert "flipped" in names
        flipped = next(s for s in servers if s["name"] == "flipped")
        assert "web_search" in flipped["tools"]
        assert all(s["enabled"] is False for s in servers)


def test_mcp_toggle_and_persist(monkeypatch, tmp_path):
    monkeypatch.setenv("FLIPPED_MCP_CONFIG_PATH", str(tmp_path / "m.json"))
    with TestClient(app) as c:
        r = c.post(f"{API_PREFIX}/mcp/servers/filesystem/toggle", params={"enabled": True})
        assert r.status_code == 200
        assert r.json()["enabled"] is True
        servers = c.get(f"{API_PREFIX}/mcp/servers").json()
        assert next(s["enabled"] for s in servers if s["name"] == "filesystem") is True


def test_mcp_toggle_unknown_404(monkeypatch, tmp_path):
    monkeypatch.setenv("FLIPPED_MCP_CONFIG_PATH", str(tmp_path / "m.json"))
    with TestClient(app) as c:
        r = c.post(f"{API_PREFIX}/mcp/servers/nope/toggle", params={"enabled": True})
        assert r.status_code == 404


# ---------- Stage 3 项目上下文 ----------

def test_project_context():
    """/project/context 返回项目名 + git 分支 + 模式（供 composer 上下文行/状态栏）。"""
    with TestClient(app) as c:
        r = c.get(f"{API_PREFIX}/project/context")
        assert r.status_code == 200
        data = r.json()
        assert set(data) >= {"project", "branch", "mode"}
        assert data["project"]  # 非空项目名
        assert data["mode"] == "本地模式"


# ---------- 阶段② 项目文件树 / 单文件读取 ----------

def test_project_files_tree():
    """/project/files 返回文件树，跳过依赖/构建产物。"""
    with TestClient(app) as c:
        r = c.get(f"{API_PREFIX}/project/files")
        assert r.status_code == 200
        data = r.json()
        assert data["root"]
        assert isinstance(data["tree"], list) and data["tree"]
        blob = str(data["tree"])
        assert "node_modules" not in blob  # 被忽略
        # 顶层应含已知目录
        top = {n["name"] for n in data["tree"]}
        assert "src" in top or "console" in top


def test_project_file_read():
    """/project/file 读取仓库内文本文件，返回内容。"""
    with TestClient(app) as c:
        r = c.get(f"{API_PREFIX}/project/file", params={"path": "STATE.json"})
        assert r.status_code == 200
        assert r.json()["content"].lstrip().startswith("{")


def test_project_file_traversal_blocked():
    """路径穿越必须被拒（403）。"""
    with TestClient(app) as c:
        r = c.get(f"{API_PREFIX}/project/file", params={"path": "../../../../etc/passwd"})
        assert r.status_code == 403


def test_project_file_not_found():
    """不存在的路径 → 404。"""
    with TestClient(app) as c:
        r = c.get(f"{API_PREFIX}/project/file", params={"path": "no/such/file.xyz"})
        assert r.status_code == 404


# ---------- 阶段① Session mode 字段（项目/对话分区） ----------

def test_session_mode_field(monkeypatch, tmp_path):
    """create_session 的 mode 落库并回传（chat→对话区, 默认 agent）。"""
    monkeypatch.setenv("FLIPPED_SESSION_STORE_PATH", str(tmp_path / "s.json"))
    with TestClient(app) as c:
        chat = c.post(f"{API_PREFIX}/sessions", params={"title": "c", "mode": "chat"}).json()
        assert chat["mode"] == "chat"
        default = c.post(f"{API_PREFIX}/sessions", params={"title": "d"}).json()
        assert default["mode"] == "agent"


# ---------- 阶段②b 浏览器渲染（URL 校验，不启浏览器） ----------

def test_browser_render_rejects_non_http():
    """非 http/https scheme → 400（在启浏览器之前就拒）。"""
    with TestClient(app) as c:
        r = c.post(f"{API_PREFIX}/browser/render", json={"url": "ftp://evil/x"})
        assert r.status_code == 400


def test_browser_render_requires_url():
    """空 URL → 422（Pydantic min_length）。"""
    with TestClient(app) as c:
        r = c.post(f"{API_PREFIX}/browser/render", json={"url": ""})
        assert r.status_code == 422


# ---------- M7.4 模式路由 ----------

def test_task_mode_chat_routes_to_run_chat(monkeypatch):
    """mode=chat 应路由到 _run_chat（而非沙盒 worker），并透传 model。"""
    calls: dict[str, str] = {}

    async def fake_chat(session_id, task_id, description, model_alias, mode):
        calls["mode"] = mode
        calls["model"] = model_alias
        from api.schemas import SessionStatus
        from api.session import store as _store

        _store.update_status(session_id, SessionStatus.done)

    monkeypatch.setattr(main, "_run_chat", fake_chat)
    with TestClient(app) as c:
        sid = _new_session(c, "chat")
        r = c.post(
            f"{API_PREFIX}/sessions/{sid}/tasks",
            json={"description": "hi", "context": {"mode": "chat", "model": "architect"}},
        )
        assert r.status_code == 200
        deadline = time.time() + 5
        while time.time() < deadline and "mode" not in calls:
            time.sleep(0.05)
    assert calls.get("mode") == "chat"
    assert calls.get("model") == "architect"
