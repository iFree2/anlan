"""Temporary manual DeepSeek test for debugging the complete tool loop."""

from datetime import datetime
from pathlib import Path
from uuid import uuid4

import httpx
import pytest

from anlan.common.models import Identity
from anlan.infrastructure.trace import JsonlTrace
from anlan.interfaces.cli import DEMO_FIELDS
from anlan.llm.config import ModelConfig
from anlan.llm.tool_model import DeepSeekToolModel
from anlan.tools.queries import FactTools
from anlan.workflows.material_analysis import OfflineAnalyzer
from anlan.workflows.service import WorkflowService
from anlan.workflows.tool_loop import LoopLimits, check_facts_agent

OWNER = Identity(tenant_id="synthetic-demo", user_id="safety-manager-demo")
PROJECT_ROOT = Path(__file__).resolve().parents[1]
REFERENCES = {
    "worker_id": "worker-001",
    "qualification_type": "welding",
    "area_id": "area-001",
}


def deepseek_key() -> str:
    """Read the user-provided, git-ignored local credential without logging it."""
    raw = (PROJECT_ROOT / "docs/DS.txt").read_text(encoding="utf-8-sig").strip()
    for line in raw.splitlines():
        name, separator, value = line.partition("=")
        if separator and name.strip() == "DEEPSEEK_API_KEY":
            return value.strip().strip('"').strip("'")
    return raw


class TemporaryDebugLedger:
    """Bound this manually selected debug run to at most three real requests."""

    def __init__(self):
        self.attempts = []

    async def reserve(self, package, run_id):
        if len(self.attempts) >= 3:
            raise RuntimeError("temporary debug request limit reached")
        attempt_id = str(uuid4())
        self.attempts.append({
            "attempt_id": attempt_id,
            "package": package,
            "run_id": run_id,
            "status": "reserved",
        })
        return attempt_id

    async def finish(self, attempt_id, status, usage=None, error=None):
        attempt = next(row for row in self.attempts if row["attempt_id"] == attempt_id)
        attempt.update(status=status, usage=usage, error=error)


@pytest.mark.live_model
async def test_live_deepseek_selects_tools_and_summarizes_results(tmp_path):
    """Make up to three real requests; delete this temporary test after debugging."""
    service = WorkflowService(OfflineAnalyzer())
    before = await service.start(OWNER, DEMO_FIELDS)
    tools = FactTools(
        PROJECT_ROOT / "examples/synthetic/facts-v1",
        clock=lambda: datetime.fromisoformat("2026-09-20T12:00:00+00:00"),
    )
    config = ModelConfig(api_key=deepseek_key(), max_requests=3)
    ledger = TemporaryDebugLedger()

    async with httpx.AsyncClient(follow_redirects=False) as client:
        model = DeepSeekToolModel(
            config,
            client,
            ledger,
            work_package="P2-WP02",
        )
        report = await check_facts_agent(
            service,
            OWNER,
            before["task_id"],
            REFERENCES,
            tools,
            model,
            JsonlTrace(tmp_path / "live-tool-loop.trace.jsonl"),
            # Debugger pauses count as wall-clock time. Bypass the production
            # schema ceiling only in this temporary manual test.
            limits=LoopLimits.model_construct(
                max_model_steps=3,
                max_tool_calls=4,
                timeout_seconds=3600,
            ),
        )

    assert report["stop_reason"] == "completed", report
    assert report["mode"] == "deepseek_live"
    assert 1 <= report["requests_this_run"] <= 3
    assert report["summary_status"] == "unverified_candidate"
    assert report["summary"]["summary"].strip()
    assert {row["tool"] for row in report["results"] if row["executed"]} == {
        "query_worker_qualification",
        "query_area_status",
    }
    assert await service.get(OWNER, before["task_id"]) == before
