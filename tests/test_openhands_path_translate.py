"""M156.13 — OpenHandsWorker._translate_paths_in_text 路径翻译单测。

planner/fail-open 构造的 task_description 含 state.cwd（宿主机路径如
/Users/wangzhenyu/projects/X），但 OpenHands 容器只看到 /projects/X。
不翻译 → Kimi 按 host 路径 mkdir → Permission denied → 浪费所有迭代。

本测试只测 _translate_paths_in_text 静态方法，不依赖 OpenHands SDK
（该方法只用 os + re，无 SDK 导入）。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# 只导入 _translate_paths_in_text 需要的依赖（os, re），绕过 SDK 重依赖
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))


def _get_translate_method():
    """直接从 openhands_worker 模块取 _translate_paths_in_text 类方法。

    避免导入整个 OpenHandsWorker（它会在模块级导入 openhands.sdk）。
    用 importlib + exec 只加载方法定义部分太脆弱，直接 import 模块更可靠。
    如果 openhands.sdk 不可用（CI 环境），跳过本测试。
    """
    try:
        from executor.openhands_worker import OpenHandsWorker
        return OpenHandsWorker._translate_paths_in_text
    except ImportError:
        pytest.skip("openhands.sdk not available", allow_module_level=True)


def test_basic_host_to_container():
    """宿主机 $HOME/projects/X → /projects/X"""
    translate = _get_translate_method()
    home = os.path.expanduser("~")
    host_path = os.path.join(home, "projects", "flipped_smoke")
    result = translate(f"在工作目录 {host_path} 下创建文件")
    assert "/projects/flipped_smoke" in result
    assert host_path not in result


def test_path_with_filename():
    """路径带文件名也被翻译"""
    translate = _get_translate_method()
    home = os.path.expanduser("~")
    host_path = os.path.join(home, "projects", "myapp", "hello.py")
    result = translate(f"Write to {host_path}")
    assert result == f"Write to /projects/myapp/hello.py"


def test_multiple_paths_in_text():
    """文本里多个路径都被翻译"""
    translate = _get_translate_method()
    home = os.path.expanduser("~")
    p1 = os.path.join(home, "projects", "app1")
    p2 = os.path.join(home, "projects", "app2")
    result = translate(f"cd {p1} && cp file {p2}/")
    assert "/projects/app1" in result
    assert "/projects/app2" in result
    assert home not in result


def test_non_projects_path_unchanged():
    """非 $HOME/projects 下的路径不翻译"""
    translate = _get_translate_method()
    result = translate("/tmp/other/path stays")
    assert result == "/tmp/other/path stays"


def test_empty_and_none():
    """空字符串安全处理"""
    translate = _get_translate_method()
    assert translate("") == ""
    assert translate(None) is None  # type: ignore[arg-type]


def test_path_in_quotes():
    """带引号的路径也翻译"""
    translate = _get_translate_method()
    home = os.path.expanduser("~")
    host_path = os.path.join(home, "projects", "app", "file.py")
    result = translate(f"cat '{host_path}'")
    assert result == "cat '/projects/app/file.py'"


def test_no_false_positive_on_similar_prefix():
    """不会误替换 $HOME/projectsX（无斜杠分隔）"""
    translate = _get_translate_method()
    home = os.path.expanduser("~")
    # projects_other 不应被替换为 /projects_other
    fake_path = os.path.join(home, "projects_other", "file")
    result = translate(f"path={fake_path}")
    # projects_other 不匹配 projects/ 前缀，原样保留
    assert fake_path in result
