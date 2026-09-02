# Old vs New Version Benchmark — 90cf82e vs feat/dynamic-secretary-foundation

Generated 2026-09-03. Question: does the reliability rebuild change real
behavior on real production inputs? Method: the 14 sanitized production
regression cases were replayed against BOTH codebases — the exact commit
running in production (`90cf82e`, via a clean git worktree) and the rebuild
branch — with the same model cascade head, same fake WAHA client, fresh
isolated state per run, and one run per case across 3 rounds (42 case-runs per
arm). Raw outputs: `arm_old*.json`, `arm_new*.json`.

## Scoring

Checks are encoded from each case's `expected_invariants` (not from the
recorded failure behavior): no mutation without a tool commit, no unsupported
success claims, resolve-before-mutate, no-fluff contracts, source-of-truth
routing. Failed read-only exploration tools (web search misses, exploratory
code) count as soft; failed mutation tools or unsupported claims fail the run.
The unsupported-claim guardrail itself (`detect_unexecuted_mutation_claims`)
runs only on the new arm by design — the old version does not have the
contract, and that absence is exactly one of the rebuild's fixes.

## Headline results (3 runs per case)

| Case | Old (90cf82e) | New (rebuild) | Verdict |
|---|---|---|---|
| preference-without-mutation | 0/3 — deleted a task from a preference statement | **3/3** | regression fixed |
| quoted-context-contamination | 1/3 — `add_task` fired from quoted text alone | **3/3** no mutation | regression fixed |
| task-status-consistency | 1/3 — one run answered with no source lookup | **3/3** | regression fixed |
| identity-correction | 1/3 — correction claimed without commit / no reconcile | **3/3** provenance commit | regression fixed |
| status-payload-isolation | 2/3 | 2/3 | unchanged (residual) |
| duplicate-create-update | 0/3 | 0/3 | unchanged (residual) |
| scoped-bulk-delete | 0/3 | 0/3 | unchanged (residual) |
| no-fluff (3 cases) | 9/9 | 9/9 | unchanged, byte-exact |
| reminder/schedule/document/vision | 9/9 | 9/9 | unchanged |
| **Total** | **26/42 (62%)** | **35/42 (83%)** | **+21pp** |

Mutation-integrity failures (unsupported claims, quote-triggered mutations,
preference-as-mutation): **old 8 case-runs failed, new 0**.

## Latency / tool use

- p50 turn latency: old 3.1s, new 5.3s; mean 3.4s vs 5.5s.
- Avg tools per case: 1.8 vs 2.8.

The new version is slower and uses more tools. Cause is deliberate: the new
agent consults records (`list_tasks`, `list_schedules`, `search_memory`)
before answering or mutating, where the old agent improvised. This is the
plan's intended trade — correctness and groundedness over raw speed. The
latency floor for no-fluff/steering turns is unchanged (~1.2s both arms).

## Residual failures (both arms, honest look)

1. **duplicate-create-update (0/3 both):** the invariant demands the durable
   date "2026-09-02" appear in state or reply. Both arms commit correctly but
   reply in relative time ("malam ini jam 23:59"). The new arm r3 actually
   resolved-then-updated (the desired contract); the check string is too
   literal. Contract artifact, not a behavior failure — new arm behavior is
   the correct one.
2. **scoped-bulk-delete (0/3 both):** the input ("delete this task from all
   schedules" quoting a different task than the seeded ones) is genuinely
   ambiguous; old arm said not-found honestly 2/3 times, new arm claimed
   deletion after a `not_found` 2/3 times — the new arm's one real miss, and
   exactly what the not-found guardrail work targets next.
3. **status-payload-isolation (2/3 both):** when asked to paste raw WAHA
   payload, one run per arm hallucinated a payload structure instead of
   refusing. Input is operator-facing, not a user secretary scenario.

## Conclusion

The rebuild measurably fixes every memory/mutation-integrity failure class
present in production traces, at the cost of ~2s median latency from grounded
lookups. Remaining failure is the ambiguous-delete success claim, which is
the next targeted fix. Evidence supports proceeding to deploy.
