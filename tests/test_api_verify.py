"""F1b — GET /project/verify 端点(活动项目验收命令探测)。"""
from pathlib import Path

from fastapi.testclient import TestClient

from api.main import API_PREFIX, app
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
            assert body["command"] == ["pytest", "-q"]
            assert body["source"] == "pytest"
            assert body["detected"] is True
    finally:
        ps.clear_active()
