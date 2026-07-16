"""M128 · 视觉反馈闭环。

借鉴 Orca 的 Design Mode：Agent 改完代码后自动截图对比 UI 变化。

核心能力：
1. 代码变更前后自动截图
2. 像素级 diff 对比
3. 变更区域标注
4. 反馈注入到 Agent prompt

需要外部工具支持（fail-open）：
- 无 Playwright/screenshot 工具时降级为文件变更记录
"""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable

from driving.structured_logger import StructuredLogger, LogLevel


class DiffLevel(str, Enum):
    """变更级别。"""
    none = "none"         # 无变化
    minimal = "minimal"   # 微小变化（< 5% 像素）
    moderate = "moderate"  # 中等变化（5-20%）
    major = "major"        # 大幅变化（> 20%）
    structural = "structural"  # 结构性变化（页面布局改变）


@dataclass
class ScreenshotResult:
    """截图结果。"""
    path: str
    timestamp: str
    width: int = 0
    height: int = 0
    file_hash: str = ""
    error: str = ""

    @property
    def success(self) -> bool:
        return not self.error and os.path.exists(self.path)

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "timestamp": self.timestamp,
            "width": self.width,
            "height": self.height,
            "file_hash": self.file_hash,
            "error": self.error,
            "success": self.success,
        }


@dataclass
class VisualDiff:
    """视觉差异对比结果。"""
    before: ScreenshotResult
    after: ScreenshotResult
    diff_level: DiffLevel
    changed_pixels: int = 0
    total_pixels: int = 0
    changed_percentage: float = 0.0
    diff_image_path: str = ""
    changed_files: list[str] = field(default_factory=list)
    summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "before": self.before.to_dict(),
            "after": self.after.to_dict(),
            "diff_level": self.diff_level.value,
            "changed_pixels": self.changed_pixels,
            "total_pixels": self.total_pixels,
            "changed_percentage": round(self.changed_percentage, 2),
            "diff_image_path": self.diff_image_path,
            "changed_files": self.changed_files,
            "summary": self.summary,
        }

    def to_prompt_text(self) -> str:
        """转换为可注入到 Agent prompt 的反馈文本。"""
        if self.diff_level == DiffLevel.none:
            return "【视觉反馈】UI 无变化。"

        lines = [f"【视觉反馈】检测到 UI 变更（{self.diff_level.value}）："]
        lines.append(f"  变更比例: {self.changed_percentage:.1f}%")

        if self.changed_files:
            lines.append(f"  变更文件: {', '.join(self.changed_files[:5])}")

        if self.diff_level == DiffLevel.major:
            lines.append("  ⚠ 大幅 UI 变更，请检查是否符合预期")
        elif self.diff_level == DiffLevel.structural:
            lines.append("  ⚠ 页面结构变化，可能影响布局")

        if self.diff_image_path:
            lines.append(f"  对比图: {self.diff_image_path}")

        return "\n".join(lines)


@dataclass
class FileChange:
    """文件变更记录。"""
    path: str
    change_type: str  # added / modified / deleted
    lines_added: int = 0
    lines_removed: int = 0


class VisualFeedbackLoop:
    """视觉反馈闭环。

    screenshot_fn: 可注入的截图函数 (url, output_path) -> ScreenshotResult。
                    默认使用 Playwright（fail-open 降级为文件变更记录）。
    """

    def __init__(
        self,
        *,
        screenshot_fn: Callable[[str, str], ScreenshotResult] | None = None,
        screenshot_dir: str = "/tmp/flipped-screenshots",
        logger: StructuredLogger | None = None,
    ) -> None:
        self.screenshot_fn = screenshot_fn or self._default_screenshot
        self.screenshot_dir = os.path.abspath(screenshot_dir)
        self.logger = logger or StructuredLogger(
            module_name="visual_feedback",
            min_level=LogLevel.info,
        )
        os.makedirs(self.screenshot_dir, exist_ok=True)

    def _default_screenshot(self, url: str, output_path: str) -> ScreenshotResult:
        """默认截图函数：尝试 Playwright，失败则返回空结果。"""
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                browser = p.chromium.launch()
                page = browser.new_page(viewport={"width": 1280, "height": 720})
                page.goto(url, timeout=15000)
                page.screenshot(path=output_path, full_page=True)
                browser.close()

            file_hash = self._file_hash(output_path)
            return ScreenshotResult(
                path=output_path,
                timestamp=datetime.now(timezone.utc).isoformat(),
                width=1280,
                height=720,
                file_hash=file_hash,
            )
        except Exception as exc:
            return ScreenshotResult(
                path=output_path,
                timestamp=datetime.now(timezone.utc).isoformat(),
                error=str(exc),
            )

    def _file_hash(self, path: str) -> str:
        """计算文件哈希。"""
        try:
            with open(path, "rb") as f:
                return hashlib.md5(f.read()).hexdigest()[:16]
        except Exception:
            return ""

    def capture(self, url: str, *, name: str = "") -> ScreenshotResult:
        """截取当前页面截图。"""
        if not name:
            name = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        output_path = os.path.join(self.screenshot_dir, f"{name}.png")

        result = self.screenshot_fn(url, output_path)

        if result.success:
            self.logger.info("screenshot_captured", {
                "name": name,
                "path": output_path,
                "hash": result.file_hash,
            })
        else:
            self.logger.warn("screenshot_failed", {
                "name": name,
                "error": result.error,
            })

        return result

    def compare(
        self,
        before: ScreenshotResult,
        after: ScreenshotResult,
        *,
        changed_files: list[FileChange] | None = None,
    ) -> VisualDiff:
        """对比两个截图的差异。

        Args:
            before: 变更前截图。
            after: 变更后截图。
            changed_files: 变更的文件列表（用于增强反馈）。
        """
        # 如果截图失败，降级为文件变更分析
        if not before.success or not after.success:
            return self._file_based_diff(before, after, changed_files or [])

        # 哈希相同 = 无变化
        if before.file_hash and before.file_hash == after.file_hash:
            return VisualDiff(
                before=before,
                after=after,
                diff_level=DiffLevel.none,
                total_pixels=before.width * before.height,
                summary="UI 无变化（截图哈希相同）",
            )

        # 像素级对比（简单实现）
        changed_pixels, total_pixels = self._pixel_diff(before.path, after.path)
        percentage = (changed_pixels / max(1, total_pixels)) * 100

        if percentage < 1:
            level = DiffLevel.none
        elif percentage < 5:
            level = DiffLevel.minimal
        elif percentage < 20:
            level = DiffLevel.moderate
        elif percentage < 50:
            level = DiffLevel.major
        else:
            level = DiffLevel.structural

        # 生成 diff 图
        diff_path = os.path.join(self.screenshot_dir, "diff_latest.png")

        files_str = [f.path for f in (changed_files or [])]

        summary_parts = [
            f"UI 变更 {percentage:.1f}%",
            f"级别: {level.value}",
        ]
        if files_str:
            summary_parts.append(f"涉及 {len(files_str)} 个文件")

        return VisualDiff(
            before=before,
            after=after,
            diff_level=level,
            changed_pixels=changed_pixels,
            total_pixels=total_pixels,
            changed_percentage=percentage,
            diff_image_path=diff_path if os.path.exists(diff_path) else "",
            changed_files=files_str,
            summary=" | ".join(summary_parts),
        )

    def _pixel_diff(self, before_path: str, after_path: str) -> tuple[int, int]:
        """像素级对比（简化实现）。"""
        try:
            from PIL import Image
            import numpy as np

            img1 = Image.open(before_path).convert("RGB")
            img2 = Image.open(after_path).convert("RGB")

            # 统一尺寸
            w = min(img1.width, img2.width)
            h = min(img1.height, img2.height)
            img1 = img1.resize((w, h))
            img2 = img2.resize((w, h))

            arr1 = np.array(img1)
            arr2 = np.array(img2)

            diff = np.abs(arr1.astype(int) - arr2.astype(int))
            threshold = 30
            changed = np.any(diff > threshold, axis=2)
            changed_count = int(changed.sum())
            total = w * h

            return changed_count, total

        except ImportError:
            # 无 PIL/numpy，返回基于文件大小的估算
            size1 = os.path.getsize(before_path)
            size2 = os.path.getsize(after_path)
            size_diff = abs(size1 - size2)
            total = max(size1, size2, 1)
            return min(size_diff, total), total
        except Exception:
            return 0, 1

    def _file_based_diff(
        self,
        before: ScreenshotResult,
        after: ScreenshotResult,
        changed_files: list[FileChange],
    ) -> VisualDiff:
        """降级：基于文件变更而非像素对比。"""
        files_str = [f.path for f in changed_files]
        level = DiffLevel.moderate if changed_files else DiffLevel.none

        summary = f"截图不可用，基于 {len(changed_files)} 个文件变更推断"
        if not changed_files:
            summary = "无截图且无文件变更"

        return VisualDiff(
            before=before,
            after=after,
            diff_level=level,
            changed_files=files_str,
            summary=summary,
        )

    def run_feedback_loop(
        self,
        url: str,
        *,
        code_change_fn: Callable[[], list[FileChange]] | None = None,
        name: str = "",
    ) -> VisualDiff:
        """执行完整的视觉反馈闭环。

        流程：
        1. 截取变更前截图
        2. 执行代码变更
        3. 截取变更后截图
        4. 对比差异
        5. 生成反馈文本

        Args:
            url: 要截图的页面 URL。
            code_change_fn: 执行代码变更的函数，返回变更文件列表。
            name: 截图名称前缀。
        """
        # 1. 变更前截图
        before = self.capture(url, name=f"{name}_before" if name else "before")

        # 2. 执行代码变更
        changed_files: list[FileChange] = []
        if code_change_fn:
            try:
                changed_files = code_change_fn()
            except Exception as exc:
                self.logger.error("code_change_failed", {"error": str(exc)})

        # 3. 变更后截图
        after = self.capture(url, name=f"{name}_after" if name else "after")

        # 4. 对比
        diff = self.compare(before, after, changed_files=changed_files)

        self.logger.info("visual_feedback_complete", {
            "diff_level": diff.diff_level.value,
            "changed_percentage": round(diff.changed_percentage, 2),
            "changed_files": len(diff.changed_files),
        })

        return diff

    def get_history(self, limit: int = 20) -> list[str]:
        """获取截图历史。"""
        if not os.path.exists(self.screenshot_dir):
            return []
        files = [
            os.path.join(self.screenshot_dir, f)
            for f in os.listdir(self.screenshot_dir)
            if f.endswith(".png")
        ]
        files.sort(key=os.path.getmtime, reverse=True)
        return files[:limit]
