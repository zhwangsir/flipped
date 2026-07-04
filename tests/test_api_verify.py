"""F1b/F1c — GET /project/verify 端点 + orchestrator 验收命令解析。"""
from pathlib import Path

from fastapi.testclient import TestClient

from api.main import API_PREFIX, app, _resolve_verify_cmd
from api import project_state as ps


def test_verify_no_active_project():
    ps.clear_active()
    with TestClient(app) as c:
        r = c.get(f"{API_PREFIX}/project/verify")
        assert r.status_code == 200
        body = r.json()
        assert body["detected"] is False
        assert body["source"] == "none"


def test_verify_detects_pytest(tmp_path: Path):
    (tmp_path / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    ps.set_active(tmp_path)
    try:
        with TestClient(app) as c:
            body = c.get(f"{API_PREFIX}/project/verify").json()
            assert body["command"] == ["python3", "-m", "pytest", "-q"]
            assert body["source"] == "pytest"
            assert body["detected"] is True
    finally:
        ps.clear_active()


# ---- F1c: _resolve_verify_cmd(自主模式验收命令解析) ----

def test_resolve_explicit_command_wins(tmp_path: Path):
    (tmp_path / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    # 显式指定优先于探测
    assert _resolve_verify_cmd({"verify_cmd": ["make", "check"]}, tmp_path) == ["make", "check"]


def test_resolve_auto_detects_when_unset(tmp_path: Path):
    (tmp_path / "Cargo.toml").write_text("[package]\nname='x'\n", encoding="utf-8")
    assert _resolve_verify_cmd({}, tmp_path) == ["cargo", "test"]


def test_resolve_placeholder_true_triggers_detection(tmp_path: Path):
    # 显式 ['true'] = 空转占位,应被探测替换
    (tmp_path / "go.mod").write_text("module x\n", encoding="utf-8")
    assert _resolve_verify_cmd({"verify_cmd": ["true"]}, tmp_path) == ["go", "test", "./..."]


def test_resolve_no_project_falls_back_to_true():
    assert _resolve_verify_cmd({}, None) == ["true"]
