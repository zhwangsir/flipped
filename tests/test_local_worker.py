"""LocalWorker 单测（M10.3：绕过 Docker 的本地 worker）。

验证：
1. 解析 ```lang:path 格式文件块
2. 安全检查：路径不能逃逸 cwd
3. 正常返回 worker 状态 dict
4. 异常容错
"""
from __future__ import annotations

import os
import tempfile
from unittest.mock import patch, MagicMock

import pytest

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from driving.orchestrator import local_worker, OrchestratorState


def _mock_kimi_response(files: dict[str, str]) -> str:
    """构造 Kimi 响应内容（```lang:path 格式文件块）。"""
    blocks = []
    for path, content in files.items():
        ext = path.rsplit(".", 1)[-1] if "." in path else "txt"
        blocks.append(f"```{ext}:{path}\n{content}\n```")
    return "\n\n".join(blocks)


def _make_state(cwd: str, subtask="写一个 landing page", feedback="") -> OrchestratorState:
    return {
        "cwd": cwd,
        "current_subtask": subtask,
        "goal": subtask,
        "project_rules": "暗黑模式，主色 #0A84FF",
        "feedback": feedback,
        "signatures": [],
        "history": [],
    }


def test_writes_single_file():
    """正常写单个文件到 cwd。"""
    with tempfile.TemporaryDirectory() as d:
        content = _mock_kimi_response({"index.html": "<!DOCTYPE html><h1>Hello</h1>"})
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "choices": [{"message": {"content": content}}]
        }
        mock_resp.raise_for_status = MagicMock()

        with patch("httpx.post", return_value=mock_resp):
            state = _make_state(d)
            result = local_worker(state)

        assert result["worker_error"] is False
        assert result["last_obs"]["ok"] is True
        assert "index.html" in result["last_obs"]["summary"]["files"]
        assert os.path.exists(os.path.join(d, "index.html"))
        with open(os.path.join(d, "index.html")) as f:
            assert "<h1>Hello</h1>" in f.read()


def test_writes_multiple_files():
    """一次写多个文件。"""
    with tempfile.TemporaryDirectory() as d:
        content = _mock_kimi_response({
            "index.html": "<html>main</html>",
            "style.css": "body { color: #0A84FF; }",
            "app.js": "console.log('hi');",
        })
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"choices": [{"message": {"content": content}}]}
        mock_resp.raise_for_status = MagicMock()

        with patch("httpx.post", return_value=mock_resp):
            result = local_worker(_make_state(d))

        assert result["last_obs"]["summary"]["tool_calls"] == 3
        for f in ("index.html", "style.css", "app.js"):
            assert os.path.exists(os.path.join(d, f))


def test_path_escaping_blocked():
    """路径逃逸 cwd 被拒绝（不写 ../ 外的文件）。"""
    with tempfile.TemporaryDirectory() as d:
        content = _mock_kimi_response({
            "../../etc/passwd": "hacked",
            "index.html": "<h1>safe</h1>",
        })
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"choices": [{"message": {"content": content}}]}
        mock_resp.raise_for_status = MagicMock()

        with patch("httpx.post", return_value=mock_resp):
            result = local_worker(_make_state(d))

        # 只有 index.html 被写，../etc/passwd 被拒绝
        assert result["last_obs"]["summary"]["tool_calls"] == 1
        assert "index.html" in result["last_obs"]["summary"]["files"]
        assert "../../etc/passwd" not in result["last_obs"]["summary"]["files"]
        assert os.path.exists(os.path.join(d, "index.html"))


def test_empty_response():
    """Kimi 返回空内容 → worker_error=True（无内容 = 基础设施故障）。"""
    with tempfile.TemporaryDirectory() as d:
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"choices": [{"message": {"content": ""}}]}
        mock_resp.raise_for_status = MagicMock()

        with patch("httpx.post", return_value=mock_resp):
            result = local_worker(_make_state(d))

        assert result["worker_error"] is True
        assert result["last_obs"]["ok"] is False


def test_non_empty_but_unparseable():
    """Kimi 有响应但无文件块 → worker_error=False（让 verifier 决定）。"""
    with tempfile.TemporaryDirectory() as d:
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"choices": [{"message": {"content": "这是说明文字，没有文件块"}}]}
        mock_resp.raise_for_status = MagicMock()

        with patch("httpx.post", return_value=mock_resp):
            result = local_worker(_make_state(d))

        assert result["worker_error"] is False  # 有内容，不算 infra error
        assert result["last_obs"]["ok"] is True


def test_http_exception_handled():
    """HTTP 异常被捕获，返回 worker_error。"""
    with tempfile.TemporaryDirectory() as d:
        with patch("httpx.post", side_effect=Exception("connection refused")):
            result = local_worker(_make_state(d))

        assert result["worker_error"] is True
        assert "connection refused" in result["last_obs"]["error"]


def test_signatures_recorded():
    """动作签名记录写入的文件名。"""
    with tempfile.TemporaryDirectory() as d:
        content = _mock_kimi_response({"index.html": "<h1>hi</h1>", "style.css": "body{}"})
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"choices": [{"message": {"content": content}}]}
        mock_resp.raise_for_status = MagicMock()

        with patch("httpx.post", return_value=mock_resp):
            result = local_worker(_make_state(d))

        sigs = result["signatures"]
        assert len(sigs) == 1
        assert "local:" in sigs[0]
        assert "index.html" in sigs[0]


def test_subdirectory_creation():
    """文件在子目录下时自动创建目录。"""
    with tempfile.TemporaryDirectory() as d:
        content = _mock_kimi_response({"src/components/Header.jsx": "export default () => <h1/>"})
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"choices": [{"message": {"content": content}}]}
        mock_resp.raise_for_status = MagicMock()

        with patch("httpx.post", return_value=mock_resp):
            result = local_worker(_make_state(d))

        assert result["last_obs"]["ok"] is True
        assert os.path.exists(os.path.join(d, "src/components/Header.jsx"))


def test_feedback_passed_to_prompt():
    """上一轮 feedback 被注入 prompt。"""
    with tempfile.TemporaryDirectory() as d:
        content = _mock_kimi_response({"index.html": "<h1>fixed</h1>"})
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"choices": [{"message": {"content": content}}]}
        mock_resp.raise_for_status = MagicMock()

        captured_kwargs = {}
        def capture_post(url, **kwargs):
            captured_kwargs.update(kwargs)
            return mock_resp

        with patch("httpx.post", side_effect=capture_post):
            local_worker(_make_state(d, feedback="上一次缺少响应式断点"))

        prompt = captured_kwargs["json"]["messages"][0]["content"]
        assert "缺少响应式断点" in prompt or "响应式断点" in prompt


def test_design_context_in_prompt():
    """project_rules（设计约束）被注入 prompt。"""
    with tempfile.TemporaryDirectory() as d:
        content = _mock_kimi_response({"index.html": "<h1>ok</h1>"})
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"choices": [{"message": {"content": content}}]}
        mock_resp.raise_for_status = MagicMock()

        captured = {}
        def capture(url, **kwargs):
            captured.update(kwargs)
            return mock_resp

        with patch("httpx.post", side_effect=capture):
            local_worker(_make_state(d))

        assert "#0A84FF" in captured["json"]["messages"][0]["content"]


def test_raw_html_fallback():
    """Kimi 输出裸 HTML（无 ```lang:path 前缀）→ 回退写 index.html。"""
    with tempfile.TemporaryDirectory() as d:
        raw_html = "<!DOCTYPE html>\n<html><body><h1>raw</h1></body></html>"
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"choices": [{"message": {"content": raw_html}}]}
        mock_resp.raise_for_status = MagicMock()

        with patch("httpx.post", return_value=mock_resp):
            result = local_worker(_make_state(d))

        assert result["worker_error"] is False
        assert os.path.exists(os.path.join(d, "index.html"))
        with open(os.path.join(d, "index.html")) as f:
            assert "<h1>raw</h1>" in f.read()


def test_raw_css_fallback():
    """Kimi 输出裸 CSS → 回退写 style.css。"""
    with tempfile.TemporaryDirectory() as d:
        raw_css = ":root { --color-accent: #0A84FF; }"
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"choices": [{"message": {"content": raw_css}}]}
        mock_resp.raise_for_status = MagicMock()

        with patch("httpx.post", return_value=mock_resp):
            result = local_worker(_make_state(d))

        assert result["worker_error"] is False
        assert os.path.exists(os.path.join(d, "style.css"))
