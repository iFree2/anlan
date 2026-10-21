# Batch 4 browser acceptance evidence

Date: 2026-10-21 (Asia/Shanghai)

Environment: local scripted service, real local PostgreSQL, synthetic console profile. No
live provider request was made. Credentials, DSN values, and task identifiers are omitted.

## Browser path exercised

The in-app browser was used for actual interaction, not screenshot-only inspection:

1. Connected by selecting the local demo configuration. The page showed the scripted-double,
   SYNTHETIC, and no-approval notices.
2. Sent `明天去罐区补焊`. The page showed a field-specific confirmation card and no task.
3. Selected `确认申请`. One material task appeared and the assistant immediately asked the
   first missing-field question.
4. Sent a location supplement, asked a temporary welding knowledge question, then supplied
   method and attachment descriptions. The same task remained bound and reached review-ready
   state.
5. Reloaded the browser. Because the token is page-memory only, reselected the local config;
   the same conversation, task, revision, messages, and sidebar projection returned.
6. Created a separate candidate and rejected it. The sidebar remained unbound.
7. Paused and resumed the active task. The binding and task revision were preserved.
8. Created a synthetic event and ran review. The detail panel showed the raw alarm still
   `active`, a completed current review, evidence entries, and feedback controls.
9. Proposed another task with four explicit fields. The old task stayed visible while the UI
   requested a new-versus-switch choice. `新建另一项任务` required another confirmation before
   a distinct task appeared. `切换到 <已有任务>` returned to an owned prior task.
10. Cancelled guidance. The conversation became unbound while the assistant explicitly stated
    that the business task was not modified.

## Responsive and security observations

- Desktop: chat and task sidebar were simultaneously visible.
- 390 x 844: the task disclosure appeared before the composer. Measured viewport width was
  390 px and document scroll width was 375 px, so no horizontal overflow was present.
- Keyboard Enter submitted; Shift+Enter remains declared for newline behavior.
- Conversation streaming used authenticated `fetch` with an `Authorization` header. No token
  appeared in the URL, page text, or captured evidence.
- Browser console inspection reported no warning or error entries during initial connection.

## Screenshot limitation

Visible desktop and mobile screenshots were captured successfully in the browser automation
result. The separate DevTools file-save operation blocked twice on this long-lived SSE page and
was terminated without creating a file. Per coordination direction, no further screenshot
mechanisms were attempted. This report preserves the sanitized interaction evidence; the
screenshots remain present in the batch execution transcript rather than this directory.
