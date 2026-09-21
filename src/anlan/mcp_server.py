"""Compatibility command entry; internal code uses canonical packages."""
import asyncio

from anlan.interfaces.mcp_server import run

if __name__ == "__main__":
    asyncio.run(run())
