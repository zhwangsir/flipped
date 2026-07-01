"""flipped MCP Server（stdio 传输）。

入口：
    PYTHONPATH=src .venv/bin/python -m mcp_server
或：
    PYTHONPATH=src .venv/bin/PYTHONPATH=src .venv/bin/python -m mcp_server

编辑器通过 MCP 协议调用：
    - web_search
    - rag_query
    - rag_ingest
    - run_coding_task
    - research_and_code
"""
from __future__ import annotations

import asyncio
import json

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent

from mcp_server.tools import TOOLS, run_tool


def create_server(name: str = "flipped-mcp-server") -> Server:
    server = Server(name)

    @server.list_tools()
    async def list_tools() -> list:
        return TOOLS

    @server.call_tool()
    async def call_tool(name: str, arguments: dict | None) -> list:
        result = await run_tool(name, arguments or {})
        return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False))]

    return server


async def main() -> None:
    server = create_server()
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


if __name__ == "__main__":
    asyncio.run(main())
