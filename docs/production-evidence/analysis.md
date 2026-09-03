# Production Evidence Analysis

Captured 2026-09-02 from the production `/opt/helmis` deployment using read-only `docker compose logs --tail 100` commands. The raw output was sanitized locally before being retained. The selected regression cases are derived from the production `data/agent_traces.jsonl`; no production data was modified.

## Direct evidence

### 1. Duplicate/unsafe mutation sequence

The latest agent trace shows one natural-language request for a task due tonight producing:

1. `add_task` with an obsolete date (`2026-02-09 23:59 WIB`)
2. `update_task` by title to the requested date (`2026-09-02 23:59 WIB`)
3. A final response claiming the task was directly recorded and updated

This is evidence for a create-then-repair mutation path, title-based addressing, and a risk of leaving a phantom old task. The fix should resolve an existing record before mutation and commit one verified operation.

### 2. Title-based bulk deletion is incomplete by contract

A request to remove an attendance task everywhere caused two separate `delete_task` calls using title variants: `Isi Absensi ...` and `Absen Mata Kuliah ...`. The final response said all related reminders were deleted, but the trace exposes neither an exact affected count nor a postcondition check. This supports canonical subject keys, explicit bulk scope, stable IDs, and verified reconciliation.

### 3. Read-only results are narrated as durable policy

A preference request saying to keep only the attendance task produced no tool call, yet the response said the policy would apply going forward. This is not proof that existing records were cleaned up. The fixture preserves this as a distinction between acknowledging a preference and claiming a mutation.

### 4. No-fluff and explicit steering are violated

The request `Kirim no fluff` invoked `remember_fact` and appended a tool chip to a copyable answer. The request `Gausah tool call, kirim no fluff` did the same. These are direct examples of unnecessary side effects, ignored mid-turn steering, and output contamination. No-fluff routing must happen before model/tool execution.

### 5. Schedule source and task source are conflated

The schedule-reconciliation trace searched vault files and notes, then created one reminder while claiming a complete seven-course set had been configured. A follow-up for another course searched memory and asked the user for the time, despite a reminder later appearing for that course. This indicates inconsistent sources of truth and unverified bulk claims.

### 6. Memory receives identity data from untrusted or weakly grounded context

The trace records `remember_fact` for an identity number extracted from a document upload. Nearby turns show the user correcting a previously wrong identity number and asking why memory was called repeatedly. The current trace format has no visible source message ID, confidence, scope, or correction/supersession metadata. This supports provenance-bearing memory and a default pause on automatic crystallization.

### 7. Document and status follow-ups can answer without retrieval evidence

A document follow-up asking for the final slide has one model step and no document retrieval tool in the trace, while still returning detailed slide content. Separately, a question about a WhatsApp status retrieved a normal group message payload. These are evidence for grounded document answers, status-event isolation, and preservation of actual message IDs/source chats.

## Service and trace observations

- The captured service output was mostly operational noise: scheduler HTTP 200 trigger messages and WAHA `/api/sessions` polling. It proves trigger/health liveness only; it does not prove an occurrence claim, outbox enqueue, provider send, or delivery result. Those raw captures were intentionally removed from this cleaned evidence set.
- The structured agent trace contains 363 turns: 341 `dispatched` and 22 `silent_no_reply`. The dominant model is `gemini-flash-lite-latest` (678 recorded steps), and task mutations are frequent (`add_task` 64, `delete_task` 15, `complete_task` 18, `update_task` 12). These counts describe exposure, not failure counts.
- Semantic-memory logs show automatic supersession events based on similarity (`sim=0.96` and `sim=0.88`) without provenance visible in the log line.

## Limits

The retained structured traces do not contain a complete inbound/outbound message correlation or provider delivery receipt. They are sufficient to reproduce the contract failures above, but not to calculate duplicate-delivery rate or prove crash-after-send behavior. Those require durable message IDs, idempotency keys, outbox state, provider message IDs, and a longer retained trace window.

## Regression corpus

`regression_cases.json` contains 14 sanitized cases selected from production traces. It is a behavioral corpus, not yet an executable pytest suite. The `expected_invariants` field is the contract to encode in the offline harness.
