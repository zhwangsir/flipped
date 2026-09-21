"""M195 P2 批消化第二波单测。

- M195.1：_split_markdown fenced code block 豁免（消化 L-M171-3）
- M195.2：limitations_report check target 存在性校验（消化 L-M185-3）
           + report 索引机制（消化 L-M184-4）
- M195.3：GET /api/v1/models/aliases 端点（消化 L-M194-2 后端半）
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from rag.ingest import _split_markdown

REPO_ROOT = Path(__file__).resolve().parent.parent
REPORT_PY = REPO_ROOT / "scripts" / "limitations_report.py"


# --------------------------------------------------------------------
# M195.1 · fenced code block 豁免
# --------------------------------------------------------------------
def test_fence_hash_comment_not_heading() -> None:
    """``` 围栏内行首 #（shell/python 注释）不再被当标题切段。"""
    text = "# 真标题\n正文\n```bash\n# 这是注释不是标题\necho hi\n```\n收尾行\n"
    sections = _split_markdown(text)
    assert len(sections) == 1
    assert "# 这是注释不是标题" in sections[0]


def test_fence_with_info_string() -> None:
    """围栏带 info string（```python）同样豁免。"""
    text = "# A\n```python\n# comment\ndef f():\n    pass\n```\n# B\nbody\n"
    sections = _split_markdown(text)
    assert len(sections) == 2
    assert sections[0].startswith("# A")
    assert "# comment" in sections[0]  # 注释留在 A 段内
    assert sections[1].startswith("# B")


def test_tilde_fence_exempt() -> None:
    """~~~ 围栏同样豁免。"""
    text = "# A\n~~~\n# not heading\n~~~\n# B\n"
    sections = _split_markdown(text)
    assert len(sections) == 2
    assert "# not heading" in sections[0]


def test_unclosed_fence_conservative() -> None:
    """围栏未闭合：余下全文视为 fence 内，保守不再切段。"""
    text = "# A\n```\n# x\n# y\n"
    sections = _split_markdown(text)
    assert len(sections) == 1


def test_heading_outside_fence_still_splits() -> None:
    """围栏外标题切段行为不变（回归）。"""
    text = "# A\nbody\n# B\nbody2\n## C\nbody3\n"
    sections = _split_markdown(text)
    assert len(sections) == 3
    assert sections[0].startswith("# A")
    assert sections[1].startswith("# B")
    assert sections[2].startswith("## C")


def test_cross_fence_chars_not_closing() -> None:
    """``` 开启的 fence 不会被 ~~~ 闭合（不同字符）。"""
    text = "# A\n```\n~~~\n# still in fence\n```\n# B\n"
    sections = _split_markdown(text)
    assert len(sections) == 2
    assert "# still in fence" in sections[0]
    assert sections[1].startswith("# B")


# --------------------------------------------------------------------
# M195.2 · check target 存在性校验 + report 索引
# --------------------------------------------------------------------
def _write_state(path: Path, milestones: list[str]) -> None:
    state = {"milestones": {m: {"title": m, "status": "done"} for m in milestones}}
    path.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")


def _write_registry(path: Path, target: str) -> None:
    reg = {
        "version": 1,
        "updated_at": "",
        "limitations": [
            {
                "id": "L-M999-1",
                "milestone": "M999",
                "text": "dummy",
                "category": "未分类",
                "impact": "",
                "priority": "P2",
                "difficulty": "中",
                "status": "open",
                "resolution_note": "",
                "target": target,
            }
        ],
    }
    path.write_text(json.dumps(reg, ensure_ascii=False), encoding="utf-8")


def _run_report(tmp_path: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(REPORT_PY), *args],
        capture_output=True, text=True, timeout=30, cwd=tmp_path,
    )


def test_check_target_milestone_must_exist(tmp_path: Path) -> None:
    """target 为 M 数字格式但 STATE.json 无该里程碑 → check 失败。"""
    _write_state(tmp_path / "STATE.json", ["M999"])
    _write_registry(tmp_path / "reg.json", "M12345")  # 不存在
    r = _run_report(tmp_path, "check", "--state", "STATE.json", "--registry", "reg.json")
    assert r.returncode == 1
    assert "M12345" in r.stdout
    assert "target" in r.stdout


def test_check_target_existing_milestone_ok(tmp_path: Path) -> None:
    """target 指向真实存在的里程碑 → check 通过。"""
    _write_state(tmp_path / "STATE.json", ["M999", "M195"])
    _write_registry(tmp_path / "reg.json", "M195")
    r = _run_report(tmp_path, "check", "--state", "STATE.json", "--registry", "reg.json")
    assert r.returncode == 0, r.stdout + r.stderr


def test_check_target_non_m_format_skipped(tmp_path: Path) -> None:
    """target 为「后续里程碑」等非 M 格式 → 不校验存在性，check 通过。"""
    _write_state(tmp_path / "STATE.json", ["M999"])
    _write_registry(tmp_path / "reg.json", "后续里程碑")
    r = _run_report(tmp_path, "check", "--state", "STATE.json", "--registry", "reg.json")
    assert r.returncode == 0, r.stdout + r.stderr


def test_report_appends_index(tmp_path: Path) -> None:
    """report 生成后维护 reports/index.md 索引（日期 + 文件 + 总数），重复生成同日去重。"""
    _write_state(tmp_path / "STATE.json", ["M999"])
    _write_registry(tmp_path / "reg.json", "")
    (tmp_path / "reports").mkdir()
    out1 = "reports/limitations_analysis_20990101.md"
    r = _run_report(tmp_path, "report", "--registry", "reg.json", "--out", out1)
    assert r.returncode == 0, r.stdout + r.stderr
    index = tmp_path / "reports" / "index.md"
    assert index.exists()
    first = index.read_text(encoding="utf-8")
    assert "limitations_analysis_20990101.md" in first
    assert "2099-01-01" in first
    # 同日同文件重复生成 → 索引不重复追加
    r2 = _run_report(tmp_path, "report", "--registry", "reg.json", "--out", out1)
    assert r2.returncode == 0
    second = index.read_text(encoding="utf-8")
    hit_lines = [l for l in second.splitlines()
                 if "limitations_analysis_20990101.md" in l]
    assert len(hit_lines) == 1


# --------------------------------------------------------------------
# M195.3 · GET /api/v1/models/aliases
# --------------------------------------------------------------------
def test_models_aliases_endpoint() -> None:
    """aliases 端点返回 alias→model 映射清单（默认+env 覆盖反映）。"""
    from fastapi.testclient import TestClient

    from api.main import app

    client = TestClient(app)
    r = client.get("/api/v1/models/aliases")
    assert r.status_code == 200
    data = r.json()
    aliases = data.get("aliases")
    assert isinstance(aliases, list) and len(aliases) >= 2
    by_alias = {a["alias"]: a for a in aliases}
    assert "coder" in by_alias and "architect" in by_alias
    # 默认映射（无 env 时）——单模型模式，coder 与 architect 同源
    assert "GLM-5.2" in by_alias["coder"]["model"]
    assert "GLM-5.2" in by_alias["architect"]["model"]


def test_models_aliases_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """FLIPPED_CODER_MODEL env 覆盖时端点反映覆盖后模型。"""
    from fastapi.testclient import TestClient

    from api.main import app

    monkeypatch.setenv("FLIPPED_CODER_MODEL", "test-override-model")
    client = TestClient(app)
    r = client.get("/api/v1/models/aliases")
    assert r.status_code == 200
    by_alias = {a["alias"]: a for a in r.json()["aliases"]}
    assert by_alias["coder"]["model"] == "test-override-model"
