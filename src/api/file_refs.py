"""chat/plan 的 @ 文件引用确定性展开：解析 @token + 安全注入文件内容（fail-open，不调 LLM/git/网络）。"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

REFS_HEADER = "以下是用户通过 @ 显式引用的项目文件内容："

_BINARY_SNIFF_BYTES = 8192

_STATUS_NOTES = {
    "missing": "文件不存在或不可读",
    "binary": "二进制文件，未注入内容",
    "outside_root": "路径越出项目根，已拒绝",
    "skipped": "超出引用数量或总量上限",
}


@dataclass
class FileRef:
    """单个 @ 引用的处理结果。"""

    token: str  # 原始 token 原文（含 @ 前缀；引号形式含引号）
    path: str  # 解析出的项目相对路径（posix 分隔）
    status: str  # "ok"|"missing"|"binary"|"outside_root"|"skipped"
    bytes: int = 0  # status=ok 时实际注入字节数（截断后）
    truncated: bool = False


def parse_file_ref_tokens(text: str) -> list[str]:
    """按出现顺序提取 @token（去重保首现序）。

    规则：
    - @ 必须位于字符串开头，或前置字符为空白（"user@example.com" 不命中）；
    - 引号形式：@"..." —— 引号内可含空格等任意字符（不支持转义，读到下一个 " 为止；
      若无闭合引号则不视为 token）；
    - 裸形式：@ 后连续「非空白且非 @」字符（至少 1 个）；
    - 返回值含 @ 前缀的 token 原文列表（引号形式整体含引号）。
    """
    tokens: list[str] = []
    seen: set[str] = set()
    i, n = 0, len(text)
    while i < n:
        if text[i] != "@" or (i > 0 and not text[i - 1].isspace()):
            i += 1
            continue
        j = i + 1
        if j < n and text[j] == '"':  # 引号形式
            end = text.find('"', j + 1)
            if end == -1:  # 无闭合引号 → 不算 token
                i = j + 1
                continue
            token = text[i : end + 1]
            i = end + 1
        else:  # 裸形式
            k = j
            while k < n and not text[k].isspace() and text[k] != "@":
                k += 1
            if k == j:  # @ 后无有效字符
                i = j
                continue
            token = text[i:k]
            i = k
        if token not in seen:
            seen.add(token)
            tokens.append(token)
    return tokens


def _read_file_ref(
    p: Path, token: str, rel: str, max_bytes_per_file: int
) -> tuple[FileRef, str | None]:
    """读取并判定单个文件，返回 (ref, content)。任何异常 → missing 兜底。"""
    try:
        with p.open("rb") as fh:
            raw = fh.read(max_bytes_per_file + 1)
        if b"\x00" in raw[:_BINARY_SNIFF_BYTES]:
            return FileRef(token, rel, "binary"), None
        truncated = len(raw) > max_bytes_per_file
        payload = raw[:max_bytes_per_file]
        try:
            content = payload.decode("utf-8")
        except UnicodeDecodeError:
            if not truncated:  # 完整文件却解不出 utf-8 → 视为二进制
                return FileRef(token, rel, "binary"), None
            content = payload.decode("utf-8", errors="replace")  # 截断处可能切断多字节字符
        return (
            FileRef(token, rel, "ok", bytes=len(payload), truncated=truncated),
            content,
        )
    except Exception:
        return FileRef(token, rel, "missing"), None


def expand_file_refs(
    text: str,
    root: Path | None,
    *,
    max_files: int = 5,
    max_bytes_per_file: int = 32768,
    max_total_bytes: int = 65536,
) -> tuple[str, list[FileRef]]:
    """返回 (expanded_text, refs)。root is None 或无 token → 原样返回 (text, [])。"""
    tokens = parse_file_ref_tokens(text)
    if root is None or not tokens:
        return text, []

    root_resolved = root.resolve()
    refs: list[FileRef] = []
    contents: list[str | None] = []
    ok_count = 0
    total_bytes = 0

    for token in tokens:
        rel = token[2:-1] if token.startswith('@"') else token[1:]
        # 安全检查：resolve 后必须仍在项目根内
        try:
            p = (root_resolved / rel).resolve()
        except OSError:
            refs.append(FileRef(token, rel, "missing"))
            contents.append(None)
            continue
        if not p.is_relative_to(root_resolved):
            refs.append(FileRef(token, rel, "outside_root"))
            contents.append(None)
            continue
        if not p.is_file():  # 不存在或是目录等
            refs.append(FileRef(token, rel, "missing"))
            contents.append(None)
            continue
        if ok_count >= max_files or total_bytes >= max_total_bytes:
            refs.append(FileRef(token, rel, "skipped"))
            contents.append(None)
            continue
        ref, content = _read_file_ref(p, token, rel, max_bytes_per_file)
        if ref.status == "ok":
            ok_count += 1
            total_bytes += ref.bytes
        refs.append(ref)
        contents.append(content)

    if not refs:
        return text, []

    parts = [text, "", REFS_HEADER]
    for ref, content in zip(refs, contents):
        if ref.status == "ok" and content is not None:
            ext = Path(ref.path).suffix.lstrip(".")
            body = content if content.endswith("\n") else content + "\n"
            parts.append(f"### @{ref.path}\n```{ext}\n{body}```")
        else:
            parts.append(f"### @{ref.path}（{_STATUS_NOTES[ref.status]}）")
    return "\n".join(parts), refs
