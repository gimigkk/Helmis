# Development & Testing Guide

This guide covers local environment setup, architecture principles, writing tests, and running the pytest test suites.

---

## 1. Local Development Setup

### Prerequisites
- Python 3.12 or 3.14
- Git

### Environment Setup
```bash
cd helmis-agent
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

---

## 2. Running Test Suites

Run from `helmis-agent/` using the project venv:

```bash
./.venv/bin/pytest -q
```

Lint:
```bash
./.venv/bin/ruff check src/ tests/
```

Run with verbose output:
```bash
pytest -v
```

Run a specific test file:
```bash
pytest tests/test_vault.py -v
```

Run with test coverage report:
```bash
pytest --cov=src tests/
```

---

## 3. Test Suite Breakdown

The test suite consists of 41 test modules (466 cases) covering edge cases, adversarial inputs, data integrity, and multimodal integrations. Counts are asserted against the live suite:

| Test File | Cases | Focus Area |
|---|---|---|
| `test_scenario_matrix.py` | 112 | 111-scenario matrix: recurrence series, nag ladders, guardrail fidelity, memory ops, scheduling, cascade ordering |
| `test_intent_planning.py` | 25 | TurnPlan classification, destructive/ambiguity confirmation gates, forced tool calling |
| `test_group_policy.py` | 22 | Group admission: bot-mention detection, human-directed suppression |
| `test_vault.py` | 21 | Vault catalog, categories, link disambiguation, OCR mode, Office extractors |
| `test_memory.py` | 20 | Tasks, notes, people-directory env fallback, task categories (routine/work), routine filtering |
| `test_agent.py` | 18 | ReAct loop, tool execution, cascade fallbacks |
| `test_guardrail_contracts.py` | 16 | Mutation fidelity, chips gating, not_found ground truth, success-language blocks |
| `test_pdf_tools.py` | 15 | PDF merge/split/render, PDF⇄DOCX, compression |
| `test_semantic_memory.py` | 13 | Embeddings, cosine search, candidate queue, correction/supersession |
| `test_google_reader.py` | 13 | Google Workspace reader, pubhtml multi-tab parser, SSRF protection |
| `test_client.py` | 12 | WAHA HTTP client, retries, rate limiting |
| `test_guardrails_fidelity.py` | 12 | Two-step anti-hallucination, LaTeX conversion, turn interception |
| `test_proactive_engine.py` | 11 | Scheduler ticks, lead buffers, nag ladders, recurrence advance |
| `test_fastpath.py` | 11 | Chat/clock fast path, model escape hatch, provider-failure greeting |
| `test_tool_validation.py` | 10 | Parallel functionCalls, interleaved text, empty parts |
| `test_task_repository.py` | 10 | SQLite task/occurrence/lease/outbox contracts |
| `test_scheduled_actions.py` | 10 | Polymorphic job executors, allowlist/quarantine, near-horizon timers |
| `test_cascade.py` | 10 | Model discovery, cooldown demotion, hedged racing, key rotation |
| `test_mid_turn_steering_matrix.py` | 9 | Mid-turn steering, binary media sync, hard step ceiling |
| `test_compact_mode.py` | 8 | Compact query mode: domain tool subsets, core-prompt invariants |
| `test_schedule_routing.py` | 7 | Schedule/reminder-policy tools vs task-list routing |
| `test_queue.py` | 7 | FIFO per-chat debounce queue, burst batching |
| `test_adversarial_edge_cases.py` | 7 | Malformed payloads, chip stripping, injection attempts |
| `test_vision_ocr.py` | 6 | Vision OCR for raster PDFs/slides, caching |
| `test_skills.py` | 6 | On-demand skill discovery, playbook loading |
| `test_ingestion_policy.py` | 6 | Webhook admission + durable replay dedup window |
| `test_authorization.py` | 4 | Caller/chat/private-memory scope enforcement |
| `test_skill_proposals.py` | 5 | Skill proposal isolation and promotion |
| `test_quoted_messages.py` | 5 | Quoted message extraction across engines |
| `test_mcp_export.py` | 5 | MCP namespace delegation through internal registry |
| `test_fuzz_vault.py` | 5 | Filename/path/upload fuzzing |
| `test_data_integrity.py` | 5 | Concurrent writes, corruption resilience, atomic locking |
| `test_production_contracts.py` | 4 | Sanitized production regression invariants |
| `test_webhook_security.py` | 3 | Webhook auth, status-event isolation |
| `test_search.py` | 3 | DuckDuckGo/Tavily web search |
| `test_history.py` | 3 | Message dedup, multi-turn formatting |
| `test_delivery_recovery.py` | 3 | Outbox drain recovery after crashes |
| `test_burst_media_preservation.py` | 3 | Burst attachment labeling, media-failure degradation |
| `test_migration.py` | 1 | JSON→SQLite migration, source archiving |

Counts drift with development; run `pytest -q` from `helmis-agent/` for the live number (466 as of this writing).

---

## 4. Mocking & Isolation Strategy

To ensure fast, deterministic, offline test execution:
- **Google Gemini API**: Mocked via `unittest.mock.AsyncMock` or `pytest-mock` to simulate tool calls, structured responses, and `429` rate limits.
- **WAHA HTTP Client**: Mocked via `httpx.AsyncClient` transport handlers.
- **Storage & Vault**: Isolated in temporary directories (`tmp_path` fixtures) that are cleanly torn down after each test.
