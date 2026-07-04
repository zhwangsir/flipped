"""F6 — 项目规则文件读取 + Supervisor prompt 注入 + drive 线程化。"""
from pathlib import Path

from driving.project_rules import read_project_rules
from driving.orchestrator import _build_supervisor_prompt, drive_orchestrated


def _w(root: Path, rel: str, text: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


# ---- read_project_rules ----

def test_reads_agents_md(tmp_path: Path):
    _w(tmp_path, "AGENTS.md", "始终用 pytest。")
    out = read_project_rules(tmp_path)
    assert "## AGENTS.md" in out
    assert "始终用 pytest。" in out


def test_concatenates_multiple_files_in_priority(tmp_path: Path):
    _w(tmp_path, "AGENTS.md", "规则A")
    _w(tmp_path, ".cursorrules", "规则B")
    out = read_project_rules(tmp_path)
    # AGENTS.md 优先在前
    assert out.index("## AGENTS.md") < out.index("## .cursorrules")
    assert "规则A" in out and "规则B" in out


def test_nested_copilot_instructions(tmp_path: Path):
    _w(tmp_path, ".github/copilot-instructions.md", "遵循 PEP8")
    out = read_project_rules(tmp_path)
    assert "copilot-instructions.md" in out
    assert "遵循 PEP8" in out


def test_no_rules_returns_empty(tmp_path: Path):
    _w(tmp_path, "README.md", "just docs")
    assert read_project_rules(tmp_path) == ""


def test_none_and_missing_dir():
    assert read_project_rules(None) == ""
    assert read_project_rules(Path("/nonexistent/x/y")) == ""


def test_total_cap_enforced(tmp_path: Path):
    _w(tmp_path, "AGENTS.md", "A" * 5000)
    _w(tmp_path, "CLAUDE.md", "B" * 5000)
    out = read_project_rules(tmp_path)
    # 单文件上限 4000 + 总上限 8000
    assert len(out) <= 8000 + 50  # 允许分隔/标题少量额外


def test_blank_file_skipped(tmp_path: Path):
    _w(tmp_path, "AGENTS.md", "   \n  ")
    _w(tmp_path, "CLAUDE.md", "真规则")
    out = read_project_rules(tmp_path)
    assert "## AGENTS.md" not in out
    assert "真规则" in out


# ---- Supervisor prompt 注入 ----

def test_prompt_includes_rules_when_present():
    state = {"goal": "建 API", "cwd": "/projects/x", "project_rules": "## AGENTS.md\n用 pytest"}
    prompt = _build_supervisor_prompt(state)
    assert "项目规则(务必遵守项目约定)" in prompt
    assert "用 pytest" in prompt


def test_prompt_omits_rules_section_when_empty():
    state = {"goal": "建 API", "cwd": "/projects/x", "project_rules": ""}
    prompt = _build_supervisor_prompt(state)
    assert "项目规则" not in prompt


# ---- drive_orchestrated 把 project_rules 灌入 state → supervisor 可见 ----

def test_drive_threads_project_rules_into_state():
    seen = {}

    def capture_supervisor(state):
        seen["rules"] = state.get("project_rules")
        return {"current_subtask": "sub", "believe_done": True,
                "history": state.get("history", []) + [{"step": "supervisor"}]}

    def worker(state):
        return {"last_obs": {"summary": {"tool_calls": 1}},
                "signatures": state.get("signatures", []) + ["s"],
                "history": state.get("history", [])}

    def overseer(state):
        return {"verdict": {"action": "continue"}, "history": state.get("history", [])}

    def verifier(cmd, cwd):
        return True, "ok"

    drive_orchestrated(
        goal="G", cwd="/projects/x", verify_cmd=["true"],
        project_rules="## AGENTS.md\n务必用 pytest",
        supervisor=capture_supervisor, worker=worker, overseer=overseer, verifier=verifier,
    )
    assert seen["rules"] == "## AGENTS.md\n务必用 pytest"
