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


# ---------- M14.4: finish=length 输出截断自动续生成 ----------

def test_needs_continuation_finish_length_unclosed_fence():
    """finish=length 且有未闭合的代码块 → 需要续生成。"""
    from driving.orchestrator import _needs_continuation
    content = "```html:index.html\n<!DOCTYPE html>\n<html><body>"  # 1 个 ``` (奇数)
    assert _needs_continuation(content, "length")


def test_needs_continuation_finish_stop():
    """finish=stop → 不需要续生成。"""
    from driving.orchestrator import _needs_continuation
    content = "```html:index.html\n<h1>hi</h1>\n```"  # 2 个 ``` (偶数)
    assert not _needs_continuation(content, "stop")


def test_needs_continuation_finish_length_closed():
    """finish=length 但代码块已闭合 → 不需要续生成（可能是正常长输出）。"""
    from driving.orchestrator import _needs_continuation
    content = "```html:index.html\n<h1>hi</h1>\n```\n说明文字"  # 2 个 ``` (偶数)
    assert not _needs_continuation(content, "length")


def test_needs_continuation_empty_content():
    """空 content → 不需要续生成（overflow retry 会处理）。"""
    from driving.orchestrator import _needs_continuation
    assert not _needs_continuation("", "length")


def test_needs_continuation_no_fence():
    """finish=length 但无代码块标记 → 不需要续生成（回退解析会处理）。"""
    from driving.orchestrator import _needs_continuation
    content = "这是纯文本说明，没有代码块"
    assert not _needs_continuation(content, "length")


def test_finish_length_triggers_continuation():
    """finish=length + 未闭合代码块 → 自动续生成，拼接成完整文件。

    E2E 真实场景：worker 生成 HTML 到 max_tokens 被截断（finish=length），
    代码块没有闭合的 ```。continuation 机制把已生成内容作为上下文，
    让模型继续输出剩余部分，拼接成完整文件。
    """
    with tempfile.TemporaryDirectory() as d:
        # 第一次：未闭合的 HTML（被 max_tokens 截断）
        first_content = "```html:index.html\n<!DOCTYPE html>\n<html><body>"
        # 第二次（continuation）：补全剩余部分并闭合代码块
        second_content = "<h1>completed</h1>\n</body>\n</html>\n```"

        call_count = [0]

        def fake_stream(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                content = first_content
                finish = "length"
            else:
                content = second_content
                finish = "stop"
            lines = _make_stream_lines(content, finish)
            mock_resp = MagicMock()
            mock_resp.raise_for_status = MagicMock()
            mock_resp.iter_lines = MagicMock(side_effect=lambda: iter(lines))
            cm = MagicMock()
            cm.__enter__ = MagicMock(return_value=mock_resp)
            cm.__exit__ = MagicMock(return_value=False)
            return cm

        with patch("httpx.stream", side_effect=fake_stream):
            result = local_worker(_make_state(d))

        assert result["worker_error"] is False
        assert os.path.exists(os.path.join(d, "index.html"))
        with open(os.path.join(d, "index.html")) as f:
            file_content = f.read()
            assert "<h1>completed</h1>" in file_content
            assert "</html>" in file_content


def test_finish_length_max_continuation_retries():
    """continuation 最多重试 2 次，仍不闭合则用回退解析。"""
    with tempfile.TemporaryDirectory() as d:
        # 主调用：未闭合的 content（1 个 ```，奇数）
        truncated = "```html:index.html\n<h1>still truncated"
        # continuation 每次返回无 ``` 的片段（拼接后 ``` 数量不变仍奇数，
        # 持续触发 _needs_continuation 直到 _max_continues 用完）
        cont_fragment = " more truncated content"

        call_count = [0]

        def fake_stream(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                content, finish = truncated, "length"
            else:
                content, finish = cont_fragment, "length"
            lines = _make_stream_lines(content, finish)
            mock_resp = MagicMock()
            mock_resp.raise_for_status = MagicMock()
            mock_resp.iter_lines = MagicMock(side_effect=lambda: iter(lines))
            cm = MagicMock()
            cm.__enter__ = MagicMock(return_value=mock_resp)
            cm.__exit__ = MagicMock(return_value=False)
            return cm

        with patch("httpx.stream", side_effect=fake_stream):
            result = local_worker(_make_state(d))

        # 主调用 + 2 次 continuation = 3 次调用上限
        assert call_count[0] == 3
        # 回退解析仍能写出部分内容（不 worker_error）
        assert result["worker_error"] is False


# ---------- M15.1: post-generation hex auto-fix ----------

def test_extract_hex_map_from_project_rules():
    """从 project_rules（compact design brief）提取 CSS 变量→hex 映射。"""
    from driving.orchestrator import _extract_hex_map
    project_rules = (
        "任务 task_1。已完成：无\n"
        "反馈：无\n"
        "【强制】必须用这些精确 hex 值，禁止替换: "
        "--color-accent: #0A84FF; --color-bg: #0D0D12; --color-text: #F5F5F5; "
        "字体 Inter; 用 CSS variables; 含 hover/focus 状态; "
    )
    hex_map = _extract_hex_map(project_rules)
    assert hex_map["--color-accent"] == "#0A84FF"
    assert hex_map["--color-bg"] == "#0D0D12"
    assert hex_map["--color-text"] == "#F5F5F5"


def test_extract_hex_map_empty_when_no_design_brief():
    """project_rules 中无设计约束 → 空映射。"""
    from driving.orchestrator import _extract_hex_map
    hex_map = _extract_hex_map("任务 task_1。已完成：无\n反馈：无")
    assert hex_map == {}


def test_auto_fix_hex_replaces_wrong_values():
    """worker 用了错误 hex 值 → 写文件后自动替换为正确值。"""
    with tempfile.TemporaryDirectory() as d:
        # worker 生成的 HTML（用了错误 hex：#0b0f19 而非 #0D0D12）
        wrong_html = (
            "```html:index.html\n"
            "<!DOCTYPE html>\n<html><head><style>\n"
            ":root {\n"
            "  --color-accent: #0a84ff;\n"
            "  --color-bg: #0b0f19;\n"
            "  --color-text: #f8fafc;\n"
            "}\n"
            "</style></head><body><h1>test</h1></body></html>\n"
            "```"
        )
        project_rules = (
            "【强制】必须用这些精确 hex 值，禁止替换: "
            "--color-accent: #0A84FF; --color-bg: #0D0D12; --color-text: #F5F5F5; "
            "字体 Inter; 用 CSS variables;"
        )
        with _mock_stream(wrong_html):
            result = local_worker(_make_state(d, subtask="test", feedback=""))
        # 覆盖 project_rules（_make_state 默认用 #0A84FF，需要完整 compact brief）
        # 实际上 local_worker 从 state["project_rules"] 读取，_make_state 设了 "暗黑模式，主色 #0A84FF"
        # 所以这里直接测试 _auto_fix_hex_in_dir

    # 直接测试 _auto_fix_hex_in_dir
    from driving.orchestrator import _auto_fix_hex_in_dir
    with tempfile.TemporaryDirectory() as d2:
        html_path = os.path.join(d2, "index.html")
        with open(html_path, "w") as f:
            f.write(
                "<!DOCTYPE html>\n<html><head><style>\n"
                ":root {\n"
                "  --color-accent: #0a84ff;\n"
                "  --color-bg: #0b0f19;\n"
                "  --color-text: #f8fafc;\n"
                "}\n"
                "</style></head><body></body></html>"
            )
        hex_map = {"--color-accent": "#0A84FF", "--color-bg": "#0D0D12", "--color-text": "#F5F5F5"}
        fixed = _auto_fix_hex_in_dir(d2, hex_map)
        assert fixed is True
        with open(html_path) as f:
            content = f.read()
            assert "#0D0D12" in content
            assert "#F5F5F5" in content
            assert "#0b0f19" not in content
            assert "#f8fafc" not in content


def test_auto_fix_hex_skips_correct_values():
    """hex 值已经正确 → 不替换。"""
    from driving.orchestrator import _auto_fix_hex_in_dir
    with tempfile.TemporaryDirectory() as d:
        html_path = os.path.join(d, "index.html")
        with open(html_path, "w") as f:
            f.write(
                ":root {\n"
                "  --color-accent: #0A84FF;\n"
                "  --color-bg: #0D0D12;\n"
                "  --color-text: #F5F5F5;\n"
                "}"
            )
        hex_map = {"--color-accent": "#0A84FF", "--color-bg": "#0D0D12", "--color-text": "#F5F5F5"}
        fixed = _auto_fix_hex_in_dir(d, hex_map)
        assert fixed is False  # 没有需要修正的


def test_auto_fix_hex_skips_non_html_files():
    """非 HTML/CSS 文件不修正。"""
    from driving.orchestrator import _auto_fix_hex_in_dir
    with tempfile.TemporaryDirectory() as d:
        with open(os.path.join(d, "app.js"), "w") as f:
            f.write("const color = '#0b0f19'; // 不应该被修正")
        hex_map = {"--color-bg": "#0D0D12"}
        fixed = _auto_fix_hex_in_dir(d, hex_map)
        assert fixed is False


def test_auto_fix_hex_integration_with_local_worker():
    """集成：local_worker 写文件后自动修正 hex 值。

    E2E 暴露：worker(Kimi) 把 #0D0D12 替换成 #0b0f19，#F5F5F5 替换成 #f8fafc。
    compact brief 已说"禁止替换"但模型不遵守。
    修复：local_worker 写文件后自动扫描 CSS 变量定义，替换为正确 hex 值。
    """
    with tempfile.TemporaryDirectory() as d:
        # worker 生成错误 hex 值的 HTML
        wrong_html = (
            "```html:index.html\n"
            "<!DOCTYPE html>\n<html><head><style>\n"
            ":root {\n"
            "  --color-accent: #0a84ff;\n"
            "  --color-bg: #0b0f19;\n"
            "  --color-text: #f8fafc;\n"
            "}\n"
            "</style></head><body><h1>test</h1></body></html>\n"
            "```"
        )
        state = {
            "cwd": d,
            "current_subtask": "写 landing page",
            "goal": "写 landing page",
            "project_rules": (
                "【强制】必须用这些精确 hex 值，禁止替换: "
                "--color-accent: #0A84FF; --color-bg: #0D0D12; --color-text: #F5F5F5; "
                "字体 Inter; 用 CSS variables;"
            ),
            "feedback": "",
            "signatures": [],
            "history": [],
        }
        with _mock_stream(wrong_html):
            result = local_worker(state)

        assert result["worker_error"] is False
        html_path = os.path.join(d, "index.html")
        assert os.path.exists(html_path)
        with open(html_path) as f:
            content = f.read()
            # 错误的 hex 值应被自动修正
            assert "#0D0D12" in content
            assert "#F5F5F5" in content
            assert "#0b0f19" not in content
            assert "#f8fafc" not in content


def test_auto_fix_design_issues_integration_with_local_worker():
    """集成：local_worker 写文件后自动修复间距/字体/HTML结构/CSS变量/动画性能/语义化。

    M24-M29：auto_fix_design_issues 在 local_worker 文件写入后自动调用，
    不依赖模型遵守设计约束。
    """
    with tempfile.TemporaryDirectory() as d:
        # worker 生成有各种设计问题的 HTML
        bad_html = (
            "```html:index.html\n"
            "<html><head><style>\n"
            "body { padding: 13px; margin: 7px; font-size: 16px; }\n"
            "h1 { font-size: 37px; }\n"
            ".card { transition: margin 0.3s; }\n"
            "</style></head><body>\n"
            "<img src=\"photo.jpg\">\n"
            "<div class=\"card\">Card</div>\n"
            "</body></html>\n"
            "```"
        )
        state = {
            "cwd": d,
            "current_subtask": "写 landing page",
            "goal": "写 landing page",
            "project_rules": "",
            "feedback": "",
            "signatures": [],
            "history": [],
        }
        with _mock_stream(bad_html):
            result = local_worker(state)

        assert result["worker_error"] is False
        html_path = os.path.join(d, "index.html")
        assert os.path.exists(html_path)
        with open(html_path) as f:
            content = f.read()

        # M24: 间距网格修复
        assert "13px" not in content, f"间距应被修正: 13px 仍在"
        assert "7px" not in content, f"间距应被修正: 7px 仍在"

        # M24: 字体比例修复
        assert "37px" not in content, f"字号应被修正: 37px 仍在"

        # M25: HTML 结构修复
        assert "viewport" in content.lower(), "应注入 meta viewport"
        assert 'lang=' in content, "应注入 html lang"
        assert 'alt=' in content.lower(), "应注入 img alt"

        # M26: 动画性能修复
        assert "margin 0.3s" not in content, "transition 应移除非 transform/opacity 属性"

        # M27: CSS 变量注入
        assert "--color-bg" in content, "应注入 CSS 变量系统"

        # M29: 语义化 HTML
        assert "<main" in content.lower(), "应注入 <main> 标签"
        assert "<header" in content.lower(), "应注入 <header> 标签"
        assert "<footer" in content.lower(), "应注入 <footer> 标签"


# ---------- M51: Worker 文件上下文累积 ----------


def test_read_file_context_no_file():
    """无 index.html 时返回空字符串。"""
    from driving.orchestrator import _read_file_context
    with tempfile.TemporaryDirectory() as d:
        assert _read_file_context(d) == ""


def test_read_file_context_with_existing_html():
    """有 index.html 时返回结构摘要（CSS 变量名 + 标签计数）。"""
    from driving.orchestrator import _read_file_context
    with tempfile.TemporaryDirectory() as d:
        html = """<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8">
<style>:root { --color-accent: #0A84FF; --color-bg: #0D0D12; }</style>
</head><body><header><nav>Logo</nav></header>
<main><section><h1>Title</h1><button>CTA</button></section></main>
<footer>Footer</footer>
</body></html>"""
        with open(os.path.join(d, "index.html"), "w") as f:
            f.write(html)
        ctx = _read_file_context(d)
        assert ctx != ""
        # 应包含 CSS 变量名
        assert "--color-accent" in ctx or "--color-bg" in ctx
        # 应包含已有标签信息
        assert "header" in ctx or "main" in ctx or "section" in ctx


def test_read_file_context_empty_file():
    """空/tiny 文件返回空字符串。"""
    from driving.orchestrator import _read_file_context
    with tempfile.TemporaryDirectory() as d:
        with open(os.path.join(d, "index.html"), "w") as f:
            f.write("")
        assert _read_file_context(d) == ""


def test_worker_prompt_includes_file_context():
    """有 index.html 时 worker prompt 包含已有文件结构摘要。"""
    with tempfile.TemporaryDirectory() as d:
        # 先创建已有 index.html
        existing_html = (
            "<!DOCTYPE html>\n<html lang=\"zh\"><head><style>\n"
            ":root { --color-accent: #0A84FF; }\n"
            "</style></head><body><header><nav>Logo</nav></header>"
            "<main><section><h1>已有标题</h1></section></main></body></html>"
        )
        with open(os.path.join(d, "index.html"), "w") as f:
            f.write(existing_html)

        # mock Kimi 响应
        content = _mock_kimi_response({"index.html": "<!DOCTYPE html><h1>updated</h1>"})
        captured_kwargs = {}

        def fake_stream(*args, **kwargs):
            if not captured_kwargs:
                captured_kwargs.update(kwargs)
            mock_resp = MagicMock()
            mock_resp.raise_for_status = MagicMock()
            mock_resp.iter_lines = MagicMock(side_effect=lambda: iter(_make_stream_lines(content)))
            cm = MagicMock()
            cm.__enter__ = MagicMock(return_value=mock_resp)
            cm.__exit__ = MagicMock(return_value=False)
            return cm

        with patch("httpx.stream", side_effect=fake_stream):
            local_worker(_make_state(d))

        prompt = captured_kwargs["json"]["messages"][0]["content"]
        # prompt 应包含已有文件的结构信息
        assert "现有" in prompt or "已有" in prompt
        assert "--color-accent" in prompt or "header" in prompt


def test_worker_prompt_no_file_context_when_empty():
    """无 index.html 时 worker prompt 不包含文件上下文。"""
    with tempfile.TemporaryDirectory() as d:
        content = _mock_kimi_response({"index.html": "<!DOCTYPE html><h1>new</h1>"})
        captured_kwargs = {}

        def fake_stream(*args, **kwargs):
            if not captured_kwargs:
                captured_kwargs.update(kwargs)
            mock_resp = MagicMock()
            mock_resp.raise_for_status = MagicMock()
            mock_resp.iter_lines = MagicMock(side_effect=lambda: iter(_make_stream_lines(content)))
            cm = MagicMock()
            cm.__enter__ = MagicMock(return_value=mock_resp)
            cm.__exit__ = MagicMock(return_value=False)
            return cm

        with patch("httpx.stream", side_effect=fake_stream):
            local_worker(_make_state(d))

        prompt = captured_kwargs["json"]["messages"][0]["content"]
        assert "现有" not in prompt


# ---------- M52: 设计质量回归保护 ----------


def test_check_design_regression_no_old_content():
    """无旧内容时不检测回归（首次生成）。"""
    from driving.orchestrator import _check_design_regression
    with tempfile.TemporaryDirectory() as d:
        # cwd 有新文件但无旧内容
        with open(os.path.join(d, "index.html"), "w") as f:
            f.write("<!DOCTYPE html><html><body><h1>new</h1></body></html>")
        assert _check_design_regression(d, "") is False


def test_check_design_regression_score_dropped():
    """新版本 design_score 低于旧版本 → 回归。"""
    from driving.orchestrator import _check_design_regression
    # 旧版本：高质量 HTML（有 viewport/CSS变量/语义化/响应式/无障碍）
    old_html = (
        "<!DOCTYPE html>\n<html lang=\"zh\"><head>\n"
        "<meta charset=\"utf-8\">\n<meta name=\"viewport\" content=\"width=device-width\">\n"
        "<style>:root { --color-accent: #0A84FF; --color-bg: #0D0D12; }\n"
        "@media (max-width: 768px) { body { font-size: 14px; } }\n"
        "</style></head><body>\n"
        "<header><nav>Logo</nav></header>\n"
        "<main><section><h1>Title</h1><button>CTA</button></section></main>\n"
        "<footer>Footer</footer>\n</body></html>"
    )
    # 新版本：低质量 HTML（缺失大量元素）
    new_html = "<html><body><h1>bad</h1></body></html>"
    with tempfile.TemporaryDirectory() as d:
        with open(os.path.join(d, "index.html"), "w") as f:
            f.write(new_html)
        assert _check_design_regression(d, old_html) is True


def test_check_design_regression_score_improved():
    """新版本 design_score 高于或等于旧版本 → 无回归。"""
    from driving.orchestrator import _check_design_regression
    # 旧版本：低质量
    old_html = "<html><body><h1>bad</h1></body></html>"
    # 新版本：高质量
    new_html = (
        "<!DOCTYPE html>\n<html lang=\"zh\"><head>\n"
        "<meta charset=\"utf-8\">\n<meta name=\"viewport\" content=\"width=device-width\">\n"
        "<style>:root { --color-accent: #0A84FF; }\n"
        "@media (max-width: 768px) { body { font-size: 14px; } }\n"
        "</style></head><body>\n"
        "<header><nav>Logo</nav></header>\n"
        "<main><section><h1>Title</h1><button>CTA</button></section></main>\n"
        "<footer>Footer</footer>\n</body></html>"
    )
    with tempfile.TemporaryDirectory() as d:
        with open(os.path.join(d, "index.html"), "w") as f:
            f.write(new_html)
        assert _check_design_regression(d, old_html) is False


def test_worker_reverts_on_regression():
    """worker 生成低质量 HTML 覆盖高质量已有文件 → 自动回退。"""
    with tempfile.TemporaryDirectory() as d:
        # 先创建高质量已有文件
        good_html = (
            "<!DOCTYPE html>\n<html lang=\"zh\"><head>\n"
            "<meta charset=\"utf-8\">\n<meta name=\"viewport\" content=\"width=device-width\">\n"
            "<style>:root { --color-accent: #0A84FF; --color-bg: #0D0D12; }\n"
            "@media (max-width: 768px) { body { font-size: 14px; } }\n"
            "</style></head><body>\n"
            "<header><nav>Logo</nav></header>\n"
            "<main><section><h1>Good Title</h1><button>CTA</button></section></main>\n"
            "<footer>Footer</footer>\n</body></html>"
        )
        with open(os.path.join(d, "index.html"), "w") as f:
            f.write(good_html)

        # worker 生成低质量 HTML（丢失 viewport/CSS变量/语义化等）
        bad_html = _mock_kimi_response({"index.html": "<html><body><h1>bad</h1></body></html>"})

        with _mock_stream(bad_html):
            result = local_worker(_make_state(d))

        # 回退后磁盘上应保留高质量内容
        with open(os.path.join(d, "index.html")) as f:
            final_content = f.read()
        assert "Good Title" in final_content  # 旧内容保留
        assert "viewport" in final_content.lower()  # 高质量特征保留


def test_worker_keeps_new_version_when_no_regression():
    """worker 生成更高质量 HTML → 保留新版本。"""
    with tempfile.TemporaryDirectory() as d:
        # 先创建低质量已有文件
        bad_html_existing = "<html><body><h1>old bad</h1></body></html>"
        with open(os.path.join(d, "index.html"), "w") as f:
            f.write(bad_html_existing)

        # worker 生成高质量 HTML
        good_new_html = (
            "```html:index.html\n"
            "<!DOCTYPE html>\n<html lang=\"zh\"><head>\n"
            "<meta charset=\"utf-8\">\n<meta name=\"viewport\" content=\"width=device-width\">\n"
            "<style>:root { --color-accent: #0A84FF; }\n"
            "@media (max-width: 768px) { body { font-size: 14px; } }\n"
            "</style></head><body>\n"
            "<header><nav>Logo</nav></header>\n"
            "<main><section><h1>New Good Title</h1><button>CTA</button></section></main>\n"
            "<footer>Footer</footer>\n</body></html>\n"
            "```"
        )
        with _mock_stream(good_new_html):
            result = local_worker(_make_state(d))

        # 保留新版本
        with open(os.path.join(d, "index.html")) as f:
            final_content = f.read()
        assert "New Good Title" in final_content
