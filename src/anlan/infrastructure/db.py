"""Shared PostgreSQL configuration; never imports workflow assembly."""
import os

from psycopg.conninfo import make_conninfo


def database_url() -> str:
    value = os.environ.get("ANLAN_DATABASE_URL", "").strip()
    if not value:
        raise ValueError("ANLAN_DATABASE_URL 未配置")
    return value

def conninfo(dsn: str) -> str:
    return make_conninfo(dsn, connect_timeout=5,
                         options="-c search_path=anlan_v2 -c statement_timeout=30000")
