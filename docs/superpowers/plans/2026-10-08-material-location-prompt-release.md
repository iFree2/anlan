# Material Location Prompt Release Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish the isolated `materials-v2` prompt so a non-location such as “去哪里操练” receives a clarification request in the cloud console.

**Architecture:** Build a wheel from `HEAD` and apply only the reviewed prompt change in a temporary release directory, so unrelated unstaged learning edits are excluded. Create a new server release beside the current one, atomically switch the `current` symlink, restart only `anlan2-console`, and switch back on readiness failure. One bounded DeepSeek request verifies the reported regression; no database, provider key, or budget migration is changed.

**Tech Stack:** Python 3.13, Hatchling/uv wheel build, systemd, PostgreSQL-backed existing budget ledger, DeepSeek Flash.

---

### Task 1: Verify the regression guard and prepare an isolated wheel

**Files:**
- Modify: `src/anlan/llm/material.py:17-28`
- Test: `tests/test_model.py:25-28`
- Create: ignored `.runtime/p8-materials-v2-build/`

- [x] **Step 1: Add the failing regression guard**

```python
def test_location_prompt_requires_an_action_phrase_to_be_reported_as_not_a_location():
    assert "去哪里操练" in SYSTEM_PROMPT
    assert "没有任何区域或作业点" in SYSTEM_PROMPT
```

- [x] **Step 2: Run the guard before the prompt change**

Run: `.venv/Scripts/python.exe -m pytest tests/test_model.py -q`

Expected: the new assertion fails because the previous `materials-v1` prompt has no such requirement.

- [x] **Step 3: Make the minimal prompt change**

```text
位置字段若只是疑问句、动作描述或闲聊，且没有任何区域或作业点，也应报告 ambiguous；
例如“去哪里操练”不是作业地点，应引用该原文并追问具体区域与作业点。
```

- [x] **Step 4: Verify the source change**

Run: `.venv/Scripts/python.exe -m pytest tests/test_model.py -q` and `.venv/Scripts/python.exe -m ruff check src/anlan/llm/material.py tests/test_model.py`

Expected: 17 passing tests and no Ruff diagnostics.

- [x] **Step 5: Build a release from clean `HEAD` plus only this prompt hunk**

Run: export `git archive HEAD` into `.runtime/p8-materials-v2-build/`, apply the two `materials-v2` replacements there, compare the staging tree with `HEAD`, then run `uv build --wheel` from that staging tree.

Expected: the staged source diff contains only `src/anlan/llm/material.py`; no current working-tree learning edits enter the wheel.

Actual: wheel `anlan-0.1.0-py3-none-any.whl`, SHA-256 `cf9710e1e1050cf87630700f5ddacdc7a6224289bc79f023cc0efd9bb20b65b8`, was inspected to contain `materials-v2` and the regression phrase.

### Task 2: Publish the isolated wheel with rollback

**Files:**
- Create on server: `/opt/anlan2/releases/p8-materials-v2-20261008/`
- Preserve: `/opt/anlan2/releases/p8-deepseek-20261007/`, `/opt/anlan2/shared/app.env`, `/opt/anlan2/shared/console.json`, existing PostgreSQL data

- [x] **Step 1: Read current release and service state**

Run a read-only SSH command asserting that `current` resolves to `p8-deepseek-20261007` and that `anlan2-console` is active.

Expected: both assertions hold before copying anything.

Blocked: the existing ignored SSH configuration reached the host but returned `AuthenticationException` on 2026-10-08. No remote command ran.

Resolved: the user supplied an authorized local password candidate, which was verified and saved only in ignored `.runtime/aliyun-ssh.txt`. Read-only SSH then confirmed `p8-deepseek-20261007` and an active service.

- [x] **Step 2: Upload and validate the wheel**

Run: copy the SHA-256-checked wheel to a unique temporary path under `/opt/anlan2/`; remote code extracts it to the new release and performs an import probe using the existing virtual environment.

Expected: the new package reports `PROMPT_VERSION == "materials-v2"`; no database/configuration file is written.

Actual: the first release became `/opt/anlan2/releases/p8-materials-v2-20261008` and loaded `materials-v2`, but its final validation was blocked before any provider request because P8-WP03 had reached 10/10 calls.

- [x] **Step 3: Atomically switch only the application release**

Run: create a replacement symlink for `/opt/anlan2/current`, atomically replace it, then `systemctl restart anlan2-console`.

Expected: `/console/api/info` becomes ready in `deepseek_live` mode. If the import, restart, or readiness check fails, switch the symlink back and restart the prior service.

Actual: P8-WP04 was added as a new permitted package through SQL011; it preserves the 100-call total and 10-call package cap, rather than reusing or resetting P8-WP03. The final release is `/opt/anlan2/releases/p8-materials-v2-budget-20261008`, and readiness reported `deepseek_live`, `materials-v2`, and P8-WP04 with 10 available calls before verification.

- [x] **Step 4: Verify the live regression with one request**

Run: using the locally ignored console access file only in process memory, create a synthetic task whose `work_location_description` is `去哪里操练` and inspect its saved analysis.

Expected: response has `semantic_status == "checked"`, `prompt_version == "materials-v2"`, and an issue for `work_location_description` quoting the supplied text. Record sanitized result, request count, and outcome; never print the access token or provider key.

Actual: one request succeeded with `semantic_status=checked`, `prompt_version=materials-v2`, exact quote `去哪里操练`, an `ambiguous` location issue, a non-empty question, and 467 total tokens. Afterward P8-WP04 was 1/10 and the shared authorization was 57/100.

- [x] **Step 5: Record the deployed result**

Run: update the P8 deployment/status note with the release path, wheel digest, health result, and exactly one model request's outcome; preserve the distinction between one regression sample and broad model-quality proof.

