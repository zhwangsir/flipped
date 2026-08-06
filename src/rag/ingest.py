"""文档 ingest：文件、目录、纯文本 -> 向量库。"""
from __future__ import annotations

import hashlib
import re
import subprocess
from pathlib import Path
from typing import Any

from rag.vector_store import ChromaVectorStore, VectorStore


SUPPORTED_EXTS = {".txt", ".md", ".py", ".json", ".js", ".ts", ".html", ".css", ".yaml", ".yml"}
DEFAULT_CHUNK_SIZE = 800
DEFAULT_CHUNK_OVERLAP = 100
CODE_EXTS = {".py", ".js", ".ts", ".html", ".css", ".yaml", ".yml", ".json"}

_HEADING_RE = re.compile(r"^#{1,6}\s", re.MULTILINE)
_BLANK_RUN_RE = re.compile(r"\n\s*\n+")
# M195.1：fenced code block 围栏行（``` 或 ~~~，可带 info string），消化 L-M171-3
_FENCE_RE = re.compile(r"^\s*(`{3,}|~{3,})")


def _chunk(text: str, chunk_size: int = DEFAULT_CHUNK_SIZE, overlap: int = DEFAULT_CHUNK_OVERLAP) -> list[str]:
    if len(text) <= chunk_size:
        return [text]
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunks.append(text[start:end])
        start += chunk_size - overlap
    return chunks


def _split_markdown(text: str) -> list[str]:
    """按标题行切段，标题行归入其下段首。

    M195.1：fenced code block（```/~~~ 围栏对内）的行首 # 不当标题——
    代码注释/脚本里的 # 是内容不是结构。围栏未闭合时余下全文视为 fence 内
    （保守不切段，避免把代码注释切成碎段）。
    """
    sections: list[str] = []
    current: list[str] = []
    fence_marker: str | None = None  # 非 None = 在 fence 内，值为围栏字符（` 或 ~）
    for line in text.split("\n"):
        m = _FENCE_RE.match(line)
        if m:
            ch = m.group(1)[0]
            if fence_marker is None:
                fence_marker = ch
            elif ch == fence_marker:
                fence_marker = None  # 闭合（同字符围栏；简化不校验长度递增）
            current.append(line)
            continue
        if fence_marker is None and _HEADING_RE.match(line):
            if current:
                sections.append("\n".join(current))
            current = [line]
        else:
            current.append(line)
    if current:
        sections.append("\n".join(current))
    return sections


def _chunk_structured(
    text: str,
    ext: str,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    overlap: int = DEFAULT_CHUNK_OVERLAP,
) -> list[str]:
    """按文档结构分块：markdown 按标题、代码按空行，其余回退 _chunk 硬切。"""
    if ext == ".md":
        sections = _split_markdown(text)
    elif ext in CODE_EXTS:
        sections = _BLANK_RUN_RE.split(text)
    else:
        return _chunk(text, chunk_size, overlap)

    sections = [s for s in sections if s.strip()]
    chunks: list[str] = []

    def emit(buf: str) -> None:
        if len(buf) > chunk_size:
            chunks.extend(_chunk(buf, chunk_size, overlap))
        else:
            chunks.append(buf)

    current = ""
    for sec in sections:
        candidate = f"{current}\n{sec}" if current else sec
        if current and len(candidate) > chunk_size:
            emit(current)
            current = sec
        else:
            current = candidate
    if current:
        emit(current)
    return chunks


def _git_files(base: Path, exts: set[str]) -> list[Path] | None:
    """git repo 内返回 git 清单（含 gitignore 过滤）；任何异常返回 None 回退 rglob。"""
    try:
        probe = subprocess.run(
            ["git", "-C", str(base), "rev-parse", "--is-inside-work-tree"],
            capture_output=True, text=True, timeout=5,
        )
        if probe.returncode != 0 or probe.stdout.strip() != "true":
            return None
        top = subprocess.run(
            ["git", "-C", str(base), "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, timeout=5,
        )
        if top.returncode != 0:
            return None
        toplevel = Path(top.stdout.strip()).resolve()
        listing = subprocess.run(
            ["git", "-C", str(toplevel), "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
            capture_output=True, text=True, timeout=5,
        )
        if listing.returncode != 0:
            return None
        files: list[Path] = []
        for rel in listing.stdout.split("\0"):
            if not rel:
                continue
            p = (toplevel / rel).resolve()
            try:
                p.relative_to(base)
            except ValueError:
                continue
            if p.is_file() and p.suffix.lower() in exts:
                files.append(p)
        return files
    except Exception:
        return None


def _stale_ids(existing: list[dict[str, Any]], keep_hash: str) -> list[str]:
    """返回 existing 中 content_hash 与 keep_hash 不一致（或缺失）的项的 id 列表。"""
    return [
        str(item["id"])
        for item in existing
        if (item.get("metadata") or {}).get("content_hash") != keep_hash
    ]


def ingest_text(text: str, metadata: dict[str, Any] | None = None, *, store: VectorStore | None = None) -> list[str]:
    store = store or ChromaVectorStore()
    docs = [{"text": text, "metadata": metadata or {}}]
    return store.add_documents(docs)


def ingest_file(path: str | Path, *, store: VectorStore | None = None, project: str | None = None) -> list[str]:
    store = store or ChromaVectorStore()
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(path)
    text = p.read_text(encoding="utf-8", errors="ignore")
    if not text.strip():
        return []
    content_hash = hashlib.sha256(text.encode()).hexdigest()[:16]
    chunks = _chunk_structured(text, p.suffix.lower())
    docs = [
        {
            "id": f"{content_hash}:{i}",
            "text": chunk,
            "metadata": {
                "source": str(p.resolve()),
                "ext": p.suffix.lower(),
                "chunk": i,
                "project": project or "",
                "content_hash": content_hash,
            },
        }
        for i, chunk in enumerate(chunks)
    ]
    ids = store.upsert_documents(docs)
    # M189.1：清理同 source 旧 content_hash 的残留 chunk（fail-open，不炸主流程）
    try:
        stale = _stale_ids(store.get_where({"source": str(p.resolve())}), content_hash)
        if stale:
            store.delete_ids(stale)
    except Exception:
        pass
    return ids


def ingest_directory(
    dir_path: str | Path,
    extensions: set[str] | None = None,
    *,
    store: VectorStore | None = None,
    project: str | None = None,
) -> list[str]:
    store = store or ChromaVectorStore()
    exts = extensions or SUPPORTED_EXTS
    base = Path(dir_path).resolve()
    if project is None:
        project = base.name
    files = _git_files(base, exts)
    if files is None:
        files = [p for p in base.rglob("*") if p.is_file() and p.suffix.lower() in exts]
    ids: list[str] = []
    for p in files:
        ids.extend(ingest_file(p, store=store, project=project))
    return ids
