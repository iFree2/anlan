"""Real Java HTTP and official MCP stdio integrated with the existing PG/P4 read-only path."""

import argparse
import asyncio
import copy
import json
from datetime import datetime
from importlib.metadata import version
from pathlib import Path

from bridge_support import bridge_stack

from anlan.common.models import Identity
from anlan.infrastructure.budget import BudgetLedger
from anlan.infrastructure.db import database_url
from anlan.interfaces.runtime import postgres_service
from anlan.knowledge.embeddings import LocalEmbeddings
from anlan.knowledge.store import KnowledgeStore
from anlan.llm.evidence_review import ScriptedEvidenceModel
from anlan.llm.review_model import ScriptedReviewModel
from anlan.memory.store import MemoryStore
from anlan.tools.mcp import mcp_fact_tools
from anlan.tools.queries import FactTools
from anlan.workflows.material_analysis import OfflineAnalyzer
from anlan.workflows.multi_review import multi_review
from anlan.workflows.parallel import canonical_observations, collect_parallel


async def evaluate(args):
    source = json.loads(args.source.read_text(encoding="utf-8"))
    originals = [r for r in source["results"] if r["arm"] == "parallel"]
    identity = Identity.model_validate(originals[0]["bundle"]["identity"])
    now = datetime.fromisoformat(source["as_of"])
    facts_dir = args.source.with_suffix(".facts")
    ledger = BudgetLedger(database_url())
    report = {"status": "running", "data_origin": "SYNTHETIC", "mode": "real_java_mcp_scripted",
              "sdk_version": version("mcp"), "requests_this_run": 0, "cases": []}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as output:
        def save():
            output.seek(0)
            json.dump(report, output, ensure_ascii=False, indent=2)
            output.truncate()
            output.flush()
        save()
        try:
            report["budget_before"] = await ledger.snapshot()
            embeddings = await LocalEmbeddings.create()
            knowledge = KnowledgeStore(database_url(), embeddings, clock=lambda: now)
            memory = MemoryStore(database_url(), clock=lambda: now)
            with bridge_stack(facts_dir, identity, now, Path(".runtime/java-api-classes")) as stack:
                async with mcp_fact_tools(stack.url, stack.token, identity, now) as (
                    remote_tools, session, info
                ):
                    report["mcp_initialization"] = info.model_dump(mode="json")
                    report["tools"] = (await session.list_tools()).model_dump(mode="json")
                    async with postgres_service(database_url(), OfflineAnalyzer()) as service:
                        for original in originals:
                            old = original["bundle"]
                            refs = old["collection"]["children"][0]["input"]["parameters"]
                            bundles = []
                            for tools in (FactTools(facts_dir, clock=lambda: now), remote_tools):
                                bundles.append(await collect_parallel(service, identity,
                                    old["snapshot"]["task_id"], refs, old["question"], tools,
                                    knowledge, memory))
                            equal = canonical_observations(bundles[0]["observations"]) == (
                                canonical_observations(bundles[1]["observations"]))
                            normalized = copy.deepcopy(bundles[1])
                            normalized["observations"] = canonical_observations(
                                normalized["observations"])
                            result = await multi_review(normalized, ScriptedReviewModel(),
                                                         ScriptedEvidenceModel())
                            row = {"case_id": original["case_id"], "direct": bundles[0],
                                   "mcp": bundles[1], "same_evidence": equal, "review": result,
                                   "material_unchanged": await service.get(identity,
                                       old["snapshot"]["task_id"]) == old["snapshot"]}
                            report["cases"].append(row)
                            save()
                            if (not equal or result["stop_reason"] != "completed"
                                    or result["model_steps"] != 2 or not row["material_unchanged"]):
                                raise ValueError("Bridge changed evidence or failed the P4 path")
            report["owned_java_process_stopped"] = stack.process.poll() is not None
            report["budget_after"] = await ledger.snapshot()
            if report["budget_before"] != report["budget_after"] or len(report["cases"]) != 3:
                raise ValueError("Unexpected ledger change or incomplete cases")
            report["status"] = "completed"
        except Exception as exc:
            report.update(status="failed", error_category=type(exc).__name__)
        finally:
            save()
    print(json.dumps({"status": report["status"], "cases": len(report["cases"])}))
    return 0 if report["status"] == "completed" else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    raise SystemExit(asyncio.run(evaluate(parser.parse_args()),
                                loop_factory=asyncio.SelectorEventLoop))
