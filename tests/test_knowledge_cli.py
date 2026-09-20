import json
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_knowledge import DOCUMENT, UnitEmbeddings, run
from test_postgres import dsn  # noqa: F401

pytestmark = pytest.mark.postgres


def test_knowledge_cli_ingest_query_withdraw_uses_trusted_identity(
        dsn, monkeypatch, tmp_path, capsys):  # noqa: F811
    from uuid import uuid4

    from anlan import cli
    path = tmp_path / "knowledge.json"
    path.write_text(json.dumps({"documents": [DOCUMENT]}), encoding="utf-8")

    async def fake_embeddings():
        return UnitEmbeddings()

    monkeypatch.setattr(cli, "database_url", lambda: dsn)
    monkeypatch.setattr(cli.LocalEmbeddings, "create", fake_embeddings)
    args = SimpleNamespace(
        command="knowledge-ingest", tenant="cli-knowledge-" + uuid4().hex, user="owner",
        knowledge_file=path, question="监护", strategy="vector", doc_id=DOCUMENT["doc_id"],
        as_of=datetime.fromisoformat("2026-09-20T12:00:00+00:00").isoformat(),
        trace=Path(tmp_path / "trace.jsonl"))
    run(cli.run(args))
    assert json.loads(capsys.readouterr().out)["documents"][0]["chunks"] == 1
    args.command = "knowledge-query"
    run(cli.run(args))
    assert json.loads(capsys.readouterr().out)["outcome"] == "ok"
    args.command = "knowledge-withdraw"
    run(cli.run(args))
    assert json.loads(capsys.readouterr().out)["withdrawn"] is True
    args.command = "knowledge-query"
    run(cli.run(args))
    assert json.loads(capsys.readouterr().out)["outcome"] == "unknown"
