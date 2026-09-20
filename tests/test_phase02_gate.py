import copy
import importlib.util
import json
from pathlib import Path


def runner():
    spec = importlib.util.spec_from_file_location(
        "phase02_gate_test", Path("evals/phase02_gate.py")
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_gate_does_not_accept_correct_outcomes_with_mutated_state():
    check = runner().check_result
    expected = {"outcomes": [["ok", None]], "stop": "completed"}
    evidence = {
        "results": [{"outcome": "ok", "reason": None}],
        "stop_reason": "completed",
        "model_steps": 2,
        "tool_calls": 1,
        "trace_warning": None,
    }
    assert check(evidence, expected, {"revision": 1}, {"revision": 2}) is False
    assert check(evidence, expected, {"revision": 1}, {"revision": 1}) is True


def test_gate_preserves_wrong_outcome_or_budget_failure():
    check = runner().check_result
    expected = {"outcomes": [["unknown", "missing"]], "stop": "completed"}
    evidence = {
        "results": [{"outcome": "ok", "reason": None}],
        "stop_reason": "completed",
        "model_steps": 2,
        "tool_calls": 1,
        "trace_warning": None,
    }
    assert check(evidence, expected, {}, {}) is False
    evidence["results"] = [{"outcome": "unknown", "reason": "missing"}]
    evidence["model_steps"] = 4
    assert check(evidence, expected, {}, {}) is False


async def test_withdrawal_probe_does_not_remove_shared_corpus_document():
    from anlan.contracts import Identity
    from anlan.service import AccessDenied

    owner = Identity(tenant_id="synthetic-test", user_id="owner")

    class Store:
        def __init__(self):
            self.documents = {"watcher"}

        async def ingest(self, identity, document):
            self.documents.add(document["doc_id"])

        async def withdraw(self, identity, doc_id):
            if identity.user_id != "owner":
                raise AccessDenied("no permission")
            self.documents.remove(doc_id)

        async def search(self, identity, parameters):
            return {"citations": [{"doc_id": name} for name in self.documents]}

    store = Store()
    assert await runner().withdrawal_probe(store, owner, {"doc_id": "watcher", "source": "test"})
    assert store.documents == {"watcher"}


def test_budget_probe_rejects_new_reservation_during_gate():
    before = json.loads(
        Path("docs/phases/phase-02-tools-rag/evidence/wp04/budget-after-live.json").read_text(
            encoding="utf-8-sig"
        )
    )
    after = copy.deepcopy(before)
    extra = {
        **after["attempts"][0],
        "attempt_id": "unexpected-new-attempt",
        "work_package": "P2-WP05",
        "status": "reserved",
        "usage": None,
    }
    after["attempts"].append(extra)
    after["total_reserved"] += 1
    after["packages"]["P2-WP05"] = 1
    check = runner().check_budget
    assert check(before, before, before["attempts"])["passed"] is True
    outcome = check(before, after, before["attempts"])
    assert outcome["passed"] is False
    assert outcome["new_reservations"] == 1
