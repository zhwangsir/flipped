"""活动项目状态。

flipped 是工具本体(像 Codex),用户用它开发**别的**项目。项目不是 flipped 自己的仓库,
而是放在项目主目录 `~/projects/<名>` 下、由用户导入/新建的文件夹。

关键:host 路径与沙盒路径的对应
  host   `~/projects/<名>`   ← 文件树 / 审查 / 终端(后端在宿主机上读)
  sandbox `/projects/<名>`   ← agent working_dir(OpenHands 容器内执行)
两者由 dev_up.sh 的 `-v $HOME/projects:/projects` 绑定挂载 1:1 对应。

默认**无活动项目**(而非 flipped 仓库);用户需先导入/新建。
放独立模块避免 main.py ↔ terminal.py 循环导入。
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional, TypedDict

# 项目主目录(host)。与沙盒挂载一致,可经 env 覆盖(同时需调整 dev_up.sh 挂载)。
PROJECTS_DIR = Path(
    os.environ.get("FLIPPED_PROJECTS_DIR", str(Path.home() / "projects"))
).expanduser()
# 沙盒内项目根(容器里 /projects,dev_up.sh 挂载点)。
SANDBOX_PROJECTS = os.environ.get("FLIPPED_SANDBOX_PROJECTS", "/projects")
# 无项目时 agent 的回退工作目录。
_FALLBACK_SANDBOX_CWD = "/workspace"


class Project(TypedDict):
    name: str
    host: str      # ~/projects/<名>
    sandbox: str   # /projects/<名>


_ACTIVE: dict[str, Optional[Project]] = {"project": None}


def _to_project(host: Path) -> Project:
    name = host.name
    return {"name": name, "host": str(host), "sandbox": f"{SANDBOX_PROJECTS}/{name}"}


def active_project() -> Optional[Project]:
    return _ACTIVE["project"]


def project_root() -> Optional[Path]:
    """活动项目的 host 路径(文件树/审查/终端);无项目返回 None。"""
    p = _ACTIVE["project"]
    return Path(p["host"]) if p else None


def sandbox_cwd() -> str:
    """活动项目在沙盒里的路径(agent working_dir);无项目回退 /workspace。"""
    p = _ACTIVE["project"]
    return p["sandbox"] if p else _FALLBACK_SANDBOX_CWD


def set_active(host: Path) -> Project:
    proj = _to_project(host)
    _ACTIVE["project"] = proj
    return proj


def clear_active() -> None:
    _ACTIVE["project"] = None


def list_projects() -> list[Project]:
    """列出项目主目录下的项目(子文件夹)。"""
    try:
        PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
        return [
            _to_project(p)
            for p in sorted(PROJECTS_DIR.iterdir(), key=lambda x: x.name.lower())
            if p.is_dir() and not p.name.startswith(".")
        ]
    except OSError:
        return []


def is_within_projects(host: Path) -> bool:
    try:
        host.resolve().relative_to(PROJECTS_DIR.resolve())
        return True
    except (ValueError, OSError):
        return False
