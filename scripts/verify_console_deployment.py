"""Record credential-free remote snapshots for a controlled service restart check."""
import argparse
import json
from pathlib import Path

import httpx


def verify(base_url, access_file, task_id):
    config = json.loads(access_file.read_text(encoding="utf-8-sig"))
    with httpx.Client(
        base_url=base_url.rstrip("/") + "/", timeout=30, trust_env=False,
        headers={"Authorization": "Bearer " + config["tokens"][0]["token"]},
    ) as client:
        def read(path):
            response = client.get(path)
            if response.status_code != 200:
                raise RuntimeError("Remote read failed; credentials and response body hidden")
            return response.json()

        task = read("tasks/" + task_id)
        events = read(f"console/api/tasks/{task_id}/events")["items"]
        reviews = []
        for event in events:
            assert event["raw"]["alarm_state"] == "active"
            for row in read(f"console/api/events/{event['receipt_id']}/reviews")["items"]:
                current = read("reviews/" + row["review_id"])
                observations = current["result"]["report"]["observations"]
                assert len(observations) == 3 and all(o["outcome"] == "ok" for o in observations)
                reviews.append({
                    "review_id": current["review_id"], "revision": current["revision"],
                    "feedback": current["feedback"], "currentness": current["currentness"],
                    "mode": current["result"]["report"]["mode"],
                    "knowledge_citations": len(observations[2].get("citations", [])),
                })
        assert len(events) == 2 and len(reviews) == 2
        assert all(r["feedback"] and r["mode"] == "scripted_double" for r in reviews)
        denied = client.get("console/api/tasks", headers={"Authorization": "Bearer invalid"})
        assert denied.status_code == 401
        return {
            "status": "passed", "data_origin": "SYNTHETIC", "task_id": task_id,
            "material_revision": task["revision"],
            "event_ids": sorted(e["receipt_id"] for e in events),
            "reviews": sorted(reviews, key=lambda r: r["review_id"]),
            "all_three_observations_ok": True, "invalid_token_rejected": True,
            "credentials_recorded": False,
        }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True)
    parser.add_argument("--access", required=True, type=Path)
    parser.add_argument("--task", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Use a new evidence file")
    report = verify(args.url, args.access, args.task)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": report["status"], "credentials_recorded": False}))


if __name__ == "__main__":
    main()
