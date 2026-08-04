"""M175 · @ 文件引用确定性展开（src/api/file_refs.py）的测试。"""
from __future__ import annotations

from pathlib import Path

import pytest

from api.file_refs import REFS_HEADER, expand_file_refs, parse_file_ref_tokens


# ---------- parse_file_ref_tokens ----------

def test_parse_bare_token():
    assert parse_file_ref_tokens("看下 @src/a.py 这个") == ["@src/a.py"]


def test_parse_quoted_token_with_space():
    assert parse_file_ref_tokens('打开 @"docs/my file.md"') == ['@"docs/my file.md"']


def test_parse_email_not_matched():
    assert parse_file_ref_tokens("联系 user@example.com") == []


def test_parse_at_string_start():
    assert parse_file_ref_tokens("@a.py 看下") == ["@a.py"]


def test_parse_dedup_keeps_first_order():
    assert parse_file_ref_tokens("@b.py @a.py @b.py") == ["@b.py", "@a.py"]


def test_parse_unclosed_quote_not_token():
    assert parse_file_ref_tokens('@"abc') == []


# ---------- expand_file_refs ----------

def test_expand_ok_injects_content(tmp_path: Path):
    (tmp_path / "hello.py").write_text("print('hi')\n", encoding="utf-8")
    expanded, refs = expand_file_refs("看下 @hello.py", tmp_path)
    assert len(refs) == 1
    ref = refs[0]
    assert ref.status == "ok"
    assert ref.path == "hello.py"
    assert ref.bytes > 0
    assert ref.truncated is False
    assert REFS_HEADER in expanded
    assert "### @hello.py" in expanded
    assert "```py" in expanded
    assert "print('hi')" in expanded


def test_expand_missing_file(tmp_path: Path):
    expanded, refs = expand_file_refs("看下 @nope.py", tmp_path)
    assert refs[0].status == "missing"
    assert "文件不存在或不可读" in expanded


def test_expand_directory_is_missing(tmp_path: Path):
    (tmp_path / "adir").mkdir()
    expanded, refs = expand_file_refs("看下 @adir", tmp_path)
    assert refs[0].status == "missing"
    assert "文件不存在或不可读" in expanded


def test_expand_outside_root_rejected(tmp_path: Path):
    proj = tmp_path / "proj"
    proj.mkdir()
    (tmp_path / "outside.txt").write_text("SECRET_OUTSIDE", encoding="utf-8")
    expanded, refs = expand_file_refs("看下 @../outside.txt", proj)
    assert refs[0].status == "outside_root"
    assert "越出项目根" in expanded
    assert "SECRET_OUTSIDE" not in expanded


def test_expand_binary_not_injected(tmp_path: Path):
    (tmp_path / "bin.dat").write_bytes(b"\x00\x01\x02abc")
    expanded, refs = expand_file_refs("看下 @bin.dat", tmp_path)
    assert refs[0].status == "binary"
    assert refs[0].bytes == 0
    assert "二进制" in expanded
    assert "abc" not in expanded.split(REFS_HEADER)[-1]


def test_expand_truncation(tmp_path: Path):
    (tmp_path / "big.txt").write_bytes(b"a" * 40000)
    expanded, refs = expand_file_refs(
        "看下 @big.txt", tmp_path, max_bytes_per_file=1024
    )
    assert refs[0].status == "ok"
    assert refs[0].truncated is True
    assert refs[0].bytes <= 1024
    assert "a" * 2000 not in expanded


def test_expand_max_files_skips_rest(tmp_path: Path):
    for i in range(6):
        (tmp_path / f"f{i}.py").write_text(f"# f{i}\n", encoding="utf-8")
    text = " ".join(f"@f{i}.py" for i in range(6))
    expanded, refs = expand_file_refs(text, tmp_path, max_files=2)
    statuses = [r.status for r in refs]
    assert statuses == ["ok", "ok", "skipped", "skipped", "skipped", "skipped"]
    assert "上限" in expanded


def test_expand_max_total_bytes_skips_rest(tmp_path: Path):
    for i in range(3):
        (tmp_path / f"f{i}.txt").write_bytes(b"x" * 100)
    text = "@f0.txt @f1.txt @f2.txt"
    expanded, refs = expand_file_refs(text, tmp_path, max_total_bytes=200)
    statuses = [r.status for r in refs]
    assert statuses == ["ok", "ok", "skipped"]
    assert "上限" in expanded


def test_expand_root_none_passthrough():
    text = "看下 @a.py"
    assert expand_file_refs(text, None) == (text, [])


def test_expand_no_token_passthrough(tmp_path: Path):
    text = "没有任何引用"
    assert expand_file_refs(text, tmp_path) == (text, [])


def test_expand_all_non_ok_still_has_header(tmp_path: Path):
    expanded, refs = expand_file_refs("看下 @nope.py", tmp_path)
    assert REFS_HEADER in expanded
    assert "### @nope.py（文件不存在或不可读）" in expanded


def test_expand_read_exception_falls_back_to_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")

    def boom(self, *args, **kwargs):
        raise OSError("disk on fire")

    monkeypatch.setattr(Path, "open", boom)
    expanded, refs = expand_file_refs("看下 @a.py", tmp_path)  # 不上抛
    assert refs[0].status == "missing"
    assert "文件不存在或不可读" in expanded
