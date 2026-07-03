"""活动项目根的共享状态。

「项目名」与「文件夹路径」解耦：默认项目根 = 后端所在仓库，用户可经
POST /project/open 选择/导入其它文件夹。文件树 / 审查 / 终端 / 读取均作用于此活动路径。
放在独立模块避免 main.py ↔ terminal.py 循环导入。
"""
from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
_ACTIVE: dict[str, Path] = {"path": REPO_ROOT}


def project_root() -> Path:
    return _ACTIVE["path"]


def set_project_root(p: Path) -> None:
    _ACTIVE["path"] = p
