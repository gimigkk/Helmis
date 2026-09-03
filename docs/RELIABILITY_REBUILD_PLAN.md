# Context

Helmis is not failing because it needs a longer system prompt or simply a stronger model. The production audit and screenshots show a deeper execution-contract problem: the model interprets ambiguous requests, operates on title-based mutable records, receives incomplete/contradictory context, and then narrates success without proving the requested postcondition. Recurring reminders are stored as one-off tasks; semantically equivalent reminders are independent; corrections are acknowledged without reconciliation; untrusted assistant/user text is promoted into long-term memory; and delivery/scheduler state is not transactional. The goal is a dependable secretary that is accurate, correctable, context-aware, conservative with side effects, and honest about uncertainty and delivery.

# Recommended approach

Implement this as a reliability-first rebuild in phases, preserving useful existing components (WAHA client, queue/media normalizers, tool registry, due-time utilities, proactive evaluator, vault, and current test fixtures) while replacing the weak contracts underneath them. Do not start by tuning prompts or changing model priority; first make incorrect actions difficult or impossible to commit and make every response derive from verified state.

## Phase 0 — Freeze and characterize production

- Treat the VPS state as read-only until a clean release is prepared; capture the current commit, dirty diff, image digest, configuration names, and data backup/restore verification separately.
- Export a sanitized regression corpus from production traces/screenshots covering the reminder incident, schedule misrouting, wrong identity, no-fluff requests, not-found mutations, status events, media, and ordinary banter.
- Add an offline contract harness using fake Gemini/WAHA clients and temporary data directories. It must assert tool order, mutation arguments, state postconditions, outbound messages, no unexpected network access, and background-task cleanup.
- Establish baseline metrics: false-success confirmations, duplicate notifications per logical event, unsupported facts, silent authorized turns, p50/p95 turn latency, and delivery failures.

## Phase 1 — Make state and mutations trustworthy

Create a versioned persistence boundary rather than extending title-based JSON dictionaries indefinitely. Prefer SQLite in WAL mode for transactional state, migrations, concurrent workers, and scheduler claims; retain vault binaries and traces on the filesystem with metadata in the database.

### Phase 1 status — task mutation contract

Completed in the current implementation:

- Stable task IDs, deterministic legacy ID backfill, canonical identity keys, and version fields.
- Exact-ID update, completion, and deletion paths, with ambiguity-safe title/identity fallback selectors.
- Optimistic `expected_version` checks that preserve conflicts without changing state.
- Structured mutation outcomes (`committed`, `not_found`, `ambiguous`, `conflict`, and `failed`) with exact affected IDs/counts and before/after state where applicable.
- Task handlers and Gemini schemas that preserve the mutation contract, plus focused unit tests and a dependency-independent smoke test.

Still outstanding for the full Phase 1 gate:

- Introduce a repository abstraction and migrate structured state to SQLite/WAL with atomic cross-process resolution, version checking, and commit.
- Add authorization/scope enforcement and durable schedule/event, reminder-policy, occurrence, scheduled-action, and outbox/delivery records.
- Implement migration/shadow comparison, backup/restore verification, and rollback procedures before production rollout.

Introduce explicit domain records:

- `task`: stable ID, canonical subject/action key, title, description, owner/assignee, status, timestamps, version.
- `schedule/event`: canonical timezone-aware start/end, recurrence rule, exceptions, source, location, and owner.
- `reminder policy/occurrence`: event/task reference, one-shot vs recurring, lead time, repeat interval, acknowledgment/stand-down policy, occurrence state.
- `scheduled action`: validated allowlisted command, target chat, requester, policy, and execution state; never generic fallback execution.
- `outbox/delivery attempt`: idempotency key, claim lease, provider message ID, attempts, backoff, and explicit success/failure.
- notes and people: stable IDs, scope/owner, revisions, and safe exact-ID mutation.

Extend/rework `memory/store.py`, `tools/tasks.py`, `tools/schema.py`, and `agent/proactive.py` around these records. Mutations must reject empty selectors, use stable IDs/canonical keys, return exact affected records/counts and before/after state, and return `ambiguous` rather than guessing. Add explicit bulk operations for “all attendance reminders for this course” and an idempotent reconcile operation for policy corrections.

Implement real recurrence (weekday/date rules and arbitrary follow-up cadence) with occurrence generation and timezone-aware canonical instants. A user-visible confirmation may mention recurrence or repeat intervals only when the persisted policy proves it.

## Phase 2 — Make the agent conservative and grounded

- Replace regex-only mutation forcing with a typed intent/action plan: classify request, resolve entities, identify source of truth, declare intended side effects, and require confirmation/clarification for ambiguity or destructive scope. Use tool calling as an execution mechanism, not as a proxy for intent.
- Enforce deterministic routing for tasks, schedules, notes, contacts, vault files, URLs, group banter, and status events before the model is allowed to improvise. Schedule questions must query schedule records/notes, not task lists.
- Fix `agent/loop.py` to validate tool arguments against the declared schema, handle all Gemini content parts/function calls, bound steering/mailbox work, and derive final text from structured outcomes.
- Rewrite `agent/guardrails.py` so read-only success can never authorize a mutation claim; `not_found`, `ambiguous`, partial, and failed outcomes are preserved; tool chips are opt-in and suppressed for no-fluff/copy-only turns; no final success text is emitted without a durable commit and (for sends) delivery evidence.
- Keep the stronger model question empirical: add a replay/A-B benchmark for the current cascade versus a stronger model using identical state and tools. Do not assume Flash-Lite is the root cause or remove `mode=ANY` blindly.
- Update `whatsapp/processor.py`, `history.py`, `parser.py`, and `webhook.py` to preserve message IDs and all burst media, avoid duplicate/repeated-message loss, reject `status@broadcast` early, make group/identity policy explicit, and provide safe fallback responses for failed media/history retrieval. Quote the originating message consistently where desired.

## Phase 3 — Make memory and learning safe

- Pause automatic fact extraction and auto-crystallization by default until each output has source turn/message ID, provenance type, confidence, scope, validity, contradiction/supersession links, and retention/deletion behavior.
- Never promote filename tokens, quoted text, assistant-generated claims, or unconfirmed schedule completions into authoritative identity/profile data. Explicit user corrections must supersede prior claims and trigger reconciliation where required.
- Move generated skills to a controlled writable proposal store separate from immutable core config; require validation, approval/versioning, rollback, size limits, and audit metadata before injecting a skill into the system prompt.
- Retrieve only active, high-confidence, authorized claims and make casual turns avoid unnecessary embedding calls.

Primary files: `memory/semantic.py`, `tools/memory.py`, `agent/crystallize.py`, `tools/skills.py`, `agent/cascade.py`, and `processor.py`.

## Phase 4 — Make scheduling and delivery reliable

- Replace untracked `asyncio` timer/tick behavior with durable occurrence claims and outbox processing. A restart, overlapping tick, or crash after a provider send must not create duplicate actions.
- Unify internal and MCP tool namespaces; validate scheduled jobs against an allowlist and quarantine malformed/unknown jobs rather than falling through to a generic send.
- Authenticate scheduler/webhook ingress, add replay/idempotency handling, and separate liveness from WAHA readiness.
- Record each outbound bubble/progress/reminder attempt and reconcile partial failures; do not mark a task or occurrence complete before the actual operation is proven.

Primary files: `agent/proactive.py`, `whatsapp/webhook.py`, `whatsapp/client.py`, `processor.py`, `tools/mcp_export.py`, `server.py`, and `docker-compose.yml`.

## Phase 5 — Production hygiene and rollout

- Reconcile docs, environment variable names, ports, scheduler cadence, service names, and backup behavior with the actual implementation.
- Add missing dependencies and a real CI gate for tests, lint, type checks, import checks, compose validation, and security/contract tests.
- Build from a clean immutable commit, pin mutable images, snapshot and verify backups, deploy an isolated canary against a test WAHA session, run synthetic webhook/scheduler scenarios with no production data, then roll out the agent only after SLO checks.
- Keep a one-command rollback to the previous image/commit and preserve the production data volume.

# Critical files to modify

`helmis-agent/src/memory/store.py`, `helmis-agent/src/memory/semantic.py`, `helmis-agent/src/tools/tasks.py`, `helmis-agent/src/tools/memory.py`, `helmis-agent/src/tools/schema.py`, `helmis-agent/src/tools/registry.py`, `helmis-agent/src/agent/loop.py`, `helmis-agent/src/agent/guardrails.py`, `helmis-agent/src/agent/proactive.py`, `helmis-agent/src/agent/crystallize.py`, `helmis-agent/src/tools/skills.py`, `helmis-agent/src/whatsapp/webhook.py`, `queue.py`, `history.py`, `parser.py`, `processor.py`, `client.py`, `tools/mcp_export.py`, `server.py`, `docker-compose.yml`, and the test/deployment configuration. Reuse existing atomic helpers, `parse_due_timestamp`, `WahaClient`, parser/quote utilities, registry injection, tracer, and proactive test fixtures rather than duplicating them.

# Verification gates

1. Unit tests for migrations, stable-ID/ambiguous mutations, recurrence/occurrences, timezone boundaries, memory provenance/corrections, skill proposals, and guardrail result fidelity.
2. Concurrency tests across processes for state writes, scheduler claims, timer-vs-tick races, retry/restart recovery, outbox idempotency, and crash-after-send.
3. Offline replay tests for every sanitized incident: duplicate attendance cleanup, recurring reminders, “done” with multiple matches, “no fluff,” wrong NIM correction, missing schedule, missing file, status media, group filtering, and failed WAHA/Gemini calls.
4. ASGI/container smoke tests with fake WAHA/Gemini, network egress denied, temporary volumes, and assertions that production data is untouched.
5. Pre-deploy checks: clean Git tree/SHA, dependency import, pytest, Ruff, type checking, `docker compose config`, image digest, backup/restore verification, canary health, synthetic webhook, scheduler, and delivery-result checks.
6. Acceptance criteria: no unsupported success confirmation; no duplicate logical reminder delivery; recurring behavior survives restart; corrections reconcile state; no untrusted fact becomes authoritative; no-fluff output is exact; unauthorized/status events cannot silently trigger model work; and every outbound action has an auditable result.

# Decisions to confirm before implementation

- Attendance is not a special feature: represent each course/session as generic event data and attach one generic reminder policy per course occurrence. Do not add an attendance-specific branch or teach each course individually.
- Support weekly recurrence plus generic arbitrary nag intervals (bounded by safety/rate limits), with explicit acknowledgment/stop behavior; the engine must be data-driven rather than course-specific.
- Define memory value by secretary utility: auto-accept only explicit, durable, low-sensitivity facts that improve future planning, identity, preferences, relationships, routines, or long-lived projects; treat tasks, one-off chat, filenames, quoted text, and assistant-generated claims as transient or candidates requiring confirmation. Store provenance/confidence/conflicts and never let embeddings alone decide authority.
- Ambiguous completion/deletion should not guess: return candidates and ask, or apply only an explicitly scoped bulk operation with exact count/postcondition.
- Use a SQLite/WAL repository as the transactional state boundary, preserving JSON/vault backups and a tested rollback path.
- Keep the model dynamic: no hardcoded attendance/course code path. The model proposes generic typed intents; validators and domain engines resolve arbitrary entities, recurrence, reminder policies, and tool actions.
  - **Session note (2026-09-03):** task categories are a *data layer* concern, not a hardcoded course path — `_detect_task_category` classifies routine attendance pings for display filtering only (scheduler unaffected), while the model retains full authority over interpretation and can override via explicit `category`. The earlier fast-path phrase whitelist + deterministic list renderer was removed as a violation of this principle; query turns now use compact mode (domain-scoped context) with the normal tool-calling loop.
- Authorized WhatsApp chats/groups, status-event treatment, recurrence downtime policy, delivery guarantee, and migration maintenance window remain to be confirmed before implementation.

## Product direction

The target is a general-purpose proactive agent, not a collection of manually taught feature branches. New domains should be expressible as data (an event, entity, predicate, reminder policy, or allowlisted action) and executed by generic engines. Attendance is the motivating example only: adding a new course, appointment, deadline, habit, or follow-up should require no new Python branch, no new skill file, and no special prompt rule.

The model remains responsible for natural-language understanding and proposing an operation, but not for inventing domain state or declaring success. The platform supplies generic primitives for identity, planning, recurrence, memory value, authorization, execution, delivery, and verification; that is what makes the agent smart and usable across future requests.

## Updated answers incorporated

- Canonical behavior: one generic reminder policy per course/session occurrence; not an attendance-specific implementation.
- Recurrence: weekly rules plus bounded arbitrary nag intervals until acknowledgment/stop policy.
- Memory: value-based secretary memory with automatic triage, provenance, confidence, explicit correction handling, and confirmation for uncertain/sensitive claims—not indiscriminate “remember everything.”
- Persistence: migrate safely to SQLite/WAL with idempotent import, shadow comparison, backup, canary, and rollback.

## Decision: direct JSON → SQLite cutover (no dual backend)

User-mandated: JSON is a **one-time migration input only**. There will be no permanent JSON/SQLite dual-runtime, no compatibility shims, and no legacy dead code. This is a small project.

- **New module** `src/memory/db.py`: thread-local connections with `PRAGMA journal_mode=WAL`, `busy_timeout=5000`, `foreign_keys=ON`, and idempotent `CREATE TABLE IF NOT EXISTS` schema. SQLite owns concurrency; the `_memory_lock` / `_semantic_lock` / vault flock disappear.
- **Schema (first cutover):** `tasks` (stable id, identity_key, version, due_ts cache, recurrence/nag policy JSON, reminder-lifecycle columns), `task_occurrences`, `outbox`, `delivery_attempts`, `activity_log` (cap 50), `people`, `notes`, `schema_migrations`.
- **Migration script** `src/memory/migrate.py` (`python -m src.memory.migrate`): copies existing JSON rows into SQLite, verifies row counts, then renames sources to `*.json.migrated-<ts>` (never deletes). Idempotent at startup.
- **`store.py` keeps its public API** but becomes SQL-backed; `proactive.py` is refactored off `load_memory()`/`save_memory()` onto `fetch_tickable_tasks()` + `update_task_fields()`.
- **Deferred to a second bounded migration:** semantic memory and vault catalog metadata (JSON for those stays until then).
- **Unchanged:** `agent_traces.jsonl` stays append-only JSONL; vault sidecar `*.meta.json` files are left alone; `scripts/backup.sh` gains `data/helmis.db` (WAL checkpoint or `VACUUM INTO`).
- **Compat-code deletion:** `MEMORY_FILE` / `SEMANTIC_MEMORY_FILE` / `CATALOG_FILE` runtime constants and the `sys.modules` probing hacks in `_get_memory_file` are removed once nothing references them; tests move to a shared `tests/conftest.py` `sqlite_db(tmp_path, monkeypatch)` fixture.

**Cutover order:** (1) `db.py` + schema + `migrate.py` → (2) `store.py` + `proactive.py` refactor → (3) delete JSON runtime code + compat seams → (4) test fixture migration → (5) `backup.sh` + docs.

## Production safety constraints (runbook, always in effect)

- **Persistent Data Protection**: NEVER delete, overwrite, or clean `/opt/helmis/data/` or `/opt/helmis/.env`. These hold the active WhatsApp credentials, long-term memory, tasks, and stored vault documents.
- Only recreate the `agent` service so `helmis-waha` remains connected and doesn't lose active WhatsApp sessions.
- Before pushing or syncing to the server, always ensure all local tests pass.
- Nothing is deployed yet; the VPS is treated as read-only until the Phase 5 rollout.

## Remaining questions for implementation

- Does weekly recurrence use local weekday/time, fixed seven-day intervals, or both? What are bounds for arbitrary nag intervals?
- During downtime, should missed occurrences be skipped, caught up once, or replayed individually?
- Who receives generic reminders and what are default quiet hours/escalations?
- Which identities/groups are authorized, and should rejected traffic produce operator-visible diagnostics?
- What provider acknowledgement and duplicate window are acceptable for WhatsApp delivery?
- Should uncertain memory candidates ask in the current turn, enter a review queue, or remain unavailable until confirmed?
- Can SQLite own semantic-memory/catalog metadata now, or only structured task/schedule/delivery state initially?
- What maintenance window and backup RPO/RTO apply to migration?
