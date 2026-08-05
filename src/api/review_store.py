"""M186 · AI 评审历史持久化（纯逻辑零 FastAPI，函数级不 import main）。

记录文件：{reviews_dir}/{project}/{ts:%Y%m%dT%H%M%S}_{uuid8}.json，id = 文件名去
.json；tmp+os.replace 原子写（同 driving.worker_rules 惯例）；写后超
REVIEW_HISTORY_CAP 按文件名升序删最旧。读侧宽松：目录不存在 → []/None；
坏 JSON 跳过不炸；load 的 review_id 含「/」「..」或为空 → None（路径穿越防护）。
"""
from __future__ import annotations

import json
import os
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REVIEW_HISTORY_CAP = 50  # 每项目评审历史上限（条）

_SUMMARY_KEYS = ("id", "ts", "project", "model", "files_reviewed", "findings_count")


def _atomic_write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _read_record(path: Path) -> dict | None:
    """读单条记录；文件不存在/坏 JSON/非对象 → None。"""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _enforce_cap(project_dir: Path) -> None:
    """超 REVIEW_HISTORY_CAP 按文件名升序删最旧（文件名 = ts 前缀 + uuid8）。"""
    try:
        files = sorted(p for p in project_dir.iterdir() if p.suffix == ".json")
    except OSError:
        return
    for p in files[: max(0, len(files) - REVIEW_HISTORY_CAP)]:
        try:
            p.unlink()
        except OSError:
            pass


def save_review(reviews_dir: Path, *, project: str, model: str,
                files_reviewed: int, findings: list[dict]) -> dict:
    """原子写一条评审记录并返回完整记录；写后超 cap 删最旧。"""
    now = datetime.now(timezone.utc)
    rid = f"{now:%Y%m%dT%H%M%S}_{uuid.uuid4().hex[:8]}"
    record = {
        "id": rid,
        "ts": now.isoformat(),
        "project": project,
        "model": model,
        "files_reviewed": files_reviewed,
        "findings_count": len(findings),
        "findings": findings,
    }
    project_dir = Path(reviews_dir) / project
    _atomic_write_json(project_dir / f"{rid}.json", record)
    _enforce_cap(project_dir)
    return record


def list_reviews(reviews_dir: Path, project: str) -> list[dict]:
    """ts desc（文件名降序）的摘要列表（无 findings）；目录不存在 → []；坏文件跳过。"""
    project_dir = Path(reviews_dir) / project
    try:
        names = sorted((p.name for p in project_dir.iterdir() if p.suffix == ".json"),
                       reverse=True)
    except OSError:
        return []
    out: list[dict] = []
    for name in names:
        rec = _read_record(project_dir / name)
        if rec is None:
            continue
        try:
            out.append({k: rec[k] for k in _SUMMARY_KEYS})
        except (KeyError, TypeError):
            continue  # 缺字段的残破记录视同坏文件，跳过不炸
    return out


def load_review(reviews_dir: Path, project: str, review_id: str) -> dict | None:
    """按 id 取完整记录（含 findings）；非法 id/未命中/坏文件 → None。"""
    if not review_id or "/" in review_id or ".." in review_id:
        return None
    return _read_record(Path(reviews_dir) / project / f"{review_id}.json")


__all__ = ["REVIEW_HISTORY_CAP", "save_review", "list_reviews", "load_review"]
