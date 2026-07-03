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


# ---------- 项目模型:flipped=工具, 项目=~/projects/<名> 导入(默认无项目) ----------

def _mk_projects_dir(monkeypatch, tmp_path):
    """把项目主目录指到 tmp,并清空活动项目。"""
    from api import project_state as ps

    pdir = tmp_path / "projects"
    pdir.mkdir()
    monkeypatch.setattr(ps, "PROJECTS_DIR", pdir)
    ps.clear_active()
    return ps, pdir


def test_project_context_none_by_default(monkeypatch, tmp_path):
    """默认无活动项目(flipped 仓库不再当项目)→ project=None。"""
    ps, _ = _mk_projects_dir(monkeypatch, tmp_path)
    try:
        with TestClient(app) as c:
            data = c.get(f"{API_PREFIX}/project/context").json()
            assert data["project"] is None and data["path"] is None
            assert data["mode"] == "本地模式"
    finally:
        ps.clear_active()


def test_project_context_active(monkeypatch, tmp_path):
    """设活动项目 → 返回名/host路径/沙盒路径(/projects/<名>)。"""
    ps, pdir = _mk_projects_dir(monkeypatch, tmp_path)
    d = pdir / "myapp"
    d.mkdir()
    ps.set_active(d)
    try:
        with TestClient(app) as c:
            ctx = c.get(f"{API_PREFIX}/project/context").json()
            assert ctx["project"] == "myapp" and ctx["path"] == str(d)
            assert ctx["sandbox"] == "/projects/myapp"  # 沙盒路径映射
    finally:
        ps.clear_active()


def test_project_files_needs_project_then_tree(monkeypatch, tmp_path):
    """无项目 → needs_project 空树;设项目 → 树(跳过 node_modules)。"""
    ps, pdir = _mk_projects_dir(monkeypatch, tmp_path)
    try:
        with TestClient(app) as c:
            empty = c.get(f"{API_PREFIX}/project/files").json()
            assert empty["needs_project"] is True and empty["tree"] == []
            d = pdir / "p"
            (d / "src").mkdir(parents=True)
            (d / "src" / "x.py").write_text("x")
            (d / "node_modules").mkdir()
            ps.set_active(d)
            data = c.get(f"{API_PREFIX}/project/files").json()
            top = {n["name"] for n in data["tree"]}
            assert "src" in top and "node_modules" not in top
    finally:
        ps.clear_active()


def test_project_file_read_and_guards(monkeypatch, tmp_path):
    """读文件正常;路径穿越 403;不存在 404;无项目 400。"""
    ps, pdir = _mk_projects_dir(monkeypatch, tmp_path)
    d = pdir / "p"
    d.mkdir()
    (d / "readme.txt").write_text("hello")
    try:
        with TestClient(app) as c:
            assert c.get(f"{API_PREFIX}/project/file", params={"path": "readme.txt"}).status_code == 400  # 无项目
            ps.set_active(d)
            ok = c.get(f"{API_PREFIX}/project/file", params={"path": "readme.txt"})
            assert ok.status_code == 200 and ok.json()["content"] == "hello"
            assert c.get(f"{API_PREFIX}/project/file", params={"path": "../../etc/passwd"}).status_code == 403
            assert c.get(f"{API_PREFIX}/project/file", params={"path": "nope.xyz"}).status_code == 404
    finally:
        ps.clear_active()


def test_projects_list_create_open(monkeypatch, tmp_path):
    """列表 / 新建 / 打开(外部→拷进 ~/projects)/ 沙盒路径。"""
    ps, pdir = _mk_projects_dir(monkeypatch, tmp_path)
    try:
        with TestClient(app) as c:
            # 新建空白项目
            r = c.post(f"{API_PREFIX}/projects", json={"name": "app1"})
            assert r.status_code == 200 and r.json()["name"] == "app1"
            assert (pdir / "app1").is_dir()
            assert r.json()["sandbox"] == "/projects/app1"
            # 列表含之
            lst = c.get(f"{API_PREFIX}/projects").json()
            assert any(p["name"] == "app1" for p in lst["projects"])
            # 外部文件夹 → 拷进项目主目录
            ext = tmp_path / "ext-app"
            ext.mkdir()
            (ext / "main.py").write_text("print(1)")
            (ext / "node_modules").mkdir()
            r2 = c.post(f"{API_PREFIX}/project/open", json={"path": str(ext)})
            assert r2.status_code == 200 and r2.json()["name"] == "ext-app"
            assert (pdir / "ext-app" / "main.py").is_file()
            assert not (pdir / "ext-app" / "node_modules").exists()  # 重依赖被排除
            # 非法项目名
            assert c.post(f"{API_PREFIX}/projects", json={"name": "a/b"}).status_code == 400
    finally:
        ps.clear_active()


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


# ---------- 阶段②c 工作区 git diff（审查面板） ----------

def test_project_diff_endpoint():
    """/project/diff 返回 {files: [...]}（内容随工作树状态变化）。"""
    with TestClient(app) as c:
        r = c.get(f"{API_PREFIX}/project/diff")
        assert r.status_code == 200
        assert isinstance(r.json()["files"], list)


def test_parse_unified_diff():
    """统一 diff 解析：正确切分文件 + 标记 add/del/hunk/ctx。"""
    from api.main import _parse_unified_diff

    sample = (
        "diff --git a/foo.py b/foo.py\n"
        "index 111..222 100644\n"
        "--- a/foo.py\n"
        "+++ b/foo.py\n"
        "@@ -1,3 +1,3 @@\n"
        " keep\n"
        "-old line\n"
        "+new line\n"
    )
    files = _parse_unified_diff(sample)
    assert len(files) == 1
    f = files[0]
    assert f["path"] == "foo.py"
    assert f["added"] == 1 and f["removed"] == 1
    types = [ln["type"] for ln in f["lines"]]
    assert types == ["hunk", "ctx", "del", "add"]


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
