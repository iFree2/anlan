"""Application composition: registry and checkpoint share one dedicated connection."""
from contextlib import asynccontextmanager

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg import AsyncConnection
from psycopg.rows import dict_row

from anlan.infrastructure.db import conninfo
from anlan.infrastructure.postgres import PostgresRegistry, checkpoint_serde
from anlan.infrastructure.trace import JsonlTrace
from anlan.workflows.material_analysis import Analyzer
from anlan.workflows.service import WorkflowService


@asynccontextmanager
async def postgres_service(dsn: str, analyzer: Analyzer, trace: JsonlTrace | None = None, *,
                           mode: str = "offline"):
    async with await AsyncConnection.connect(
        conninfo(dsn), autocommit=True, row_factory=dict_row, prepare_threshold=0,
    ) as connection:
        # Lock and checkpoint writes share the same DB session. Losing the lock connection
        # must also prevent the stale worker from writing through a second live connection.
        saver = AsyncPostgresSaver(connection, serde=checkpoint_serde())
        yield WorkflowService(analyzer, trace, registry=PostgresRegistry(connection),
                              checkpointer=saver, mode=mode)
