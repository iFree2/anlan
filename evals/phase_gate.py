"""本地P1工程回归和历史预测重新评分；本入口不创建模型客户端。"""

import argparse
import asyncio
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from anlan.analysis import AnalysisFailure, OfflineAnalyzer
from anlan.contracts import Identity
from anlan.evaluation import score_issues
from anlan.service import WorkflowService

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "evals/phase01-regression-v1/manifest.json"
OWNER = Identity(tenant_id="synthetic-p1-gate", user_id="owner")
ACTORS = {
    "owner": OWNER,
    "other_tenant": Identity(tenant_id="other-synthetic", user_id="owner"),
    "other_user": Identity(tenant_id=OWNER.tenant_id, user_id="other-user"),
}


def load_verified(path: Path, checksum: str, format_: str):
    text = path.read_text(encoding="utf-8-sig")
    data = json.loads(text) if format_ == "json" else [
        json.loads(line) for line in text.splitlines() if line.strip()]
    canonical = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    if hashlib.sha256(canonical.encode()).hexdigest() != checksum:
        raise ValueError(f"checksum mismatch: {path.name}")
    return data


class CountingOfflineAnalyzer(OfflineAnalyzer):
    def __init__(self, inject_timeout: bool):
        self.calls = 0
        self.inject_timeout = inject_timeout

    async def analyze(self, application):
        self.calls += 1
        if self.inject_timeout:
            raise AnalysisFailure("model_timeout")
        return await super().analyze(application)


def check_state(state: dict, expected: dict, fields: dict, calls: int) -> bool:
    analysis = state["analysis"]
    return (
        state["revision"] == expected["revision"]
        and state["status"] == expected["status"]
        and state["fields"] == fields
        and calls == expected["analysis_calls"]
        and sorted(i["field"] for i in analysis["issues"]) == sorted(expected["issue_fields"])
        and analysis["semantic_status"] == expected.get("semantic_status", "offline_not_checked")
        and analysis["error"] == expected.get("error")
        and all(i["source"] == "rule" and i["kind"] == "missing" and i["question"].strip()
                for i in analysis["issues"])
        and "approved" not in state
    )


async def run_case(case: dict, base_fields: dict) -> dict:
    checks = []
    try:
        analyzer = CountingOfflineAnalyzer(case.get("analyzer") == "inject_model_timeout")
        service = WorkflowService(analyzer)
        fields = {**base_fields, **case["initial_overrides"]}
        state = await service.start(OWNER, fields)
        saved = await service.get(OWNER, state["task_id"])
        checks.append({"step": "start", "state": saved, "expected": case["initial_expected"],
                       "passed": state == saved and check_state(
                           saved, case["initial_expected"], fields, analyzer.calls)})
        for index, step in enumerate(case["steps"], start=1):
            before = await service.get(OWNER, state["task_id"])
            before_calls = analyzer.calls
            returned, error = None, None
            try:
                actor = ACTORS[step.get("actor", "owner")]
                if step["action"] == "resume":
                    returned = await service.resume(actor, state["task_id"], step["revision"],
                                                    step["fields"], request_id=step["request_id"])
                elif step["action"] == "get":
                    returned = await service.get(actor, state["task_id"])
                else:
                    raise ValueError("Action outside gate whitelist")
            except Exception as exc:
                error = type(exc).__name__
            current = await service.get(OWNER, state["task_id"])
            if "expected_error" in step:
                passed = (error == step["expected_error"] and current == before
                          and analyzer.calls == before_calls)
            elif error is None:
                fields = {**fields, **step.get("fields", {})}
                passed = (check_state(returned, step["expected"], fields, analyzer.calls)
                          and check_state(current, step["expected"], fields, analyzer.calls)
                          and returned == current)
                if step.get("same_result_as_previous"):
                    passed = passed and returned == before
            else:
                passed = False
            checks.append({"step": index, "passed": passed, "error": error,
                           "expected": step.get("expected", step.get("expected_error")),
                           "state": current, "analysis_calls": analyzer.calls})
            state = current
    except Exception as exc:
        # 仅记录异常类型，案例失败仍归档，不把输入/凭据放进错误字符串。
        checks.append({"step": "unexpected_failure", "passed": False,
                       "error": type(exc).__name__})
    return {"case_id": case["case_id"], "passed": bool(checks) and all(c["passed"] for c in checks),
            "analyzer": case.get("analyzer", "offline"), "checks": checks}


def rescore_archive(archive: dict, labels: list[dict]) -> dict:
    expected = {row["case_id"]: row["expected"] for row in labels}
    actual = {row["case_id"]: row for row in archive["results"]}
    if (len(actual) != len(archive["results"]) or len(expected) != len(labels)
            or actual.keys() != expected.keys()):
        raise ValueError("Archive case IDs do not exactly match labels")
    results = []
    for case_id, row in actual.items():
        issues = row["state"]["analysis"]["issues"]
        results.append({"case_id": case_id, "scores": score_issues(
            [[issue["field"], issue["kind"]] for issue in issues], expected[case_id])})
    issues = [issue for row in actual.values() for issue in row["state"]["analysis"]["issues"]]
    return {
        "mode": "archived_prediction_rescore", "cases": len(results), "results": results,
        "exact_matches": sum(row["scores"]["exact_match"] for row in results),
        "model_issue_count": sum(issue["source"] == "model" for issue in issues),
        "rule_issue_count": sum(issue["source"] == "rule" for issue in issues),
        "historical_request_attempts": archive["summary"]["request_attempts"],
        "historical_total_tokens": archive["summary"]["known_total_tokens"],
        "limitation": "Seen dev predictions from WP03; no new model call or trajectory replay.",
    }


async def evaluate(output: Path) -> dict:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    loaded = {}
    for name, item in manifest["files"].items():
        path = (ROOT / item["path"]).resolve()
        if not path.is_relative_to(ROOT):
            raise ValueError("Frozen path escapes project root")
        loaded[name] = load_verified(path, item["sha256"], item["format"])
    output.parent.mkdir(parents=True, exist_ok=True)
    archive = rescore_archive(loaded["archive"], loaded["labels"])
    with output.open("x", encoding="utf-8") as destination:
        results = [await run_case(case, loaded["cases"]["base_fields"])
                   for case in loaded["cases"]["cases"]]
        passed = sum(case["passed"] for case in results)
        result = {
            "created_at": datetime.now(UTC).isoformat(), "suite_version": manifest["version"],
            "runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "frozen_files": manifest["files"], "requests_this_run": 0, "tokens_this_run": 0,
            "workflow": {"mode": "offline_contract_regression", "cases": len(results),
                         "passed": passed, "failed": len(results) - passed, "results": results},
            "archive_rescore": archive,
            "status": "passed" if passed == len(results) and archive["exact_matches"] == archive[
                "cases"] else "failed",
        }
        json.dump(result, destination, ensure_ascii=False, indent=2)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        report = asyncio.run(evaluate(args.output))
    except (OSError, ValueError, KeyError):
        parser.exit(2, "冻结数据/来源校验失败或输出文件已存在，请检查manifest和新输出路径。\n")
    print(json.dumps({"status": report["status"], "workflow_passed": report["workflow"]["passed"],
                      "requests_this_run": 0, "output": str(args.output)}, ensure_ascii=False))
    raise SystemExit(0 if report["status"] == "passed" else 1)
