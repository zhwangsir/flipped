"""OpenHandsWorker 宿主机 → 容器内路径转换单测（M10.3 修复）。

worker 写文件到 OpenHands 容器内 `/projects/X`，宿主机 verify_cmd 要读
`$HOME/projects/X` 才能找到同一文件（dev_up.sh 挂载 `$HOME/projects:/projects`）。
"""
from __future__ import annotations

import os

from executor.openhands_worker import OpenHandsWorker


def test_projects_path_translated_to_container():
    home = os.path.expanduser("~")
    host = os.path.join(home, "projects", "flipped_e2e_landing")
    assert OpenHandsWorker._to_container_path(host) == "/projects/flipped_e2e_landing"


def test_projects_root_itself():
    home = os.path.expanduser("~")
    host = os.path.join(home, "projects")
    assert OpenHandsWorker._to_container_path(host) == "/projects"


def test_nested_projects_path():
    home = os.path.expanduser("~")
    host = os.path.join(home, "projects", "a", "b", "c")
    assert OpenHandsWorker._to_container_path(host) == "/projects/a/b/c"


def test_non_projects_path_unchanged():
    """非 $HOME/projects 下的路径原样返回（容器内可能看不到，调用方负责保证可访问）。"""
    assert OpenHandsWorker._to_container_path("/tmp/foo") == "/tmp/foo"
    assert OpenHandsWorker._to_container_path("/var/data") == "/var/data"


def test_empty_path_passthrough():
    assert OpenHandsWorker._to_container_path("") == ""


def test_trailing_slash_normalized():
    home = os.path.expanduser("~")
    host = os.path.join(home, "projects", "x") + "/"
    assert OpenHandsWorker._to_container_path(host) == "/projects/x"


def test_worker_uses_container_path():
    """构造 worker 时传入宿主机 $HOME/projects/X，内部 working_dir 应为容器内路径。"""
    from api.events import EventBus
    from api.session import SessionStore

    home = os.path.expanduser("~")
    host = os.path.join(home, "projects", "flipped_e2e_landing")
    w = OpenHandsWorker("s", "t", EventBus(SessionStore()), working_dir=host)
    assert w.working_dir == "/projects/flipped_e2e_landing"


def test_worker_non_projects_path_unchanged():
    """非挂载点路径原样保留（worker 会在容器内独立 tmpfs 创建）。"""
    from api.events import EventBus
    from api.session import SessionStore

    w = OpenHandsWorker("s", "t", EventBus(SessionStore()), working_dir="/tmp/foo")
    assert w.working_dir == "/tmp/foo"
