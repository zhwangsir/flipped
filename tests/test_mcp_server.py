"""MCP Server 工具单元测试（注入依赖，避免真网络/LLM）。"""
from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

from mcp_server.server import create_server
from mcp_server.tools import run_tool


def test_create_server() -> None:
    server = create_server("test")
    assert server is not None


def test_web_search(monkeypatch) -> None:
    mock = MagicMock(return_value=[{"title": "t", "url": "http://x", "snippet": "s"}])
    monkeypatch.setattr("mcp_server.tools.web_search", mock)

    result = asyncio.run(run_tool("web_search", {"query": "python", "max_results": 2}))

    assert "results" in result
    assert "formatted" in result
    mock.assert_called_once_with("python", max_results=2)


def test_rag_query(monkeypatch) -> None:
    mock_store = MagicMock()
    mock_store.query.return_value = [{"text": "doc", "metadata": {}, "distance": 0.5}]
    monkeypatch.setattr("mcp_server.tools.ChromaVectorStore", lambda: mock_store)

    result = asyncio.run(run_tool("rag_query", {"query": "python", "n_results": 3}))

    assert result["results"][0]["text"] == "doc"
    mock_store.query.assert_called_once_with("python", n_results=3)


def test_rag_ingest(monkeypatch) -> None:
    mock_store = MagicMock()
    mock_store.add_documents.return_value = ["id1"]
    monkeypatch.setattr("mcp_server.tools.ChromaVectorStore", lambda: mock_store)

    result = asyncio.run(run_tool("rag_ingest", {"text": "hello", "metadata": {"k": "v"}}))

    assert result["count"] == 1
    assert result["ingested_ids"] == ["id1"]
    mock_store.add_documents.assert_called_once()


def test_run_coding_task(monkeypatch) -> None:
    mock = MagicMock(return_value={
        "verified": True, "stop_reason": "verified", "history": [{"step": "worker"}]
    })
    monkeypatch.setattr("mcp_server.tools.drive_orchestrated", mock)

    result = asyncio.run(run_tool("run_coding_task", {
        "goal": "write a test",
        "cwd": "/tmp",
        "verify_cmd": ["pytest", "-q"],
    }))

    assert result["verified"] is True
    assert result["stop_reason"] == "verified"
    mock.assert_called_once()


def test_research_and_code(monkeypatch) -> None:
    mock_gather = MagicMock(return_value="research context")
    mock_drive = MagicMock(return_value={
        "verified": True, "stop_reason": "verified", "history": []
    })
    monkeypatch.setattr("mcp_server.tools.gather", mock_gather)
    monkeypatch.setattr("mcp_server.tools.drive_orchestrated", mock_drive)

    result = asyncio.run(run_tool("research_and_code", {
        "research_query": "python testing",
        "coding_task": "write a pytest test",
        "cwd": "/tmp",
        "verify_cmd": ["pytest", "-q"],
    }))

    assert result["verified"] is True
    assert "research context" in result["context"]
    assert "write a pytest test" in mock_drive.call_args.args[0]
    mock_gather.assert_called_once_with("python testing")
    mock_drive.assert_called_once()
