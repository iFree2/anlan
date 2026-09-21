import json

import pytest
from test_tool_loop import SequenceModel, scenario

from anlan.llm.tool_model import FinalAnswer, ModelTurn, ScriptedToolModel, ToolCall

QUESTION = "监护人员需要什么安排？"
CHUNK = "0123456789abcdef01234567"
QUOTE = "SYNTHETIC：安排专门监护人员，需人工复核。"


class KnowledgeDouble:
    def __init__(self, unknown=False):
        self.calls = []
        self.unknown = unknown

    async def search(self, identity, parameters):
        self.calls.append((identity, parameters))
        return {
            "outcome": "unknown" if self.unknown else "ok",
            "reason": "no_eligible_evidence" if self.unknown else None,
            "queried_at": "2026-09-20T12:00:00Z",
            "citations": []
            if self.unknown
            else [
                {
                    "chunk_id": CHUNK,
                    "quote": QUOTE,
                    "doc_id": "watcher",
                    "version": 1,
                    "source": "synthetic-policy/watcher",
                    "content_hash": "a" * 64,
                    "document_hash": "b" * 64,
                    "valid_from": "2026-01-01T00:00:00Z",
                    "valid_until": "2027-01-01T00:00:00Z",
                }
            ],
        }


@pytest.mark.parametrize("unknown", [False, True])
async def test_three_tool_chain_preserves_citations_and_unknown(tmp_path, unknown):
    knowledge = KnowledgeDouble(unknown)
    report = await scenario(
        ScriptedToolModel(), tmp_path, knowledge_store=knowledge, knowledge_question=QUESTION
    )
    assert report["stop_reason"] == "completed"
    assert report["tool_calls"] == 3
    assert len(knowledge.calls) == 1
    assert knowledge.calls[0][1] == {"question": QUESTION}
    assert report["results"][-1]["tool"] == "query_knowledge"
    citations = report["summary"]["knowledge_citations"]
    assert citations == ([] if unknown else [{"chunk_id": CHUNK, "quote": QUOTE}])


async def test_knowledge_parameters_cannot_inject_identity(tmp_path):
    knowledge = KnowledgeDouble()
    model = SequenceModel(
        [
            ModelTurn(
                calls=[
                    ToolCall(
                        id="knowledge-1",
                        name="query_knowledge",
                        arguments=json.dumps({"question": QUESTION, "tenant_id": "other"}),
                    )
                ]
            ),
            ModelTurn(final=FinalAnswer(summary="unknown", evidence_call_ids=["knowledge-1"])),
        ]
    )
    report = await scenario(model, tmp_path, knowledge_store=knowledge, knowledge_question=QUESTION)
    assert report["results"][0]["reason"] == "invalid_parameters"
    assert knowledge.calls == []


@pytest.mark.parametrize("bad_chunk,bad_quote", [("unknown-chunk", QUOTE), (CHUNK, "不存在的引用")])
async def test_fabricated_knowledge_citation_is_not_published(tmp_path, bad_chunk, bad_quote):
    class Fabricating(ScriptedToolModel):
        async def next(self, messages, run_id):
            turn = await super().next(messages, run_id)
            if turn.final:
                from anlan.knowledge.contracts import KnowledgeCitation

                turn.final.knowledge_citations = [
                    KnowledgeCitation(chunk_id=bad_chunk, quote=bad_quote)
                ]
            return turn

    report = await scenario(
        Fabricating(), tmp_path, knowledge_store=KnowledgeDouble(), knowledge_question=QUESTION
    )
    assert report["stop_reason"] == "unsupported_knowledge_citation"
    assert report["summary"] is None
    assert len(report["results"]) == 3


async def test_knowledge_failure_is_an_observation_not_loss_of_fact_results(tmp_path):
    class Failed(KnowledgeDouble):
        async def search(self, identity, parameters):
            raise OSError("source unavailable")

    report = await scenario(
        ScriptedToolModel(), tmp_path, knowledge_store=Failed(), knowledge_question=QUESTION
    )
    assert report["stop_reason"] == "completed"
    assert report["results"][-1]["reason"] == "knowledge_unavailable"
    assert report["results"][0]["outcome"] == "ok"


async def test_onnx_failure_is_kept_as_knowledge_error(tmp_path):
    from onnxruntime.capi.onnxruntime_pybind11_state import Fail

    class Failed(KnowledgeDouble):
        async def search(self, identity, parameters):
            raise Fail("native-inference-error-sentinel")

    report = await scenario(ScriptedToolModel(), tmp_path, knowledge_store=Failed(),
                            knowledge_question=QUESTION)
    assert report["results"][-1]["reason"] == "knowledge_unavailable"
    assert report["results"][0]["outcome"] == "ok"
    assert "native-inference-error-sentinel" not in json.dumps(report)
