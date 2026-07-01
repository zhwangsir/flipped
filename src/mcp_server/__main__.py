"""入口：python -m src.mcp_server"""
from mcp_server.server import main

if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
