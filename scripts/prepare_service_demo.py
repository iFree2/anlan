"""Write an ignored local bearer configuration and synthetic task/source bindings."""

import argparse
import asyncio
import json
import secrets
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4

from anlan.common.models import Identity
from anlan.infrastructure.db import database_url
from anlan.infrastructure.events import EventStore
from anlan.infrastructure.postgres import initialize_database
from anlan.interfaces.runtime import postgres_service
from anlan.knowledge.embeddings import LocalEmbeddings
from anlan.knowledge.store import KnowledgeStore
from anlan.workflows.event_contracts import SourceBinding
from anlan.workflows.material_analysis import OfflineAnalyzer

ROOT = Path(__file__).resolve().parents[1]


async def prepare(output, *, console=False):
    if output.exists():
        raise ValueError("Use a new config path to preserve running service credentials")
    dsn = database_url()
    await initialize_database(dsn)
    await EventStore(dsn).initialize()
    identity = Identity(tenant_id="synthetic-p5-replay", user_id="safety-manager-demo")
    now = datetime.fromisoformat("2026-09-22T04:00:00+00:00")
    data = ROOT / "examples/synthetic/perception-v1"
    store = KnowledgeStore(
        dsn, await LocalEmbeddings.create(ROOT / ".runtime/embeddings"), clock=lambda: now
    )
    await store.initialize()
    for document in json.loads((data / "knowledge.json").read_text(encoding="utf-8"))["documents"]:
        await store.ingest(identity, document)
    fields = {
        "work_location_description": "SYNTHETIC：area-p5-demo台架",
        "work_object_description": "SYNTHETIC：服务启动验证试件",
        "work_method_description": "SYNTHETIC：worker-p5-001焊接演示",
        "attachment_description": "SYNTHETIC：服务验证示意图",
    }
    sources = []
    for kind in ("helmet_missing", "gas_abnormal"):
        async with postgres_service(dsn, OfflineAnalyzer()) as workflow:
            task = await workflow.start(identity, fields)
        binding = SourceBinding(
            identity=identity,
            source_id="http-demo-" + uuid4().hex,
            kind=kind,
            object_ref="area-p5-demo",
            task_id=task["task_id"],
            revision=task["revision"],
            run_id=task["run_id"],
            valid_from=now - timedelta(minutes=1),
            valid_until=now + timedelta(hours=1),
        )
        sources.append(
            {
                "binding": binding.model_dump(mode="json"),
                "references": json.loads((data / "refs.json").read_text(encoding="utf-8")),
            }
        )
    config = {
        "schema_version": "local-service-v1",
        "as_of": now.isoformat(),
        "tokens": [{"token": secrets.token_hex(32), "identity": identity.model_dump()}],
        "sources": sources,
        "facts_dir": str(data / "facts"),
        "embeddings_cache": str(ROOT / ".runtime/embeddings"),
    }
    if console:
        config["console_profiles"] = [{
            "identity": identity.model_dump(),
            "references": json.loads((data / "refs.json").read_text(encoding="utf-8")),
        }]
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as handle:
        json.dump(config, handle, ensure_ascii=False, indent=2)
    return {
        "status": "prepared",
        "config": str(output.resolve()),
        "sources": [s["binding"]["source_id"] for s in sources],
        "credentials_printed": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / ".runtime/service-demo.json")
    args = parser.parse_args()
    print(json.dumps(asyncio.run(prepare(args.output), loop_factory=asyncio.SelectorEventLoop)))


if __name__ == "__main__":
    main()
