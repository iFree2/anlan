# Conversation routing v1

This directory freezes 49 manually rule-reviewed **SYNTHETIC** cases. The 24-case
development split and 25-case historically named `holdout` split are labeled independently in
`cases.json`; case IDs must not be reused or silently relabeled. During the targeted negation
repair, the latter cases were inspected. It is therefore reported only as
`seen_post_fix_regression`, never as unseen generalization evidence. A genuinely unseen set must
be created by a later independent review. Cases cover ordinary chat, explicit and
implicit hot work, negation, quotations, hypotheticals, knowledge questions, active-task
fields, ambiguity, task control, task selection, prompt injection, historical repairs, and
mixed messages.

`scripted-results.json` is an actual run of `ScriptedConversationModel` at
`scripted-intent-v1`. It is a deterministic protocol-double baseline, not live-provider or
production-quality evidence. The saved results contain explicit predictions; the scorer
rejects missing predictions instead of substituting expected labels.

## Frozen scripted baseline

- Intent accuracy: 40/49 (81.63%). Seen development 22/24; seen post-fix regression 18/25.
- Hot-work recall: 5/5 (100%) on this small reviewed set.
- Chat false positives as hot work: 6.
- Required-confirmation coverage: 7/9 (77.78%).
- Field exact match: 12/13 (92.31%).
- Spurious non-empty fields when the reviewed expectation is empty: 8.
- Unconfirmed business writes: 0. This metric is zero because the saved classifier run makes
  no workflow calls; separate service/API gates verify the control-flow boundary.

Known intent misses are deliberately retained: all three non-application repair descriptions,
two prompt-injection cases, one quotation, one mixed consultation, one cancel phrase, and one
affirmative variant. The ambiguous-location field also keeps the word `可能`, so exact match
misses. These are protocol-double limitations and are not evidence about DeepSeek quality.

The high-risk active-task negations `不要把位置改成二号罐区` and `别把作业方式写成气焊`
were fixed by a targeted rule after their failing regression tests were observed; this file was
then regenerated. The original pre-fix observation and post-fix report are retained beside the
dataset. Other misses remain visible rather than being tuned away. No unseen score is claimed.

## Reproduction

Generate a new saved result file (the command refuses to overwrite):

```powershell
.venv/Scripts/python.exe evals/evaluate_conversation_routing.py `
  --generate-scripted-from evals/conversation-routing-v1/cases.json `
  --output .runtime/scripted-results-new.json
```

Score either the frozen asset or a separately authorized live-provider result:

```powershell
.venv/Scripts/python.exe evals/evaluate_conversation_routing.py `
  --input evals/conversation-routing-v1/scripted-results.json `
  --output .runtime/conversation-routing-check.json
```

The evaluator never contacts a provider. Live results must use `result_kind=live_provider`,
record the real request count, and remain separate from this scripted baseline.
