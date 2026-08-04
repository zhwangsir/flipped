"""M168.1 · assistant 会话文件改动 undo（对标 opencode /undo）TDD 测试。

核心机制 = git shadow snapshot（宿主侧执行）：
- auto/agent 消息派发前：宿主 project_root 跑 `git stash create`（dangling commit，
  不动工作区/索引/历史；无变更 → HEAD）得 snapshot hash → emit EventType.snapshot。
- chat/plan（_run_chat 直连）不改文件 → 无快照。
- 快照失败（非 git 工作区）不阻塞派发，emit system message「非 git 工作区，本轮改动不可撤销」。
- POST /sessions/{id}/undo：找最近一条未被 undo 覆盖的快照 →
  `git restore --source=<hash> -- .` 还原 tracked + 删除快照后 file_change(add/create)
  的新增文件（路径穿越防护）→ emit undo 结果事件（message/system, payload.undo=True）。

测试风格沿用既有套件：同步测试函数 + TestClient + monkeypatch 模块级 helper。
真 git 集成测试用 tmp_path 真仓库（无 git → skip）。
"""
from __future__ import annotations

import shutil
import subprocess

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(monkeypatch, tmp_path):
    """隔离 DB + mock orchestrator，返回 TestClient（同 test_assistant_api.py）。"""
    monkeypatch.setenv("FLIPPED_MOCK_ORCHESTRATOR", "1")
    monkeypatch.setattr("api.main.FLIPPED_CHECKPOINT_DB", str(tmp_path / "cp.db"))
    from api.main import app
    return TestClient(app)


@pytest.fixture()
def project_root(tmp_path):
    """把活动项目指向 tmp_path/proj（宿主侧目录），测试后清理，绝不污染全局 ps。"""
    from api import project_state as ps
    proj = tmp_path / "proj"
    proj.mkdir(exist_ok=True)
    ps.set_active(proj)
    yield proj
    ps.clear_active()


def _new_session(client, mode: str | None = None) -> str:
    body = {"title": "t"}
    if mode:
        body["mode"] = mode
    return client.post("/api/v1/assistant/sessions", json=body).json()["id"]


def _emit(sid, etype, payload, role=None):
    from api.main import bus
    from api.schemas import EventType, Role
    bus.emit(sid, getattr(EventType, etype) if isinstance(etype, str) else etype,
             role or Role.system, payload)


def _events(sid):
    from api.main import store
    return store.events(sid)


class _FakeRunning:
    """RUNNING_TASKS 守卫只调 .done()（同 test_assistant_api.py 模式）。"""
    def done(self) -> bool:
        return False


# ====================================================================
# 1 · 快照 emit（send_assistant_message, mode=auto/agent）
# ====================================================================

def test_agent_message_emits_snapshot_event_with_payload(client, monkeypatch, project_root):
    """mode=agent → 派发前 emit snapshot 事件 {snapshot, head, task_id}。"""
    monkeypatch.setattr("api.assistant._git_snapshot", lambda root: "snap123")
    monkeypatch.setattr("api.assistant._git_head", lambda root: "head456")
    sid = _new_session(client)
    r = client.post(f"/api/v1/assistant/sessions/{sid}/messages",
                    json={"text": "改代码"})
    assert r.status_code == 200, r.text
    snaps = [e for e in _events(sid) if e.type == "snapshot"]
    assert len(snaps) == 1
    assert snaps[0].payload["snapshot"] == "snap123"
    assert snaps[0].payload["head"] == "head456"
    assert snaps[0].payload["task_id"] == r.json()["task_id"]


def test_snapshot_emitted_before_task_dispatch(client, monkeypatch, project_root):
    """快照事件必须先于 create_task（orchestrator 启动时已能在事件流里找到）。"""
    monkeypatch.setattr("api.assistant._git_snapshot", lambda root: "snap123")
    monkeypatch.setattr("api.assistant._git_head", lambda root: "head456")
    seen = {}

    async def _fake_orch(session_id, task_id, req):
        seen["snap_visible"] = any(e.type == "snapshot" for e in _events(session_id))

    monkeypatch.setattr("api.main._run_orchestrator", _fake_orch)
    sid = _new_session(client)
    r = client.post(f"/api/v1/assistant/sessions/{sid}/messages", json={"text": "x"})
    assert r.status_code == 200, r.text
    assert seen.get("snap_visible") is True


@pytest.mark.parametrize("mode", ["chat", "plan"])
def test_chat_plan_modes_skip_snapshot(client, monkeypatch, project_root, mode):
    """chat/plan（_run_chat 直连）不改文件 → 不调 _git_snapshot、无 snapshot 事件。"""
    calls = {"snap": 0}

    def _counting_snap(root):
        calls["snap"] += 1
        return "snap123"

    async def _fake_chat(*args):
        return None

    monkeypatch.setattr("api.assistant._git_snapshot", _counting_snap)
    monkeypatch.setattr("api.main._run_chat", _fake_chat)
    sid = _new_session(client, mode=mode)
    r = client.post(f"/api/v1/assistant/sessions/{sid}/messages",
                    json={"text": "hi", "mode": mode})
    assert r.status_code == 200, r.text
    assert calls["snap"] == 0
    assert not any(e.type == "snapshot" for e in _events(sid))


def test_snapshot_failure_does_not_block_dispatch(client, monkeypatch, project_root):
    """快照失败（非 git 工作区）→ 仍 200 派发 + emit system 提示，无 snapshot 事件。"""
    monkeypatch.setattr("api.assistant._git_snapshot", lambda root: None)
    sid = _new_session(client)
    r = client.post(f"/api/v1/assistant/sessions/{sid}/messages", json={"text": "改代码"})
    assert r.status_code == 200, r.text
    assert r.json()["task_id"].startswith("task-")
    evs = _events(sid)
    assert not any(e.type == "snapshot" for e in evs)
    warns = [e for e in evs
             if e.type == "message" and "非 git 工作区，本轮改动不可撤销" in e.payload.get("text", "")]
    assert len(warns) == 1


def test_no_active_project_skips_snapshot_but_dispatches(client, monkeypatch):
    """无活动项目（project_root=None）→ 同样走失败提示路径，不阻塞派发。"""
    from api import project_state as ps
    ps.clear_active()
    calls = {"snap": 0}

    def _counting(root):
        calls["snap"] += 1
        return "x"

    monkeypatch.setattr("api.assistant._git_snapshot", _counting)
    sid = _new_session(client)
    r = client.post(f"/api/v1/assistant/sessions/{sid}/messages", json={"text": "x"})
    assert r.status_code == 200, r.text
    assert calls["snap"] == 0, "project_root 为 None 时不应调 git"
    assert not any(e.type == "snapshot" for e in _events(sid))


# ====================================================================
# 2 · undo 端点守卫
# ====================================================================

def test_undo_unknown_session_returns_404(client):
    r = client.post("/api/v1/assistant/sessions/sess-nope/undo")
    assert r.status_code == 404


def test_undo_running_task_returns_409(client, project_root):
    """RUNNING_TASKS 有活任务 → 409「运行中不能撤销」。"""
    from api.main import RUNNING_TASKS
    sid = _new_session(client)
    RUNNING_TASKS[sid] = _FakeRunning()
    try:
        r = client.post(f"/api/v1/assistant/sessions/{sid}/undo")
        assert r.status_code == 409
        assert "运行中不能撤销" in r.json()["detail"]
    finally:
        RUNNING_TASKS.pop(sid, None)


def test_undo_without_snapshot_returns_409(client, project_root):
    """事件流中无 snapshot → 409「没有可撤销的改动」。"""
    sid = _new_session(client)
    r = client.post(f"/api/v1/assistant/sessions/{sid}/undo")
    assert r.status_code == 409
    assert "没有可撤销的改动" in r.json()["detail"]


def test_undo_non_git_repo_returns_400(client, monkeypatch, project_root):
    """有快照但 project_root 非 git repo（rev-parse 失败）→ 400 明示，不调 restore。"""
    sid = _new_session(client)
    _emit(sid, "snapshot", {"snapshot": "abc123", "head": "x", "task_id": "t"})
    monkeypatch.setattr("api.assistant._git_head", lambda root: None)
    calls = {"restore": 0}
    monkeypatch.setattr("api.assistant._git_restore",
                        lambda root, h: calls.__setitem__("restore", calls["restore"] + 1))
    r = client.post(f"/api/v1/assistant/sessions/{sid}/undo")
    assert r.status_code == 400
    assert "git" in r.json()["detail"]
    assert calls["restore"] == 0


def test_undo_restore_failure_returns_500(client, monkeypatch, project_root):
    """git restore 失败（如 hash 失效）→ 500 带 stderr，不 emit undo 事件。"""
    sid = _new_session(client)
    _emit(sid, "snapshot", {"snapshot": "abc123", "head": "x", "task_id": "t"})
    monkeypatch.setattr("api.assistant._git_head", lambda root: "head456")

    def _boom(root, h):
        raise RuntimeError("fatal: bad object abc123")

    monkeypatch.setattr("api.assistant._git_restore", _boom)
    r = client.post(f"/api/v1/assistant/sessions/{sid}/undo")
    assert r.status_code == 500
    assert "fatal: bad object abc123" in r.json()["detail"]
    assert not any(e.payload.get("undo") for e in _events(sid))


# ====================================================================
# 3 · undo 成功路径
# ====================================================================

def _patch_git_ok(monkeypatch, calls):
    monkeypatch.setattr("api.assistant._git_head", lambda root: "head456")

    def _restore(root, h):
        calls["root"] = root
        calls["hash"] = h

    monkeypatch.setattr("api.assistant._git_restore", _restore)


def test_undo_calls_git_restore_with_latest_snapshot(client, monkeypatch, project_root):
    """undo → git restore --source=<最近 snapshot hash>，响应 {ok, restored, deleted}。"""
    sid = _new_session(client)
    _emit(sid, "snapshot", {"snapshot": "abc123", "head": "x", "task_id": "t"})
    calls = {}
    _patch_git_ok(monkeypatch, calls)
    r = client.post(f"/api/v1/assistant/sessions/{sid}/undo")
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["ok"] is True
    assert data["session_id"] == sid
    assert data["restored"] is True
    assert data["deleted"] == []
    assert calls["hash"] == "abc123"
    from pathlib import Path
    assert Path(calls["root"]) == project_root
    # undo 结果事件落库（payload.undo=True + snapshot hash，供多轮幂等）
    undos = [e for e in _events(sid) if e.payload.get("undo")]
    assert len(undos) == 1
    assert undos[0].payload["snapshot"] == "abc123"


def test_undo_deletes_added_files_from_file_change_events(client, monkeypatch, project_root):
    """快照后 file_change add/create 的新增文件被删除；modify 类不动；缺失文件跳过。"""
    sid = _new_session(client)
    from api.schemas import Role
    _emit(sid, "snapshot", {"snapshot": "abc123", "head": "x", "task_id": "t"})
    new1 = project_root / "new.py"
    new1.write_text("x")
    pkg = project_root / "pkg"
    pkg.mkdir()
    new2 = pkg / "mod.py"
    new2.write_text("y")
    _emit(sid, "file_change", {"path": "/workspace/new.py", "change": "add"}, Role.worker)
    _emit(sid, "file_change", {"path": "pkg/mod.py", "change": "create"}, Role.worker)
    _emit(sid, "file_change", {"path": "/workspace/gone.py", "change": "add"}, Role.worker)
    _emit(sid, "file_change", {"path": "/workspace/other.py", "change": "modify"}, Role.worker)
    calls = {}
    _patch_git_ok(monkeypatch, calls)
    r = client.post(f"/api/v1/assistant/sessions/{sid}/undo")
    assert r.status_code == 200, r.text
    assert not new1.exists(), "add 的新文件应被删除"
    assert not new2.exists(), "create 的新文件应被删除"
    deleted = r.json()["deleted"]
    assert "/workspace/new.py" in deleted
    assert "pkg/mod.py" in deleted
    assert "/workspace/other.py" not in deleted, "modify 不属于 add/create，不删"


def test_undo_ignores_file_changes_before_snapshot(client, monkeypatch, project_root):
    """快照事件**之前**的 file_change 不在本轮回滚范围。"""
    sid = _new_session(client)
    from api.schemas import Role
    old = project_root / "old.py"
    old.write_text("keep")
    _emit(sid, "file_change", {"path": "/workspace/old.py", "change": "add"}, Role.worker)
    _emit(sid, "snapshot", {"snapshot": "abc123", "head": "x", "task_id": "t"})
    calls = {}
    _patch_git_ok(monkeypatch, calls)
    r = client.post(f"/api/v1/assistant/sessions/{sid}/undo")
    assert r.status_code == 200, r.text
    assert old.exists(), "快照前的文件不属于本轮新增，不能删"
    assert r.json()["deleted"] == []


def test_undo_path_traversal_protection(client, monkeypatch, project_root, tmp_path):
    """../ 穿越与 project_root 外绝对路径 → 跳过不误删。"""
    sid = _new_session(client)
    from api.schemas import Role
    evil_rel = tmp_path / "evil_rel.txt"
    evil_rel.write_text("evil")
    evil_abs = tmp_path / "evil_abs.txt"
    evil_abs.write_text("evil")
    _emit(sid, "snapshot", {"snapshot": "abc123", "head": "x", "task_id": "t"})
    _emit(sid, "file_change", {"path": "../evil_rel.txt", "change": "add"}, Role.worker)
    _emit(sid, "file_change", {"path": str(evil_abs), "change": "create"}, Role.worker)
    calls = {}
    _patch_git_ok(monkeypatch, calls)
    r = client.post(f"/api/v1/assistant/sessions/{sid}/undo")
    assert r.status_code == 200, r.text
    assert evil_rel.exists(), "../ 穿越路径绝不能删 project_root 外文件"
    assert evil_abs.exists(), "root 外绝对路径绝不能删"
    assert r.json()["deleted"] == []


def test_undo_multi_round_skips_already_undone_snapshots(client, monkeypatch, project_root):
    """多轮 undo：每次撤销最近一条未覆盖快照；全部撤销后 → 409。"""
    sid = _new_session(client)
    _emit(sid, "snapshot", {"snapshot": "s1", "head": "x", "task_id": "t1"})
    _emit(sid, "snapshot", {"snapshot": "s2", "head": "x", "task_id": "t2"})
    monkeypatch.setattr("api.assistant._git_head", lambda root: "head456")
    restored = []
    monkeypatch.setattr("api.assistant._git_restore", lambda root, h: restored.append(h))

    r1 = client.post(f"/api/v1/assistant/sessions/{sid}/undo")
    assert r1.status_code == 200, r1.text
    assert restored == ["s2"], "第一轮撤销最近快照 s2"

    r2 = client.post(f"/api/v1/assistant/sessions/{sid}/undo")
    assert r2.status_code == 200, r2.text
    assert restored == ["s2", "s1"], "第二轮跳过已撤销的 s2，落 s1"

    r3 = client.post(f"/api/v1/assistant/sessions/{sid}/undo")
    assert r3.status_code == 409, "快照全部撤销后 → 409"
    assert "没有可撤销的改动" in r3.json()["detail"]


# ====================================================================
# 4 · git helper 单测（mock subprocess）
# ====================================================================

class _Completed:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def test_git_snapshot_returns_stash_create_hash(monkeypatch, tmp_path):
    """stash create 输出非空 → 直接作为 snapshot hash（dangling commit）。"""
    import api.assistant as A
    seen = {}

    def fake_run(cmd, **kw):
        seen["cmd"] = cmd
        seen["kw"] = kw
        return _Completed(0, "abc123\n", "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert A._git_snapshot(tmp_path) == "abc123"
    assert seen["cmd"] == ["git", "stash", "create"]
    assert seen["kw"]["cwd"] == str(tmp_path)
    assert seen["kw"]["timeout"] == 10


def test_git_snapshot_falls_back_to_head_when_no_changes(monkeypatch, tmp_path):
    """stash create 空输出（无变更）→ 用 `git rev-parse HEAD` 兜底。"""
    import api.assistant as A
    cmds = []

    def fake_run(cmd, **kw):
        cmds.append(cmd)
        if cmd[:2] == ["git", "stash"]:
            return _Completed(0, "", "")
        return _Completed(0, "head999\n", "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert A._git_snapshot(tmp_path) == "head999"
    assert cmds[0][:2] == ["git", "stash"]
    assert cmds[1] == ["git", "rev-parse", "HEAD"]


def test_git_snapshot_non_git_repo_returns_none(monkeypatch, tmp_path):
    """stash create 非零退出（非 git repo）→ None（不抛）。"""
    import api.assistant as A

    def fake_run(cmd, **kw):
        return _Completed(128, "", "fatal: not a git repository")

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert A._git_snapshot(tmp_path) is None


def test_git_snapshot_timeout_returns_none(monkeypatch, tmp_path):
    """git 超时 → None（快照失败不阻塞任务）。"""
    import api.assistant as A

    def fake_run(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd, 10)

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert A._git_snapshot(tmp_path) is None


def test_git_head_non_repo_returns_none(monkeypatch, tmp_path):
    import api.assistant as A

    def fake_run(cmd, **kw):
        return _Completed(128, "", "fatal: not a git repository")

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert A._git_head(tmp_path) is None


def test_git_restore_invokes_correct_args(monkeypatch, tmp_path):
    """restore 调用形：git restore --source=<hash> -- .（cwd=root, timeout=10）。"""
    import api.assistant as A
    seen = {}

    def fake_run(cmd, **kw):
        seen["cmd"] = cmd
        seen["kw"] = kw
        return _Completed(0, "", "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    A._git_restore(tmp_path, "abc123")
    assert seen["cmd"] == ["git", "restore", "--source=abc123", "--", "."]
    assert seen["kw"]["cwd"] == str(tmp_path)
    assert seen["kw"]["timeout"] == 10


def test_git_restore_failure_raises_runtime_error_with_stderr(monkeypatch, tmp_path):
    """restore 非零退出 → RuntimeError 带 stderr。"""
    import api.assistant as A

    def fake_run(cmd, **kw):
        return _Completed(128, "", "fatal: bad object abc123")

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(RuntimeError, match="fatal: bad object abc123"):
        A._git_restore(tmp_path, "abc123")


# ====================================================================
# 5 · 路径映射单测（容器路径 → 宿主 project_root）
# ====================================================================

def test_map_change_to_host_prefixes_and_relative(project_root):
    """/workspace/ 与 session.cwd 前缀 strip；相对路径直接挂 root。"""
    from api.assistant import _map_change_to_host
    assert _map_change_to_host("/workspace/a.py", project_root, "/workspace") == project_root.resolve() / "a.py"
    assert _map_change_to_host("/projects/proj/b.py", project_root, "/projects/proj") == project_root.resolve() / "b.py"
    assert _map_change_to_host("c/d.py", project_root, "/workspace") == project_root.resolve() / "c" / "d.py"
    assert _map_change_to_host(str(project_root / "e.py"), project_root, "/workspace") == project_root.resolve() / "e.py"


def test_map_change_to_host_rejects_traversal_and_outside(project_root, tmp_path):
    """../ 穿越、root 外绝对路径、空前缀、空 path → None。"""
    from api.assistant import _map_change_to_host
    assert _map_change_to_host("../evil.py", project_root, "/workspace") is None
    assert _map_change_to_host(str(tmp_path / "evil.py"), project_root, "/workspace") is None
    assert _map_change_to_host("/workspace", project_root, "/workspace") is None, "前缀本身不是文件"
    assert _map_change_to_host("", project_root, "/workspace") is None
    assert _map_change_to_host("/elsewhere/x.py", project_root, "/workspace") is None


# ====================================================================
# 6 · 真 git 集成测试（tmp_path 真仓库，无 git → skip）
# ====================================================================

def _git(root, *args):
    subprocess.run(["git", *args], cwd=str(root), check=True,
                   capture_output=True, text=True)


@pytest.mark.skipif(shutil.which("git") is None, reason="git 不可用")
def test_undo_real_git_roundtrip(client, project_root):
    """真仓库端到端：快照 → 改/删/增 → undo → tracked 还原 + 删除文件恢复 + 新增文件被删。"""
    root = project_root
    _git(root, "init")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "t")
    (root / "a.py").write_text("v1\n")
    (root / "b.py").write_text("b\n")
    _git(root, "add", ".")
    _git(root, "commit", "-m", "init")

    # 快照时刻工作区有未提交改动 → stash create 产真实 dangling commit
    (root / "a.py").write_text("v2-snapshot\n")
    from api.assistant import _git_snapshot
    snap = _git_snapshot(root)
    assert snap, "有未提交改动时 stash create 应产出 hash"

    # 快照之后：再改 a.py、删 tracked b.py、新增 untracked c.py
    (root / "a.py").write_text("v3-after\n")
    (root / "b.py").unlink()
    (root / "c.py").write_text("new\n")

    sid = _new_session(client)
    from api.schemas import Role
    _emit(sid, "snapshot", {"snapshot": snap, "head": "x", "task_id": "t"})
    _emit(sid, "file_change", {"path": "/workspace/c.py", "change": "add"}, Role.worker)

    r = client.post(f"/api/v1/assistant/sessions/{sid}/undo")
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["ok"] is True
    assert data["restored"] is True
    assert "/workspace/c.py" in data["deleted"]

    assert (root / "a.py").read_text() == "v2-snapshot\n", "tracked 改动应还原到快照态"
    assert (root / "b.py").exists() and (root / "b.py").read_text() == "b\n", "被删 tracked 文件应恢复"
    assert not (root / "c.py").exists(), "turn 内新增文件应被删除"

    # 再 undo → 唯一快照已被覆盖 → 409
    r2 = client.post(f"/api/v1/assistant/sessions/{sid}/undo")
    assert r2.status_code == 409
