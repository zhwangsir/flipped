"""双模型并行验证监督单元测试（M14 / D19）。"""
from __future__ import annotations

import sys
import time
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from driving.parallel_verifier import (
    SemanticVerdict,
    _coerce_verdict,
    _parse_semantic_json,
    _read_artifacts,
    make_glm_semantic_verifier,
    make_parallel_verifier,
)


# ---------- _read_artifacts ----------

def test_read_artifacts_index_html(tmp_path):
    """优先读 index.html。"""
    (tmp_path / "index.html").write_text("<html><body>hello</body></html>", encoding="utf-8")
    (tmp_path / "style.css").write_text("body{color:red}", encoding="utf-8")
    out = _read_artifacts(tmp_path)
    assert "=== index.html ===" in out
    assert "<html>" in out
    assert "hello" in out


def test_read_artifacts_no_files(tmp_path):
    """无产物文件返回空串。"""
    assert _read_artifacts(tmp_path) == ""


def test_read_artifacts_truncates_long_file(tmp_path):
    """长文件截断到 _MAX_FILE_BYTES。"""
    long_content = "x" * 10000
    (tmp_path / "index.html").write_text(long_content, encoding="utf-8")
    out = _read_artifacts(tmp_path)
    assert "truncated" in out
    assert len(out) < 10000


def test_read_artifacts_fallback_glob(tmp_path):
    """无 index.html 时扫其他 html。"""
    (tmp_path / "page.html").write_text("<div>page</div>", encoding="utf-8")
    out = _read_artifacts(tmp_path)
    assert "page" in out
    assert "=== page.html ===" in out


# ---------- _parse_semantic_json / _coerce_verdict ----------

def test_parse_pure_json():
    """纯 JSON 正常解析。"""
    content = '{"severity":"ok","issues":[],"rationale":"all good"}'
    v = _parse_semantic_json(content)
    assert v.severity == "ok"
    assert v.checked is True
    assert v.issues == []


def test_parse_markdown_code_block():
    """markdown code block 包裹的 JSON。"""
    content = '```json\n{"severity":"warning","issues":["small issue"],"rationale":"minor"}\n```'
    v = _parse_semantic_json(content)
    assert v.severity == "warning"
    assert len(v.issues) == 1
    assert "small issue" in v.issues[0]


def test_parse_json_with_extra_text():
    """JSON + 附加文字。"""
    content = 'Here is my analysis:\n{"severity":"blocker","issues":["missing alt"]}\n以上是结论。'
    v = _parse_semantic_json(content)
    assert v.severity == "blocker"
    assert "missing alt" in v.issues[0]


def test_parse_garbage_fail_open():
    """无法解析的输出 fail-open（不当 blocker）。"""
    content = "I cannot analyze this."
    v = _parse_semantic_json(content)
    assert v.severity == "ok"
    assert v.checked is False
    assert "无法解析" in v.skip_reason


def test_coerce_unknown_severity_defaults_ok():
    """未知 severity 值 fail-open 为 ok。"""
    v = _coerce_verdict({"severity": "critical", "issues": ["x"]})
    assert v.severity == "ok"


def test_coerce_issues_string_to_list():
    """issues 为字符串时包成 list。"""
    v = _coerce_verdict({"severity": "warning", "issues": "single issue"})
    assert v.issues == ["single issue"]


def test_coerce_issues_truncated():
    """issue 字符串截断到 80 字符。"""
    long_issue = "x" * 200
    v = _coerce_verdict({"severity": "warning", "issues": [long_issue]})
    assert len(v.issues[0]) <= 80


# ---------- SemanticVerdict ----------

def test_verdict_is_blocker():
    assert SemanticVerdict(severity="blocker").is_blocker is True
    assert SemanticVerdict(severity="warning").is_blocker is False
    assert SemanticVerdict(severity="ok").is_blocker is False


def test_verdict_summary_skip():
    v = SemanticVerdict(severity="ok", checked=False, skip_reason="no artifacts")
    assert "跳过" in v.summary()
    assert "no artifacts" in v.summary()


def test_verdict_summary_ok():
    v = SemanticVerdict(severity="ok", checked=True)
    assert "通过" in v.summary()


def test_verdict_summary_blocker_with_issues():
    v = SemanticVerdict(severity="blocker", issues=["a", "b"], checked=True)
    s = v.summary()
    assert "blocker" in s
    assert "a" in s


# ---------- make_glm_semantic_verifier（mock GLM） ----------

def test_glm_semantic_verifier_no_artifacts(tmp_path):
    """无产物文件 → skip。"""
    v = make_glm_semantic_verifier(timeout=5)
    result = v([], str(tmp_path))
    assert result.checked is False
    assert "无产物" in result.skip_reason


def test_glm_semantic_verifier_mock_ok(tmp_path):
    """mock GLM 返回 ok。"""
    (tmp_path / "index.html").write_text("<html><body>ok</body></html>", encoding="utf-8")

    def fake_post(url, **kwargs):
        class R:
            status_code = 200
            def raise_for_status(self): pass
            def json(self):
                return {"choices": [{"message": {"content": '{"severity":"ok","issues":[],"rationale":"good"}'}}]}
        return R()

    with patch("driving.parallel_verifier.resolve_model_config", return_value=("http://fake/v1", "fake-model")):
        with patch("httpx.post", side_effect=fake_post):
            v = make_glm_semantic_verifier(timeout=5)
            result = v([], str(tmp_path))
    assert result.severity == "ok"
    assert result.checked is True
    assert result.rationale == "good"


def test_glm_semantic_verifier_http_error_fail_open(tmp_path):
    """GLM HTTP 错误 → fail-open。"""
    (tmp_path / "index.html").write_text("<html></html>", encoding="utf-8")

    def fake_post(url, **kwargs):
        raise Exception("connection refused")

    with patch("driving.parallel_verifier.resolve_model_config", return_value=("http://fake/v1", "fake")):
        with patch("httpx.post", side_effect=fake_post):
            v = make_glm_semantic_verifier(timeout=5)
            result = v([], str(tmp_path))
    assert result.severity == "ok"
    assert result.checked is False
    assert "GLM 调用失败" in result.skip_reason


# ---------- make_parallel_verifier ----------

def test_parallel_both_pass(tmp_path):
    """确定性通过 + GLM ok → 通过。"""
    (tmp_path / "index.html").write_text("<html></html>", encoding="utf-8")

    def base_ok(cmd, cwd):
        return True, "det: ok"

    def fake_post(url, **kwargs):
        class R:
            status_code = 200
            def raise_for_status(self): pass
            def json(self):
                return {"choices": [{"message": {"content": '{"severity":"ok","issues":[]}'}}]}
        return R()

    with patch("driving.parallel_verifier.resolve_model_config", return_value=("http://fake/v1", "fake")):
        with patch("httpx.post", side_effect=fake_post):
            verifier = make_parallel_verifier(base_ok, glm_timeout=5)
            ok, msg = verifier([], str(tmp_path))
    assert ok is True
    assert "det: ok" in msg
    assert "glm_semantic 通过" in msg


def test_parallel_deterministic_fail(tmp_path):
    """确定性失败 → 失败（GLM 仍并行跑）。"""
    (tmp_path / "index.html").write_text("<html></html>", encoding="utf-8")

    def base_fail(cmd, cwd):
        return False, "verify_cmd exit 1"

    def fake_post(url, **kwargs):
        class R:
            status_code = 200
            def raise_for_status(self): pass
            def json(self):
                return {"choices": [{"message": {"content": '{"severity":"ok","issues":[]}'}}]}
        return R()

    with patch("driving.parallel_verifier.resolve_model_config", return_value=("http://fake/v1", "fake")):
        with patch("httpx.post", side_effect=fake_post):
            verifier = make_parallel_verifier(base_fail, glm_timeout=5)
            ok, msg = verifier([], str(tmp_path))
    assert ok is False
    assert "verify_cmd exit 1" in msg


def test_parallel_glm_blocker_fails(tmp_path):
    """确定性通过 + GLM blocker → 失败。"""
    (tmp_path / "index.html").write_text("<html></html>", encoding="utf-8")

    def base_ok(cmd, cwd):
        return True, "det: ok"

    def fake_post(url, **kwargs):
        class R:
            status_code = 200
            def raise_for_status(self): pass
            def json(self):
                return {"choices": [{"message": {"content": '{"severity":"blocker","issues":["missing section","no alt"],"rationale":"structure broken"}'}}]}
        return R()

    with patch("driving.parallel_verifier.resolve_model_config", return_value=("http://fake/v1", "fake")):
        with patch("httpx.post", side_effect=fake_post):
            verifier = make_parallel_verifier(base_ok, glm_timeout=5)
            ok, msg = verifier([], str(tmp_path))
    assert ok is False
    assert "glm_blocker" in msg
    assert "missing section" in msg or "no alt" in msg


def test_parallel_glm_warning_passes(tmp_path):
    """确定性通过 + GLM warning → 通过（warning 不阻断）。"""
    (tmp_path / "index.html").write_text("<html></html>", encoding="utf-8")

    def base_ok(cmd, cwd):
        return True, "det: ok"

    def fake_post(url, **kwargs):
        class R:
            status_code = 200
            def raise_for_status(self): pass
            def json(self):
                return {"choices": [{"message": {"content": '{"severity":"warning","issues":["minor typo"]}'}}]}
        return R()

    with patch("driving.parallel_verifier.resolve_model_config", return_value=("http://fake/v1", "fake")):
        with patch("httpx.post", side_effect=fake_post):
            verifier = make_parallel_verifier(base_ok, glm_timeout=5)
            ok, msg = verifier([], str(tmp_path))
    assert ok is True
    assert "warning" in msg


def test_parallel_glm_skip_fail_open(tmp_path):
    """GLM 不可用 → fail-open（只返回确定性结果）。"""
    (tmp_path / "index.html").write_text("<html></html>", encoding="utf-8")

    def base_ok(cmd, cwd):
        return True, "det: ok"

    def fake_post(url, **kwargs):
        raise Exception("connection refused")

    with patch("driving.parallel_verifier.resolve_model_config", return_value=("http://fake/v1", "fake")):
        with patch("httpx.post", side_effect=fake_post):
            verifier = make_parallel_verifier(base_ok, glm_timeout=5)
            ok, msg = verifier([], str(tmp_path))
    assert ok is True
    assert "GLM 调用失败" in msg or "跳过" in msg


def test_parallel_actually_concurrent(tmp_path):
    """验证两个 verifier 真的并行（总时间 ≈ max(t1, t2)，不是 t1+t2）。"""
    (tmp_path / "index.html").write_text("<html></html>", encoding="utf-8")

    def slow_base(cmd, cwd):
        time.sleep(0.5)
        return True, "det: ok"

    def slow_glm_post(url, **kwargs):
        time.sleep(0.5)
        class R:
            status_code = 200
            def raise_for_status(self): pass
            def json(self):
                return {"choices": [{"message": {"content": '{"severity":"ok"}'}}]}
        return R()

    with patch("driving.parallel_verifier.resolve_model_config", return_value=("http://fake/v1", "fake")):
        with patch("httpx.post", side_effect=slow_glm_post):
            verifier = make_parallel_verifier(slow_base, glm_timeout=5)
            t0 = time.monotonic()
            ok, msg = verifier([], str(tmp_path))
            elapsed = time.monotonic() - t0
    assert ok is True
    # 并行：两个 0.5s 任务应在 < 1s 完成（串行需 1s+）
    assert elapsed < 0.95, f"expected parallel (<0.95s), got {elapsed:.2f}s"


def test_parallel_deterministic_crash_fails(tmp_path):
    """确定性 verifier 抛异常 → 失败。"""
    (tmp_path / "index.html").write_text("<html></html>", encoding="utf-8")

    def crash_base(cmd, cwd):
        raise RuntimeError("base crashed")

    def fake_post(url, **kwargs):
        class R:
            status_code = 200
            def raise_for_status(self): pass
            def json(self):
                return {"choices": [{"message": {"content": '{"severity":"ok"}'}}]}
        return R()

    with patch("driving.parallel_verifier.resolve_model_config", return_value=("http://fake/v1", "fake")):
        with patch("httpx.post", side_effect=fake_post):
            verifier = make_parallel_verifier(crash_base, glm_timeout=5)
            ok, msg = verifier([], str(tmp_path))
    assert ok is False
    assert "crashed" in msg


# ---- M92.1 _read_artifacts 后端代码产物读取扩展 ----

def test_read_artifacts_reads_main_py(tmp_path):
    """M92.1: 读取后端 main.py。"""
    (tmp_path / "main.py").write_text("from fastapi import FastAPI\napp = FastAPI()", encoding="utf-8")
    out = _read_artifacts(tmp_path)
    assert "=== main.py ===" in out
    assert "FastAPI" in out


def test_read_artifacts_reads_app_py(tmp_path):
    """M92.1: 读取 app.py。"""
    (tmp_path / "app.py").write_text("def hello(): return 'hi'", encoding="utf-8")
    out = _read_artifacts(tmp_path)
    assert "=== app.py ===" in out
    assert "hello" in out


def test_read_artifacts_priority_index_html_over_py(tmp_path):
    """M92.1: index.html 优先级仍高于 .py 文件。"""
    (tmp_path / "index.html").write_text("<html>frontend</html>", encoding="utf-8")
    (tmp_path / "main.py").write_text("# backend", encoding="utf-8")
    out = _read_artifacts(tmp_path)
    assert "=== index.html ===" in out
    assert "=== main.py ===" in out  # 两者都读,但 index.html 在前


def test_read_artifacts_reads_py_glob_fallback(tmp_path):
    """M92.1: 无入口文件时扫其他 .py 文件。"""
    (tmp_path / "models.py").write_text("class User: pass", encoding="utf-8")
    (tmp_path / "routes.py").write_text("def get(): pass", encoding="utf-8")
    out = _read_artifacts(tmp_path)
    assert "models.py" in out
    assert "routes.py" in out


def test_read_artifacts_mixed_frontend_backend(tmp_path):
    """M92.1: 前后端混合产物都能读到。"""
    (tmp_path / "index.html").write_text("<html>front</html>", encoding="utf-8")
    (tmp_path / "main.py").write_text("app = FastAPI()", encoding="utf-8")
    out = _read_artifacts(tmp_path)
    assert "index.html" in out
    assert "main.py" in out


# ---- M92.2 GLM 语义验证后端代码质量维度 ----

def test_glm_semantic_prompt_includes_backend_dimensions(tmp_path):
    """M92.2: GLM prompt 包含后端代码质量维度(异常处理/SQL注入/输入校验)。"""
    (tmp_path / "main.py").write_text("app = FastAPI()", encoding="utf-8")
    captured_prompt = []

    def fake_post(url, **kwargs):
        captured_prompt.append(kwargs.get("json", {}).get("messages", [{}])[0].get("content", ""))
        class R:
            status_code = 200
            def raise_for_status(self): pass
            def json(self):
                return {"choices": [{"message": {"content": '{"severity":"ok"}'}}]}
        return R()

    with patch("driving.parallel_verifier.resolve_model_config", return_value=("http://fake/v1", "fake")):
        with patch("httpx.post", side_effect=fake_post):
            v = make_glm_semantic_verifier(timeout=5)
            v([], str(tmp_path))
    assert captured_prompt, "应捕获到 GLM prompt"
    prompt = captured_prompt[0]
    # 后端代码质量维度应在 prompt 中
    assert "exception" in prompt.lower() or "异常" in prompt
    assert "sql" in prompt.lower() or "注入" in prompt


def test_glm_blocker_on_backend_sql_injection(tmp_path):
    """M92.2: GLM 检测到 SQL 注入 → blocker。"""
    (tmp_path / "main.py").write_text(
        "def query(user_input): cur.execute(f'SELECT * FROM users WHERE name={user_input}')",
        encoding="utf-8",
    )

    def base_ok(cmd, cwd):
        return True, "det: ok"

    def fake_post(url, **kwargs):
        class R:
            status_code = 200
            def raise_for_status(self): pass
            def json(self):
                return {"choices": [{"message": {"content": '{"severity":"blocker","issues":["SQL注入风险:f-string拼接SQL"]}'}}]}
        return R()

    with patch("driving.parallel_verifier.resolve_model_config", return_value=("http://fake/v1", "fake")):
        with patch("httpx.post", side_effect=fake_post):
            verifier = make_parallel_verifier(base_ok, glm_timeout=5)
            ok, msg = verifier([], str(tmp_path))
    assert ok is False, "SQL 注入应被 GLM blocker 阻断"
    assert "SQL" in msg or "注入" in msg


def test_glm_warning_on_missing_exception_handling(tmp_path):
    """M92.2: GLM 检测到缺少异常处理 → warning(不阻断)。"""
    (tmp_path / "main.py").write_text("def risky(): return 1/0", encoding="utf-8")

    def base_ok(cmd, cwd):
        return True, "det: ok"

    def fake_post(url, **kwargs):
        class R:
            status_code = 200
            def raise_for_status(self): pass
            def json(self):
                return {"choices": [{"message": {"content": '{"severity":"warning","issues":["缺少异常处理:除零未try-except"]}'}}]}
        return R()

    with patch("driving.parallel_verifier.resolve_model_config", return_value=("http://fake/v1", "fake")):
        with patch("httpx.post", side_effect=fake_post):
            verifier = make_parallel_verifier(base_ok, glm_timeout=5)
            ok, msg = verifier([], str(tmp_path))
    assert ok is True, "warning 不应阻断"
    assert "异常" in msg or "warning" in msg.lower()


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
