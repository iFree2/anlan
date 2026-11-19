"""Bounded fixture access and instrumentation forwarding to native APIs."""

import hashlib
import json
from pathlib import Path

from anlan.infrastructure.trace import JsonlTrace
from anlan.llm.tool_model import FinalAnswer, ModelTurn, ScriptedToolModel, ToolCall
from anlan.tools.queries import FactTools

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURE_ROOT = REPO_ROOT / "evals/enterprise-eval-v2/runner-v1"


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def canonical(value) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()


def fixture_path(relative: str) -> Path:
    path = Path(relative)
    root = FIXTURE_ROOT.resolve()
    if path.is_absolute() or ".." in path.parts:
        raise ValueError("path outside trusted fixture root")
    resolved = (root / path).resolve()
    if not resolved.is_relative_to(root):
        raise ValueError("path outside trusted fixture root")
    return resolved


class TraceCapture:
    """Explicit exporter: local file only, never inspect environment OTLP settings."""

    def __init__(self, stream, binding):
        self.stream = stream
        self.binding = binding

    def event(self, producer, payload):
        self.stream.write(
            json.dumps(
                {**self.binding, "producer": producer, "payload": payload}, ensure_ascii=False
            )
            + "\n"
        )
        self.stream.flush()

    def export(self, record):
        self.event("native", record)
        return True

    def native_trace(self):
        return JsonlTrace(exporter=self)


class RecordedModel:
    mode = "scripted_double"

    def __init__(self, case_id, counts, calls):
        self.case_id, self.counts, self.calls = case_id, counts, calls
        self.base = ScriptedToolModel()

    async def next(self, messages, run_id):
        self.counts["model"] += 1
        if self.case_id.endswith("outside-ref"):
            if self.counts["model"] == 1:
                turn = ModelTurn(
                    calls=[
                        ToolCall(
                            id="outside",
                            name="query_area_status",
                            arguments='{"area_id":"area-outside"}',
                        )
                    ]
                )
            else:
                turn = ModelTurn(
                    final=FinalAnswer(
                        summary="SYNTHETIC 候选，待人工复核", evidence_call_ids=["outside"]
                    )
                )
        elif self.case_id.endswith("bad-citation") and self.counts["model"] == 2:
            turn = ModelTurn(
                final=FinalAnswer(
                    summary="SYNTHETIC 不支持引用刺激，非发布输出",
                    evidence_call_ids=["invented-call"],
                )
            )
        else:
            turn = await self.base.next(messages, run_id)
        self.calls.append(
            {"kind": "scripted_turn", "run_id": run_id, "turn": turn.model_dump(mode="json")}
        )
        return turn


class RecordedTools(FactTools):
    def __init__(self, fixed_at, fault, counts, calls):
        async def reader(path):
            # Enforce each resolved file, including any reparse-point targets.
            resolved = fixture_path("facts/" + path.name)
            if path.resolve() != resolved:
                raise ValueError("unexpected fixture path")
            counts["reader"] += 1
            calls.append({"kind": "reader", "file": path.name})
            if fault and path.name == "qualifications.json":
                raise OSError("SYNTHETIC injected source read failure")
            return resolved.read_bytes()

        super().__init__(fixture_path("facts"), clock=lambda: fixed_at, reader=reader)
        self.counts, self.calls = counts, calls

    async def query_worker_qualification(self, identity, parameters):
        self.counts["handler"] += 1
        self.calls.append({"kind": "handler", "tool": "query_worker_qualification"})
        return await super().query_worker_qualification(identity, parameters)

    async def query_area_status(self, identity, parameters):
        self.counts["handler"] += 1
        self.calls.append({"kind": "handler", "tool": "query_area_status"})
        return await super().query_area_status(identity, parameters)
