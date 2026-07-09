"""LocalWorker 单测（M10.3：绕过 Docker 的本地 worker；M10.5 streaming 模式）。

验证：
1. 解析 ```lang:path 格式文件块
2. 安全检查：路径不能逃逸 cwd
3. 正常返回 worker 状态 dict
4. 异常容错

M10.5：local_worker 改用 httpx.stream（streaming 模式只收 content deltas，
忽略 reasoning_content）。mock 从 httpx.post 改为 httpx.stream context manager。
"""
from __future__ import annotations

import json
import os
import tempfile
from contextlib import contextmanager
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


def _make_stream_lines(content: str, finish_reason: str = "stop"):
    """把 content 拆成 SSE data: 行序列，模拟 streaming 响应。"""
    lines = []
    # 把 content 拆成小 chunk（每 50 字符一个 delta）
    for i in range(0, len(content), 50):
        chunk = content[i:i + 50]
        lines.append(f"data: {json.dumps({'choices': [{'delta': {'content': chunk}, 'finish_reason': None}]})}")
    lines.append(f"data: {json.dumps({'choices': [{'delta': {}, 'finish_reason': finish_reason}]})}")
    lines.append("data: [DONE]")
    return lines


@contextmanager
def _mock_stream(content: str, finish_reason: str = "stop"):
    """构造 httpx.stream 的 mock context manager。

    local_worker 用 `with httpx.stream(...) as r: r.iter_lines()` 消费 SSE。
    这里 mock 返回一个有 raise_for_status() 和 iter_lines() 的对象。
    """
    lines = _make_stream_lines(content, finish_reason)
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    # M11.1：用 side_effect 让每次调用都返回新迭代器（overflow retry 会调用两次）
    mock_resp.iter_lines = MagicMock(side_effect=lambda: iter(lines))
    mock_cm = MagicMock()
    mock_cm.__enter__ = MagicMock(return_value=mock_resp)
    mock_cm.__exit__ = MagicMock(return_value=False)
    with patch("httpx.stream", return_value=mock_cm):
        yield


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
        with _mock_stream(content):
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
        with _mock_stream(content):
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
        with _mock_stream(content):
            result = local_worker(_make_state(d))

        # 只有 index.html 被写，../etc/passwd 被拒绝
        assert result["last_obs"]["summary"]["tool_calls"] == 1
        assert "index.html" in result["last_obs"]["summary"]["files"]
        assert "../../etc/passwd" not in result["last_obs"]["summary"]["files"]
        assert os.path.exists(os.path.join(d, "index.html"))


def test_empty_response():
    """Kimi 返回空内容 → worker_error=True（无内容 = 基础设施故障）。"""
    with tempfile.TemporaryDirectory() as d:
        with _mock_stream(""):
            result = local_worker(_make_state(d))

        assert result["worker_error"] is True
        assert result["last_obs"]["ok"] is False


def test_non_empty_but_unparseable():
    """Kimi 有响应但无文件块 → worker_error=False（让 verifier 决定）。"""
    with tempfile.TemporaryDirectory() as d:
        with _mock_stream("这是说明文字，没有文件块"):
            result = local_worker(_make_state(d))

        assert result["worker_error"] is False  # 有内容，不算 infra error
        assert result["last_obs"]["ok"] is True


def test_http_exception_handled():
    """HTTP 异常被捕获，返回 worker_error。"""
    with tempfile.TemporaryDirectory() as d:
        mock_cm = MagicMock()
        mock_cm.__enter__ = MagicMock(side_effect=Exception("connection refused"))
        mock_cm.__exit__ = MagicMock(return_value=False)
        with patch("httpx.stream", return_value=mock_cm):
            result = local_worker(_make_state(d))

        assert result["worker_error"] is True
        assert "connection refused" in result["last_obs"]["error"]


def test_signatures_recorded():
    """动作签名记录写入的文件名。"""
    with tempfile.TemporaryDirectory() as d:
        content = _mock_kimi_response({"index.html": "<h1>hi</h1>", "style.css": "body{}"})
        with _mock_stream(content):
            result = local_worker(_make_state(d))

        sigs = result["signatures"]
        assert len(sigs) == 1
        assert "local:" in sigs[0]
        assert "index.html" in sigs[0]


def test_subdirectory_creation():
    """文件在子目录下时自动创建目录。"""
    with tempfile.TemporaryDirectory() as d:
        content = _mock_kimi_response({"src/components/Header.jsx": "export default () => <h1/>"})
        with _mock_stream(content):
            result = local_worker(_make_state(d))

        assert result["last_obs"]["ok"] is True
        assert os.path.exists(os.path.join(d, "src/components/Header.jsx"))


def test_feedback_passed_to_prompt():
    """上一轮 feedback 被注入 prompt。"""
    with tempfile.TemporaryDirectory() as d:
        content = _mock_kimi_response({"index.html": "<h1>fixed</h1>"})
        captured_kwargs = {}

        original_stream = MagicMock
        lines = _make_stream_lines(content)

        def fake_stream(*args, **kwargs):
            if not captured_kwargs:
                captured_kwargs.update(kwargs)
            mock_resp = MagicMock()
            mock_resp.raise_for_status = MagicMock()
            mock_resp.iter_lines = MagicMock(side_effect=lambda: iter(lines))
            cm = MagicMock()
            cm.__enter__ = MagicMock(return_value=mock_resp)
            cm.__exit__ = MagicMock(return_value=False)
            return cm

        with patch("httpx.stream", side_effect=fake_stream):
            local_worker(_make_state(d, feedback="上一次缺少响应式断点"))

        prompt = captured_kwargs["json"]["messages"][0]["content"]
        assert "缺少响应式断点" in prompt or "响应式断点" in prompt


def test_design_context_in_prompt():
    """project_rules（设计约束）被注入 prompt。"""
    with tempfile.TemporaryDirectory() as d:
        content = _mock_kimi_response({"index.html": "<h1>ok</h1>"})
        captured_kwargs = {}
        lines = _make_stream_lines(content)

        def fake_stream(*args, **kwargs):
            if not captured_kwargs:
                captured_kwargs.update(kwargs)
            mock_resp = MagicMock()
            mock_resp.raise_for_status = MagicMock()
            mock_resp.iter_lines = MagicMock(side_effect=lambda: iter(lines))
            cm = MagicMock()
            cm.__enter__ = MagicMock(return_value=mock_resp)
            cm.__exit__ = MagicMock(return_value=False)
            return cm

        with patch("httpx.stream", side_effect=fake_stream):
            local_worker(_make_state(d))

        assert "#0A84FF" in captured_kwargs["json"]["messages"][0]["content"]


def test_raw_html_fallback():
    """Kimi 输出裸 HTML（无 ```lang:path 前缀）→ 回退写 index.html。"""
    with tempfile.TemporaryDirectory() as d:
        raw_html = "<!DOCTYPE html>\n<html><body><h1>raw</h1></body></html>"
        with _mock_stream(raw_html):
            result = local_worker(_make_state(d))

        assert result["worker_error"] is False
        assert os.path.exists(os.path.join(d, "index.html"))
        with open(os.path.join(d, "index.html")) as f:
            assert "<h1>raw</h1>" in f.read()


def test_raw_css_fallback():
    """Kimi 输出裸 CSS → 回退写 style.css。"""
    with tempfile.TemporaryDirectory() as d:
        raw_css = ":root { --color-accent: #0A84FF; }"
        with _mock_stream(raw_css):
            result = local_worker(_make_state(d))

        assert result["worker_error"] is False
        assert os.path.exists(os.path.join(d, "style.css"))
