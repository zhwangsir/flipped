"""M128 · 视觉反馈闭环测试。"""
from __future__ import annotations

import os
import tempfile

from driving.visual_feedback import (
    VisualFeedbackLoop,
    ScreenshotResult,
    VisualDiff,
    DiffLevel,
    FileChange,
)


def _make_screenshot(path: str, success: bool = True, hash: str = "abc123") -> ScreenshotResult:
    """创建模拟截图结果。"""
    if success:
        # 创建实际的图片文件
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)
    return ScreenshotResult(
        path=path,
        timestamp="2026-01-01T00:00:00Z",
        width=1280,
        height=720,
        file_hash=hash if success else "",
        error="" if success else "screenshot failed",
    )


class TestDiffLevel:
    def test_values(self):
        assert DiffLevel.none.value == "none"
        assert DiffLevel.major.value == "major"
        assert DiffLevel.structural.value == "structural"


class TestScreenshotResult:
    def test_success_when_file_exists(self):
        fd, path = tempfile.mkstemp(suffix=".png")
        os.close(fd)
        r = ScreenshotResult(path=path, timestamp="t", file_hash="h")
        assert r.success is True

    def test_fail_when_error(self):
        r = ScreenshotResult(path="/nonexistent", timestamp="t", error="failed")
        assert r.success is False

    def test_to_dict(self):
        r = ScreenshotResult(path="/tmp/test.png", timestamp="t", width=800, height=600)
        d = r.to_dict()
        assert d["width"] == 800
        assert d["path"] == "/tmp/test.png"


class TestVisualDiff:
    def test_to_dict(self):
        before = ScreenshotResult(path="b", timestamp="t")
        after = ScreenshotResult(path="a", timestamp="t")
        diff = VisualDiff(before=before, after=after, diff_level=DiffLevel.moderate)
        d = diff.to_dict()
        assert d["diff_level"] == "moderate"

    def test_to_prompt_text_none(self):
        before = ScreenshotResult(path="b", timestamp="t")
        after = ScreenshotResult(path="a", timestamp="t")
        diff = VisualDiff(before=before, after=after, diff_level=DiffLevel.none)
        text = diff.to_prompt_text()
        assert "无变化" in text

    def test_to_prompt_text_major(self):
        before = ScreenshotResult(path="b", timestamp="t")
        after = ScreenshotResult(path="a", timestamp="t")
        diff = VisualDiff(
            before=before, after=after, diff_level=DiffLevel.major,
            changed_percentage=35.5,
        )
        text = diff.to_prompt_text()
        assert "大幅" in text
        assert "35.5" in text


class TestVisualFeedbackLoop:
    def test_capture_with_mock(self):
        def mock_screenshot(url, path):
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as f:
                f.write(b"fake png")
            return ScreenshotResult(path=path, timestamp="t", file_hash="h1")

        loop = VisualFeedbackLoop(
            screenshot_fn=mock_screenshot,
            screenshot_dir=tempfile.mkdtemp(),
        )
        result = loop.capture("http://localhost:3000", name="test")
        assert result.success is True
        assert os.path.exists(result.path)

    def test_capture_fail_open(self):
        def failing_screenshot(url, path):
            return ScreenshotResult(path=path, timestamp="t", error="no browser")

        loop = VisualFeedbackLoop(
            screenshot_fn=failing_screenshot,
            screenshot_dir=tempfile.mkdtemp(),
        )
        result = loop.capture("http://localhost:3000")
        assert result.success is False
        assert "no browser" in result.error

    def test_compare_identical_screenshots(self):
        """相同哈希 = 无变化。"""
        loop = VisualFeedbackLoop(screenshot_dir=tempfile.mkdtemp())
        before = ScreenshotResult(path="/b.png", timestamp="t", file_hash="same", width=100, height=100)
        after = ScreenshotResult(path="/a.png", timestamp="t", file_hash="same", width=100, height=100)
        diff = loop.compare(before, after)
        assert diff.diff_level == DiffLevel.none

    def test_compare_with_failed_screenshots(self):
        """截图失败时降级为文件变更分析。"""
        loop = VisualFeedbackLoop(screenshot_dir=tempfile.mkdtemp())
        before = ScreenshotResult(path="/b.png", timestamp="t", error="failed")
        after = ScreenshotResult(path="/a.png", timestamp="t", error="failed")
        changes = [FileChange(path="src/App.tsx", change_type="modified")]
        diff = loop.compare(before, after, changed_files=changes)
        assert diff.diff_level == DiffLevel.moderate
        assert "src/App.tsx" in diff.changed_files

    def test_compare_with_no_changes_no_files(self):
        """截图失败且无文件变更 = 无变化。"""
        loop = VisualFeedbackLoop(screenshot_dir=tempfile.mkdtemp())
        before = ScreenshotResult(path="/b.png", timestamp="t", error="failed")
        after = ScreenshotResult(path="/a.png", timestamp="t", error="failed")
        diff = loop.compare(before, after, changed_files=[])
        assert diff.diff_level == DiffLevel.none

    def test_run_feedback_loop(self):
        """完整视觉反馈闭环。"""
        call_count = [0]

        def mock_screenshot(url, path):
            call_count[0] += 1
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as f:
                f.write(f"fake png {call_count[0]}".encode())
            return ScreenshotResult(
                path=path, timestamp="t",
                file_hash=f"hash_{call_count[0]}",
                width=100, height=100,
            )

        loop = VisualFeedbackLoop(
            screenshot_fn=mock_screenshot,
            screenshot_dir=tempfile.mkdtemp(),
        )

        def make_changes():
            return [FileChange(path="src/index.html", change_type="modified")]

        diff = loop.run_feedback_loop(
            "http://localhost:3000",
            code_change_fn=make_changes,
        )
        assert call_count[0] == 2  # before + after
        assert diff.diff_level != DiffLevel.none or len(diff.changed_files) > 0

    def test_run_feedback_loop_with_code_error(self):
        """代码变更失败时不阻塞反馈闭环。"""
        def mock_screenshot(url, path):
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as f:
                f.write(b"png")
            return ScreenshotResult(path=path, timestamp="t", file_hash="h")

        loop = VisualFeedbackLoop(
            screenshot_fn=mock_screenshot,
            screenshot_dir=tempfile.mkdtemp(),
        )

        def failing_change():
            raise RuntimeError("build failed")

        diff = loop.run_feedback_loop(
            "http://localhost:3000",
            code_change_fn=failing_change,
        )
        # 不应崩溃
        assert isinstance(diff, VisualDiff)

    def test_get_history(self):
        screenshot_dir = tempfile.mkdtemp()
        # 创建一些截图文件
        for i in range(5):
            with open(os.path.join(screenshot_dir, f"shot_{i}.png"), "wb") as f:
                f.write(b"png")

        loop = VisualFeedbackLoop(screenshot_dir=screenshot_dir)
        history = loop.get_history(limit=3)
        assert len(history) == 3
        assert all(h.endswith(".png") for h in history)

    def test_get_history_empty(self):
        loop = VisualFeedbackLoop(screenshot_dir=tempfile.mkdtemp())
        history = loop.get_history()
        assert history == []

    def test_file_hash(self):
        loop = VisualFeedbackLoop(screenshot_dir=tempfile.mkdtemp())
        path = os.path.join(loop.screenshot_dir, "test.png")
        with open(path, "wb") as f:
            f.write(b"test content")
        h = loop._file_hash(path)
        assert len(h) == 16
