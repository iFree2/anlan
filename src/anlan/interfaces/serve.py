"""Start the local synthetic API with a Psycopg-compatible asyncio loop."""

import argparse
import asyncio
from pathlib import Path

import uvicorn

from anlan.infrastructure.db import database_url
from anlan.interfaces.api import create_app
from anlan.interfaces.service_config import ServiceConfig


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--host", default="127.0.0.1", choices=["127.0.0.1", "0.0.0.0"])
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("port must be 1..65535")
    try:
        app = create_app(database_url(), ServiceConfig.from_file(args.config))
        server = uvicorn.Server(
            uvicorn.Config(
                app, host=args.host, port=args.port, access_log=False, log_level="warning"
            )
        )
        asyncio.run(server.serve(), loop_factory=asyncio.SelectorEventLoop)
    except (ValueError, OSError):
        parser.exit(2, "服务配置无效或监听失败；凭据和配置正文已隐藏。\n")


if __name__ == "__main__":
    main()
