# Production Evidence

## Model Replay Benchmark

`model_benchmark_results.json` contains a replay of the sanitized regression
corpus using identical isolated state and tools. The production cascade arm
ran all 14 cases. The stronger-model arm was recorded but is not decision-grade:
the provider returned the agent connection fallback for all 14 runs. Do not use
its `0/14` score as a model-quality result. Rerun after provider capacity is
available.

Captured locally on 2026-09-02 from the production `/opt/helmis` deployment using read-only SSH commands. No production data or containers were modified.

## Primary Interaction Data

- `agent_interactions.jsonl`: 363 normalized, sanitized turn records. Use this for replay tooling and automated assertions.
- `agent_interactions.md`: concise human-readable transcript of the same 363 turns, including user input, ordered tool names, sanitized arguments, result status, timings, and final reply. Bulky tool-result bodies are omitted.
- `regression_cases.json`: 14 selected failure-oriented cases with expected invariants.
- `analysis.md`: evidence-based findings and limitations.

The structured source was production `data/agent_traces.jsonl`: 363 valid records, 330 tool-bearing steps, and 46 media turns. Identifiers, credentials, host details, and ANSI control sequences were removed from retained artifacts. Trace timestamps are retained as correlation handles.

## Canonical Evidence

Use `agent_interactions.jsonl` for replay and `regression_cases.json` for contract tests. `analysis.md` records the findings and evidence limits.
