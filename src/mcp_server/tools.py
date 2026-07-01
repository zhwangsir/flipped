"""MCP 工具实现。"""
from __future__ import annotations

import asyncio
import os
from typing import Any

from mcp.types import Tool

from driving.orchestrator import drive_orchestrated
from driving.researcher import gather
from rag.ingest import ingest_directory, ingest_file, ingest_text
from rag.vector_store import ChromaVectorStore
from tools.web_search import format_for_llm, search as web_search


TOOLS: list[Tool] = [
    Tool(
        name="web_search",
        description="Search the web via SearXNG and return formatted results with sources.",
        inputSchema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "max_results": {"type": "integer", "default": 5},
            },
            "required": ["query"],
        },
    ),
    Tool(
        name="rag_query",
        description="Query the local RAG vector store for private knowledge.",
        inputSchema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Query text"},
                "n_results": {"type": "integer", "default": 5},
            },
            "required": ["query"],
        },
    ),
    Tool(
        name="rag_ingest",
        description="Ingest documents (files, directories, or raw text) into the RAG vector store.",
        inputSchema={
            "type": "object",
            "properties": {
                "paths": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Files or directories to ingest",
                },
                "text": {"type": "string", "description": "Raw text to ingest"},
                "metadata": {"type": "object", "description": "Optional metadata for raw text"},
            },
        },
    ),
    Tool(
        name="run_coding_task",
        description="Run a coding task through the flipped orchestrator (Supervisor/Worker/Overseer/Verify).",
        inputSchema={
            "type": "object",
            "properties": {
                "goal": {"type": "string", "description": "Task description"},
                "verify_cmd": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Verification command",
                    "default": ["pytest", "-q"],
                },
                "cwd": {"type": "string", "description": "Working directory", "default": "."},
            },
            "required": ["goal"],
        },
    ),
    Tool(
        name="research_and_code",
        description="Research a topic using web search and RAG, then generate and verify code.",
        inputSchema={
            "type": "object",
            "properties": {
                "research_query": {"type": "string", "description": "Topic to research"},
                "coding_task": {"type": "string", "description": "Code generation task to run after research"},
                "verify_cmd": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Verification command",
                    "default": ["pytest", "-q"],
                },
                "cwd": {"type": "string", "description": "Working directory", "default": "."},
            },
            "required": ["research_query", "coding_task"],
        },
    ),
]


async def run_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    if name == "web_search":
        return await _web_search(arguments)
    if name == "rag_query":
        return await _rag_query(arguments)
    if name == "rag_ingest":
        return await _rag_ingest(arguments)
    if name == "run_coding_task":
        return await _run_coding_task(arguments)
    if name == "research_and_code":
        return await _research_and_code(arguments)
    raise ValueError(f"Unknown tool: {name}")


async def _web_search(arguments: dict[str, Any]) -> dict[str, Any]:
    query = arguments.get("query", "")
    max_results = int(arguments.get("max_results", 5))
    try:
        results = web_search(query, max_results=max_results)
        return {"results": results, "formatted": format_for_llm(results)}
    except Exception as e:
        return {"error": str(e), "results": [], "formatted": ""}


async def _rag_query(arguments: dict[str, Any]) -> dict[str, Any]:
    query = arguments.get("query", "")
    n_results = int(arguments.get("n_results", 5))
    store = ChromaVectorStore()
    results = store.query(query, n_results=n_results)
    return {"results": results}


async def _rag_ingest(arguments: dict[str, Any]) -> dict[str, Any]:
    paths = arguments.get("paths") or []
    text = arguments.get("text", "")
    metadata = arguments.get("metadata") or {}
    store = ChromaVectorStore()
    ids: list[str] = []
    if text:
        ids.extend(ingest_text(text, metadata=metadata, store=store))
    for path in paths:
        p = os.path.expanduser(path)
        if os.path.isdir(p):
            ids.extend(ingest_directory(p, store=store))
        elif os.path.isfile(p):
            ids.extend(ingest_file(p, store=store))
    return {"ingested_ids": ids, "count": len(ids)}


async def _run_coding_task(arguments: dict[str, Any]) -> dict[str, Any]:
    goal = arguments.get("goal", "")
    cwd = arguments.get("cwd", ".")
    verify_cmd = arguments.get("verify_cmd") or ["pytest", "-q"]
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, lambda: drive_orchestrated(goal, cwd, verify_cmd))
    return {
        "verified": result.get("verified", False),
        "stop_reason": result.get("stop_reason", ""),
        "history": result.get("history", []),
    }


async def _research_and_code(arguments: dict[str, Any]) -> dict[str, Any]:
    research_query = arguments.get("research_query", "")
    coding_task = arguments.get("coding_task", "")
    cwd = arguments.get("cwd", ".")
    verify_cmd = arguments.get("verify_cmd") or ["pytest", "-q"]

    # Research phase
    context = await asyncio.to_thread(gather, research_query)

    # Coding phase with research context prepended
    augmented_goal = f"{coding_task}\n\n相关背景:\n{context}"
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, lambda: drive_orchestrated(augmented_goal, cwd, verify_cmd))
    return {
        "research_query": research_query,
        "coding_task": coding_task,
        "context": context,
        "verified": result.get("verified", False),
        "stop_reason": result.get("stop_reason", ""),
        "history": result.get("history", []),
    }
