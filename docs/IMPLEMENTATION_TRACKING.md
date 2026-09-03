# Implementation Tracking

Single status snapshot for the reliability rebuild. Overwrite this file in place; never append milestone logs.

- Architecture, decisions, acceptance criteria: [RELIABILITY_REBUILD_PLAN.md](RELIABILITY_REBUILD_PLAN.md)
- Sanitized production evidence: [production-evidence/README.md](production-evidence/README.md)

> Snapshot convention: "Done" = implemented and verified against the listed gate.
> History lives in git, not here. If a milestone is not listed under Done, it is not done.

## Current Position

- **Branch:** `feat/dynamic-secretary-foundation` (committed through 2026-09-03)
- **Last commit:** `5631528` — Phase 5 ops tooling (CI, backup verify, rollback, health check)
- **Last updated:** 2026-09-03
- **Last verified:** `326 passed` (full suite, from `helmis-agent/`), Ruff clean on changed files
- **Phase:** All rebuild phases (0–5) build complete; legacy task wrappers/JSON import path removed
- **Step:** Next: push branch + deploy to VPS (sync → migrate → rebuild agent → health check)

## Phase Roadmap

| Phase | Goal | Status | Current gate |
|---|---|---|---|
| 0 | Freeze production, capture evidence, establish replay baseline | **Complete** | 14-case sanitized corpus and executable offline contracts |
| 1 | Trustworthy state and mutations | **Complete** | Direct JSON cutover done; schedule/policy records and authorization in place |
| 2 | Conservative, grounded agent | **Complete** | Typed action plans with confirmation gates, deterministic routing, schema validation, group admission policy, durable replay dedup, replay benchmark harness (stronger-model arm pending provider capacity) |
| 3 | Safe memory and learning | **Complete** | Provenance + auto-extraction off by default; correction/supersession workflow; skill proposal/version/rollback; uncertain claims queue as candidates until explicit confirm/reject |
| 4 | Reliable scheduling and delivery | **Complete** | Durable occurrences + outbox; policy-driven nag engine with data recipients; recurrence survives downtime (bot + human); job allowlist/quarantine; MCP delegates to internal registry |
| 5 | Production hygiene and rollout | **Complete (build)** | CI gate (ruff/import/pytest/compose), `verify_backup.sh`, `rollback.sh`, `health_check.sh`; VPS rollout itself pending deploy |

## Done

| Area | State |
|---|---|
| Production evidence | 14 sanitized regression cases captured in `docs/production-evidence/`; offline contract suite `test_production_contracts.py` executable |
| Task mutation contract | Stable IDs, identity keys, versions, structured outcomes (`committed/not_found/ambiguous/conflict/failed`) on all task tools |
| Task persistence | SQLite/WAL `TaskRepository`; tasks read/written via repository transactions (no snapshot task writes) |
| Scheduler task access | `fetch_tickable_tasks()` + per-task `update_task_fields()` with optimistic version checks |
| Durable scheduling state | Tables: `tasks`, generic `schedules`, `reminder_policies`, stage-aware `task_occurrences`, `outbox`, `delivery_attempts`, `activity_log`, `repository_meta` (schema v3, idempotent column migration for pre-v3 DBs) |
| Occurrence primitives | Idempotent generation, stage-specific token-owned occurrence claims/completion/release, scheduler integration for scheduled actions and human reminder stages; recurring tasks advance to the next timezone-aware due time |
| Outbox delivery | Idempotent enqueue, occurrence-linked rows, lease claims, exact-row `claim_outbox_id`, stage-stable reminder keys, exponential backoff with `next_retry_at`, bounded retries to terminal `dead` state, `record_delivery_attempt` with injectable clock; proactive reminders route through outbox; `deliver_outbox_batch` worker |
| Drain lifecycle | `run_outbox_drain_loop` background task wired into webhook app lifespan (starts/stops with service); crash-after-claim recovery via lease expiry; restart-safe, duplicate-free |
| Generic schedule/policy records | Repository-backed `schedules` and `reminder_policies` records with stable IDs, timezone/recurrence, ownership, lifecycle/version fields, explicit task/schedule references, and scope validation |
| Tool authorization boundary | Central dispatch rejects missing/unknown principals, configured unauthorized chat origins, and cross-user private-memory scopes before handlers run; internal scheduler/Helmis workers remain explicitly allowed |
| Legacy migration | `src/memory/migrate.py`: JSON → SQLite with row verification, timestamped source archive, never deletes |
| Direct JSON cutover | Task state is SQLite-only: `save_memory` no longer mirrors tasks, `replace_all`/`_normalize_memory`/`_pkg_attr`/`sys.modules` probing removed, `MEMORY_FILE` constant deleted; people/notes/activity remain JSON-backed by explicit plan deferral; tests use shared `tests/conftest.py` `sqlite_db` fixture (fresh DB per test, no shared `data/` writes) |
| Tool argument schema validation | `src/tools/validation.py`: model-issued args checked against declared schema at dispatch (unknown keys, wrong types, missing required rejected before handler); schema drift fixed (`update_task` new_status/recurrence/nag args, `remember_fact` scope/source_turn_id, `save_vault_file` original_filename, filename no longer required); internal/MCP tools without declarations pass through |
| Loop content-part handling | `loop.py` handles full Gemini part lists: parallel functionCalls all execute with one functionResponse turn, interleaved text preserved in history, text collected across all text parts, empty part lists no longer crash; regression tests in `tests/test_tool_validation.py` |
| Deterministic schedule routing | New `list_schedules`/`create_schedule`/`list_reminder_policies` tools over repository records with model-facing schema descriptions directing schedule questions away from task lists; tests in `tests/test_schedule_routing.py` |
| Guardrail mutation fidelity | `mutation_was_effective()`: read-only tool success and zero-count mutation results never authorize success claims; `ambiguous`/`conflict`/`failed`/`not_found` outcomes block success language; `is_no_fluff_request()` + `verify_action_fidelity(no_fluff=)` suppress tool chips and keep copy-only output exact; tests in `tests/test_guardrail_contracts.py` |
| Guardrail chips opt-in | Tool chips footnote now opt-in via `HELMIS_TOOL_CHIPS_ENABLED` (default off; wired in `.env.example`); no-fluff turns never get chips even when enabled; 4 legacy tests updated to the opt-in contract + 3 new cases in `tests/test_guardrail_contracts.py` |
| Policy-driven reminder engine | `proactive.py` nag ladder now resolves a reminder policy per task (`reminder_policies` row → task nag fields → urgent default as data, legacy cadence preserved: 10m interval, 5 nags, 60m stand-down); recipients resolve through people directory + group JID for multi-recipient tokens (person-specific env/name-sniffing branches removed; unresolvable recipient raises instead of guessing); single generic nag template with policy-computed minutes; cross-alert fires at budget midpoint only when policy carries `cross_alert_recipient` (persisted through `add_task` nag_policy merge); recurrence advances for human reminders too (weekly series no longer dies after first due reminder) and for >2h overdue recurring tasks on both bot and human stages (occurrence skipped, series advanced to next slot instead of expiring); tests: policy-row cadence/stand-down, recurring human advance, downtime skip+advance, non-recurring still expires in `tests/test_proactive_engine.py` |
| Scheduled-job allowlist + quarantine | `dispatch_scheduled_action` validates jobs before execution: unknown `kind` values are quarantined (durable `quarantined` status + reason, never reinterpreted), `tool` jobs must reference a registered AND schema-declared tool, `message` jobs require explicit text (no title-sniffing for structured jobs), agent/message targets resolve via people directory with quarantine on unresolvable recipient; only plain kindless message tasks keep title extraction (generic fallback, no job structure to misuse); 4 new tests in `tests/test_scheduled_actions.py` |
| MCP namespace unification | `mcp_export.py` raw-client wrappers removed: external MCP tools (`waha_send_message`, `waha_send_media`, `waha_get_messages`) delegate to the same `TOOL_REGISTRY` handlers through `execute_tool_call`, so authorization, schema validation, and logging apply identically (optional params omitted instead of passing nulls that fail schema type checks); `mcp` added to internal caller prefixes; tests in `tests/test_mcp_export.py` |
| Uncertain-memory candidate workflow | `add_memory(status=)`: model-extracted facts queue as `candidate` (never retrieved, never overwrite active records even at sim≥0.88 — closes leak where 0.7-confidence claims passed the retrieval filter); `list_memory_candidates` / `confirm_memory_candidate(id)` (→ active, authoritative, confidence 0.9) / `reject_memory_candidate(id)` (→ `rejected`, kept on disk for audit, never retrieved); owner-scoped resolution; 5 new tests in `tests/test_semantic_memory.py` |
| Burst media preservation | `process_batched_turn` labels every burst media attachment in turn context (primary = inlineData + document banner, others = explicit `[Lampiran Media: ...]` labels); media-download and history-fetch failures degrade safely with the turn still answered; tests in `tests/test_burst_media_preservation.py` |
| Typed intent/action planning | New `src/agent/intent.py`: `TurnPlan` (intent/domain/action_type/selectors/side_effects/destructive/confirmation gate/source of truth), deterministic destructive-scope + ambiguous-selector confirmation gates with model-facing directives, entity pre-resolution against task store, `should_force_tools()` gates `mode=ANY` (confirmation-required plans no longer force tool calls); `guardrails.classify_turn_intent` delegates to the planner (legacy behavior preserved); tests in `tests/test_intent_planning.py` |
| Group admission policy | New `src/whatsapp/policy.py`: pure decision functions for bot-mention detection (name/trigger prefix/@mention/phone mention/bot quote) and human-directed-message suppression; webhook group gate delegates to `decide_group_admission`; mention-list extraction normalized across WAHA engines; tests in `tests/test_group_policy.py` + webhook integration tests in `tests/test_ingestion_policy.py` |
| Durable replay dedup | New `processed_messages` table (schema v3 idempotent create) with `register_seen_message(window_seconds=3600)`; webhook checks the durable window after the in-memory 60s cache so a restart or provider redelivery cannot reprocess a message; store failure degrades open (never drops messages); tests in `tests/test_ingestion_policy.py` |
| Replay/A-B benchmark harness | `helmis-agent/scripts/benchmark_replay.py` replays sanitized corpus cases against identical isolated state/tools with production cascade versus a pinned stronger-model arm, records tool sequences/outcomes/replies/latency, and writes `docs/production-evidence/model_benchmark_results.json`; production cascade completed 14 runs (1/14 contract passes, median behavior 4-7s), baseline arm was provider-inconclusive because `gemini-flash-latest` returned connection fallback on all 14 runs; no model upgrade decision made |
| Backups | `scripts/backup.sh` WAL-checkpoints `helmis.db` before archiving |
| Semantic memory safety | Provenance/source-turn/confidence/scope/authority fields; auto fact-extraction off by default (`HELMIS_ENABLE_AUTO_FACT_EXTRACTION`); retrieval restricted to authoritative ≥0.7 confidence |
| Semantic memory correction workflow | `correct_memory()` in `semantic.py` + `correct_fact` tool: explicit user correction marks matched active claims superseded (`authoritative=False`, `confidence=0.0`, `superseded_by`/`superseded_at` audit links kept on disk) and appends an `explicit_user_correction` claim (confidence 1.0, `supersedes` backlinks); matching = exact/substring first, embedding ≥0.78 fallback; search skips superseded records and exposes provenance; tests in `tests/test_semantic_memory.py` |
| Skill proposals | Auto-generated skills go to proposal store with validation; explicit `approve_skill_proposal()` promotion; active skills never auto-modified |
| Skill versioning + rollback | Promotions and agent updates snapshot every prior active `SKILL.md` to `<skill>/.versions/vNNN.md` and record audit metadata (version, sha256, source, proposal path, timestamps) in `config/skills/.skill-registry.json`; `rollback_skill(name)` restores the registry-recorded previous version (rollback itself versioned + attributed); `list_skill_versions()` exposes history; `list_proposals()`/`reject_proposal(reason)` complete the candidate workflow (rejected proposals kept for audit with reason, never injectable); proposal path containment enforced; tests in `tests/test_skill_proposals.py` (6 cases) |
| Webhook security | Optional `WAHA_WEBHOOK_SECRET` (header) and separate `SCHEDULER_WEBHOOK_SECRET`; `status@broadcast` rejected pre-queue; `/health` (liveness) vs `/ready` (WAHA) split; secrets wired in Compose + cron trigger |
| Config | Compose/`.env.example` reconciled with secret vars; dev docs test-module table updated |
| Legacy code removal | All legacy task wrappers deleted (`complete_task`/`delete_task` in store, `complete_task` seam in tools, JSON auto-import path, `task_id_or_title`/`query_or_file_ids` alias fallbacks); `migrate_json_tasks` is the only JSON→SQLite path (repo marker `bulk_import_done`); zero `legacy` references in src/tests/scripts; suite green at 326 |
| Version A/B benchmark | Version-agnostic arm replay (`scripts/run_arm_replay.py`) old (`90cf82e`) vs new branch, 3 runs × 14 sanitized cases: old 26/42 (62%) vs new 35/42 (83%); mutation-integrity failures 8 case-runs → 0; residual: ambiguous bulk-delete success language (fixed by not_found guardrail), duplicate-create-update scorer literalism; report in `docs/production-evidence/version_comparison.md` |
| not_found guardrail hardening | `verify_action_fidelity`: when all mutation tools return `not_found` and the tool result ships no message, a verified ground-truth no-match message replaces the model text (previously the model's claim stood when the result had no message field); claiming language blocked outright by the mutation-claim detector; 2 tests in `tests/test_guardrail_contracts.py` |
| CI pipeline | `.github/workflows/ci.yml`: ruff (`src/ tests/ scripts/`), 14-module import smoke check, full pytest with isolated `DATA_DIR`, `docker compose config -q` validation; triggers on push (main + feat/**) and PRs |
| Backup restore verification | `scripts/verify_backup.sh`: extracts archive to `mktemp` dir, `PRAGMA integrity_check`, per-table row counts (`tasks`/`outbox`/`occurrences`/`reminder_policies`/`memory_candidates`), waha-session + catalog presence warnings; never touches live `data/` or `.env`; tested against synthetic archive |
| One-command rollback | `scripts/rollback.sh`: safety backup → explicit migration-boundary warning/confirmation → `git checkout` target commit → rebuild agent only (waha/scheduler/volumes/data untouched) → healthy check with log tail |
| Synthetic health check | `scripts/health_check.sh`: container run/healthy status for all 3 services, host-side `/health`, `/ready` (WAHA reachability), waha `/ping`, MCP tool-registration + outbox-drain log presence; non-zero exit on failure |

## Not Started

- Delivery duplicate-window: provider-side deduplication is not implemented (durable outbox + replay dedup suppress duplicates before send, but crash-after-provider-accept still relies on the provider)
- Domain-specific authorization policy and outbound target allowlisting beyond the central caller/chat/private-memory boundary
- Replay/A-B benchmark rerun with available stronger model/quota; current report is provider-inconclusive for arm B, so no model upgrade decision yet
- VPS rollout: push branch → sync VPS to branch → `python -m src.memory.migrate` → rebuild agent → `scripts/health_check.sh` (CI run + canary against a test WAHA session happen at deploy time)

## Blockers / Open Decisions

Blocking occurrence semantics (need user/product answer, then proceed):
1. Missed occurrences during downtime: skip / catch-up-once / replay? -> catch up or just ask for clarification
2. Weekly recurrence: local weekday-time vs fixed 7-day interval? -> idk
3. Reminder recipients, quiet hours, escalation defaults? -> if the user wants to

Non-blocking (decide before Phase 5 only):
- Authorized chat/group list; provider duplicate-detection window; migration maintenance window; backup RPO/RTO.

## Conventions

- Run tests from `helmis-agent/` (pyproject config); running from repo root silently mis-configures pytest and produced 16 phantom failures earlier — always verify with the full-suite count.
- Update this snapshot at each phase gate: move items Not Started → Done only with the verification result recorded in the same edit.
