# P11 conversation batch 5 gate report

Date: 2026-10-21 (Asia/Shanghai). Data: SYNTHETIC. Model mode: scripted_double.

## Verification

- Contract/safety fixes: 36 passed; later negation and evaluation regression set: 52 passed.
- Task 9 focused suite with explicit same-process PostgreSQL environment: 98 passed in 89.57s, 0 skipped.
- Full application suite before the final smoke-only additions: 564 passed in 376.42s, 0 skipped. A final full run is recorded below before handoff.
- Ruff: `ruff check src tests evals scripts` reported no diagnostics.
- Browser evidence: batch 4 actual interaction covered the main chain, reject, pause/resume, new/switch, event/review, refresh, desktop and 390x844. The separate screenshot file-save operation blocked and was not retried.

## Routing evaluation

All 49 cases are now seen. The historically named 25-case holdout was inspected during the
negation repair and is reported only as `seen_post_fix_regression`; there is no unseen score.

- Pre-fix intent: 38/49 (77.55%); post-fix: 40/49 (81.63%).
- Seen development: 22/24; seen post-fix regression: 18/25.
- Hot-work recall 5/5; chat false positives as hot work 6.
- Confirmation coverage 7/9; non-empty-gold field exact match 12/13; spurious non-empty
  extraction on empty-field expectations 8.
- Saved classifier-run unconfirmed business writes: 0. Actual API/service gates separately prove no task before confirmation and no write for chat/negated active fields.
- Retained misses include non-application repair descriptions, prompt injection, one quotation,
  one mixed consultation, one cancel phrase, one affirmative variant, and one ambiguous field
  exact-match mismatch. Scripted quality is not live-provider quality.

## Wheel and clean start

- Final wheel built from safety-fix commit `f83fb5f`: `anlan-0.1.0-py3-none-any.whl`, SHA-256
  `451BEB219C873F356330857C3D82CF5AA906284F77B7AFD6238F9B817987422D`, 113 files.
  The earlier `5CC2B6DA...` wheel was an intermediate verification artifact and is not the final build.
- Inspection found SQL013, SQL014, index.html, app.js, api.js, and styles.css.
- Installed with dependencies into a new isolated venv and started from
  `.runtime/wheel-run-p11-final`, outside the source/package import path.
- Cross-process smoke passed: no task before confirmation, confirmed task creation, chat caused
  zero task revision change, identical replay, refresh recovery. After stopping and restarting
  the wheel service, a GET recovered the same conversation/task/revision.
- The smoke performs authenticated `/console/api/info` verification before any POST and refuses
  any service whose `model_mode` is not exactly `scripted_double`.

Preserved failures: the first monolithic PowerShell orchestration was rejected by execution
policy, so the check was split into auditable processes. Two early smoke outputs failed with
health assertions although PowerShell could reach the service; installed httpx returned 502
because it inherited the host proxy. A failing regression was added, the loopback client now uses
`trust_env=False`, and new output paths passed. Initial startup also required waiting for the
knowledge runtime before health became ready. These failed reports remain in ignored `.runtime`.

## Budget and release boundary

Local frozen learning ledger before and after: 46/100 total, 44 succeeded, 2 failed, 0 reserved;
P11-WP01 has no attempts. This is not a claim about current cloud remaining balance. Live provider
requests in this batch: 0. P11-WP01 live quality remains unverified. No SSH, deployment, cloud
credential read, or cloud mutation occurred. The existing DeepSeek deployment does not include
this conversation change.

## Independent review

A read-only reviewer inspected `a30bc18..2e0d5da`. It found no Critical issues and two
Important host-boundary gaps: a live misclassification could replace a switch-choice pending
intent, and a live misclassification of negated active-task input could submit a field. Both were
reproduced with deliberately wrong `ProposedModel` outputs, then fixed in the host constraint
layer. Follow-up coordination extended the same explicit-affirmative check to all pending kinds,
covering `不确认`, `还没确认`, and `解释一下确认流程`. Reviewer Minor findings were also
addressed: the scorer now rejects unknown intent/field contracts and reports spurious non-empty
fields when the reviewed expectation is empty.

Follow-up review required switch targets to match the user's explicit original text and prevented
an ambiguous field-confirmation candidate from being replaced by a new-task misclassification.
These were reproduced and fixed before `f83fb5f`; the reviewer then reported no remaining
Critical or Important findings. Provider-quality evaluation remains separate from this review.

## Final verification

The coordinating chat ran the final suite after source freeze at `f83fb5f`, with the explicit
local PostgreSQL environment loaded in the same process:

```text
576 passed in 458.07s (0:07:38)
All checks passed!
```

The first line is the complete `pytest -q` result (0 skipped); the second is
`ruff check src tests evals scripts`. Only documentation changed afterwards. The final wheel
hash above corresponds to the same frozen source, and its main and restart smoke reports passed.

An additional coordinating-chat smoke against the local preview on port 8130 passed all five
checks: no task before confirmation, confirmed task creation, chat zero task writes, identical
replay, and refresh recovery. Report: `.runtime/conversation-preview-smoke-20261021.json`.
Preview connection configuration remains in ignored `.runtime/conversation-preview-20261021.json`;
no access token is included in committed evidence.
