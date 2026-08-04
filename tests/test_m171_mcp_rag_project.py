"""M171 B 队 · MCP 工具层 rag_query/rag_ingest project 过滤契约 TDD 测试。

契约（A 队并行实现，本测试全部走 monkeypatch 隔离，不 import 真实现跑真摄入）：
- rag_query 带 project → store.query(..., filter={"project": project})
- rag_query 不带 project → filter 为 None
- rag_ingest 带 project + paths → ingest_file/ingest_directory 收到 project=...
- rag_ingest 带 project + text → ingest_text 的 metadata 含 project
- 调用方 metadata 显式含 project → 不被 arguments.project 覆盖（调用方优先）
- inputSchema 内省：rag_query/rag_ingest properties 含 project 字段（防回归）
"""
from __future__ import annotations

import pytest

from mcp_server import tools


@pytest.fixture()
def fake_store(monkeypatch):
    """钉住 tools 模块内 ChromaVectorStore 引用，返回查询调用记录。"""
    calls: dict = {}

    class FakeStore:
        def __init__(self):
            pass

        def query(self, query, n_results=5, filter=None):
            calls["query"] = query
            calls["n_results"] = n_results
            calls["filter"] = filter
            return [{"id": "c1", "text": "hit", "metadata": {"project": "flipped"}}]

    monkeypatch.setattr(tools, "ChromaVectorStore", FakeStore)
    return calls


# ---------- rag_query ----------

@pytest.mark.asyncio
async def test_rag_query_with_project_passes_filter(fake_store):
    result = await tools.run_tool("rag_query", {"query": "q", "n_results": 3, "project": "flipped"})
    assert fake_store["filter"] == {"project": "flipped"}
    assert fake_store["n_results"] == 3
    assert result == {"results": [{"id": "c1", "text": "hit", "metadata": {"project": "flipped"}}]}


@pytest.mark.asyncio
async def test_rag_query_without_project_filter_is_none(fake_store):
    result = await tools.run_tool("rag_query", {"query": "q"})
    assert fake_store["filter"] is None
    assert "results" in result


# ---------- rag_ingest ----------

@pytest.mark.asyncio
async def test_rag_ingest_with_project_and_paths(monkeypatch, tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("hello")
    calls: dict = {}

    def fake_ingest_file(path, store=None, project=None):
        calls.setdefault("file", []).append({"path": path, "project": project})
        return ["id-file"]

    monkeypatch.setattr(tools, "ingest_file", fake_ingest_file)
    monkeypatch.setattr(tools, "ChromaVectorStore", lambda: object())

    result = await tools.run_tool("rag_ingest", {"paths": [str(f)], "project": "flipped"})
    assert calls["file"][0]["project"] == "flipped"
    assert result == {"ingested_ids": ["id-file"], "count": 1}


@pytest.mark.asyncio
async def test_rag_ingest_with_project_and_directory(monkeypatch, tmp_path):
    calls: dict = {}

    def fake_ingest_directory(path, store=None, project=None):
        calls["dir"] = {"path": path, "project": project}
        return ["id-dir"]

    monkeypatch.setattr(tools, "ingest_directory", fake_ingest_directory)
    monkeypatch.setattr(tools, "ChromaVectorStore", lambda: object())

    result = await tools.run_tool("rag_ingest", {"paths": [str(tmp_path)], "project": "flipped"})
    assert calls["dir"]["project"] == "flipped"
    assert result["count"] == 1


@pytest.mark.asyncio
async def test_rag_ingest_with_project_and_text_merges_metadata(monkeypatch):
    captured: dict = {}

    def fake_ingest_text(text, metadata=None, store=None):
        captured["metadata"] = dict(metadata or {})
        return ["id-text"]

    monkeypatch.setattr(tools, "ingest_text", fake_ingest_text)
    monkeypatch.setattr(tools, "ChromaVectorStore", lambda: object())

    result = await tools.run_tool("rag_ingest",
                                  {"text": "note", "project": "flipped",
                                   "metadata": {"source": "manual"}})
    assert captured["metadata"]["project"] == "flipped"
    assert captured["metadata"]["source"] == "manual"
    assert result == {"ingested_ids": ["id-text"], "count": 1}


@pytest.mark.asyncio
async def test_rag_ingest_caller_metadata_project_wins(monkeypatch):
    """调用方显式传的 metadata["project"] 优先，不被 arguments.project 覆盖。"""
    captured: dict = {}

    def fake_ingest_text(text, metadata=None, store=None):
        captured["metadata"] = dict(metadata or {})
        return ["id-text"]

    monkeypatch.setattr(tools, "ingest_text", fake_ingest_text)
    monkeypatch.setattr(tools, "ChromaVectorStore", lambda: object())

    await tools.run_tool("rag_ingest",
                         {"text": "note", "project": "flipped",
                          "metadata": {"project": "caller-specified"}})
    assert captured["metadata"]["project"] == "caller-specified"


# ---------- inputSchema 内省（防回归） ----------

def test_input_schema_rag_query_has_project_property():
    tool = next(t for t in tools.TOOLS if t.name == "rag_query")
    props = tool.inputSchema["properties"]
    assert "project" in props
    assert props["project"]["type"] == "string"
    assert tool.inputSchema["required"] == ["query"]


def test_input_schema_rag_ingest_has_project_property():
    tool = next(t for t in tools.TOOLS if t.name == "rag_ingest")
    props = tool.inputSchema["properties"]
    assert "project" in props
    assert props["project"]["type"] == "string"
    assert "required" not in tool.inputSchema
