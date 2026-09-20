"""真实本地编码器与PG的跨进程知识演示，使用新的合成租户保留历史证据。"""

import argparse
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not os.environ.get("ANLAN_DATABASE_URL"):
        parser.error("先加载项目PG环境；不输出凭据。")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    tenant = "synthetic-knowledge-smoke-" + uuid4().hex
    report = {"created_at": datetime.now(UTC).isoformat(), "data_origin": "SYNTHETIC",
              "tenant_id": tenant, "requests_this_run": 0, "encoding": "local_neural",
              "status": "failed", "commands": []}
    with args.output.open("x", encoding="utf-8") as output:
        def call(*command, expected=0, actor_tenant=tenant):
            argv = [sys.executable, "-m", "anlan", *command, "--tenant", actor_tenant,
                    "--as-of", "2026-09-20T12:00:00Z"]
            result = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8",
                                    timeout=60, env={**os.environ, "PYTHONUTF8": "1"})
            report["commands"].append({"argv": argv, "exit_code": result.returncode,
                                       "stdout": result.stdout, "stderr": result.stderr})
            if result.returncode != expected:
                raise AssertionError("knowledge CLI failed")
            return json.loads(result.stdout) if expected == 0 else None

        try:
            ingested = call("knowledge-ingest")
            assert len(ingested["documents"]) == 9
            assert call("knowledge-withdraw", "--doc-id", "withdrawn-policy")["withdrawn"]
            result = call("knowledge-query", "--question", "作业点隔离措施要核对什么？",
                          "--strategy", "hybrid")
            assert result["citations"][0]["doc_id"] == "isolation"
            assert len(result["answer"]) == 1
            assert call("knowledge-query", "--question", "作业点隔离措施",
                        actor_tenant="other-tenant")["outcome"] == "unknown"
            call("knowledge-withdraw", "--doc-id", "isolation", "--user", "other-user", expected=2)
            result = call("knowledge-query", "--question", "允许略去监护核对吗？")
            assert not {"withdrawn-policy", "future-policy", "expired-policy"} & {
                c["doc_id"] for c in result["citations"]}
            report["status"] = "passed"
        except Exception as exc:
            report["error_category"] = type(exc).__name__
        finally:
            json.dump(report, output, ensure_ascii=False, indent=2)
    print(json.dumps({"status": report["status"], "commands": len(report["commands"]),
                      "output": str(args.output)}))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
