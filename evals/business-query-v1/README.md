# Grounded business query v1

Frozen deterministic acceptance cases for status, details, process guidance, cited knowledge,
missing knowledge, target selection, role isolation, unauthorized targets, mixed requests,
quoted instructions, negation, hypothesis and prompt injection.

Run `uv run pytest tests/test_business_query_evaluation.py -q`.
Every case executes the production scripted classifier, host constraint, policy and query gateway.
All cases require zero unconfirmed business writes, the specified outcome and evidence keys,
and absence of forbidden output markers. Independent real-PostgreSQL collaboration tests prove
the role and tenant boundary, private-message isolation and unchanged business table counts.
These are protocol and grounding checks, not evidence of live-model quality. No live model is used.

Changes to these cases require review alongside the query contract. The future business-query
Skill, model synthesis, deployments and cloud resources are outside this acceptance set.
