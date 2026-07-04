"""F5 — 仓库结构地图 + Supervisor prompt 注入 + drive 线程化。"""
from pathlib import Path

from driving.repo_map import build_repo_map
from driving.orchestrator import _build_supervisor_prompt, drive_orchestrated


def _w(root: Path, rel: str, text: str = "x") -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def test_detects_stack(tmp_path: Path):
    _w(tmp_path, "pyproject.toml")
    _w(tmp_path, "package.json", "{}")
    out = build_repo_map(tmp_path)
    assert "技术栈：" in out
    assert "Python" in out and "Node/JS" in out


def test_lists_top_dirs_and_key_files(tmp_path: Path):
    _w(tmp_path, "src/app.py")
    _w(tmp_path, "tests/test_app.py")
    _w(tmp_path, "README.md")
    _w(tmp_path, "Makefile")
    out = build_repo_map(tmp_path)
    assert "顶层目录：" in out
    assert "src/" in out and "tests/" in out
    assert "关键文件：" in out
    assert "README.md" in out and "Makefile" in out


def test_expands_top_dirs_one_level(tmp_path: Path):
    _w(tmp_path, "src/api/main.py")
    _w(tmp_path, "src/driving/orchestrator.py")
    out = build_repo_map(tmp_path)
    assert "src/ 下：" in out
    assert "api/" in out and "driving/" in out


def test_skips_ignored_and_hidden(tmp_path: Path):
    _w(tmp_path, "src/real.py")
    _w(tmp_path, "node_modules/pkg/index.js")
    _w(tmp_path, ".git/config")
    (tmp_path / ".venv").mkdir()
    out = build_repo_map(tmp_path)
    assert "node_modules" not in out
    assert ".git" not in out
    assert ".venv" not in out
    assert "src/" in out


def test_none_and_missing_dir():
    assert build_repo_map(None) == ""
    assert build_repo_map(Path("/nonexistent/x/y")) == ""


def test_empty_project(tmp_path: Path):
    # 空目录:无技术栈/目录/关键文件 → 空串
    assert build_repo_map(tmp_path) == ""


def test_total_cap(tmp_path: Path):
    for i in range(50):
        _w(tmp_path, f"dir{i:03d}/f.py")
    out = build_repo_map(tmp_path)
    assert len(out) <= 2500


def test_real_flipped_repo_maps_python():
    out = build_repo_map(Path("."))
    assert "Python" in out
    assert "src/" in out


# ---- Supervisor prompt 注入 ----

def test_prompt_includes_repo_map():
    state = {"goal": "建 API", "cwd": "/projects/x",
             "repo_map": "技术栈：Python\n顶层目录：src/、tests/"}
    prompt = _build_supervisor_prompt(state)
    assert "项目结构" in prompt
    assert "src/、tests/" in prompt


def test_prompt_omits_repo_map_when_empty():
    prompt = _build_supervisor_prompt({"goal": "g", "cwd": "/x", "repo_map": ""})
    assert "项目结构" not in prompt


# ---- drive_orchestrated 线程化 repo_map ----

def test_drive_threads_repo_map_into_state():
    seen = {}

    def capture_supervisor(state):
        seen["map"] = state.get("repo_map")
        return {"current_subtask": "sub", "believe_done": True,
                "history": state.get("history", []) + [{"step": "supervisor"}]}

    def worker(state):
        return {"last_obs": {"summary": {"tool_calls": 1}},
                "signatures": state.get("signatures", []) + ["s"], "history": state.get("history", [])}

    def overseer(state):
        return {"verdict": {"action": "continue"}, "history": state.get("history", [])}

    drive_orchestrated(
        goal="G", cwd="/projects/x", verify_cmd=["true"],
        repo_map="技术栈：Python",
        supervisor=capture_supervisor, worker=worker, overseer=overseer,
        verifier=lambda c, d: (True, "ok"),
    )
    assert seen["map"] == "技术栈：Python"
