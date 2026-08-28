# Development & Testing Guide

This guide covers local environment setup, architecture principles, writing tests, and running the 15 pytest test suites (116 tests).

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

Run the entire test suite:

```bash
pytest
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

## 3. Test Suite Breakdown (21 Modules, 179 Tests)

The test suite consists of 21 comprehensive test modules covering edge cases, adversarial inputs, data integrity, and multimodal integrations:

| Test File | Cases | Focus Area |
|---|---|---|
| `test_adversarial_edge_cases.py` | 7 | Malformed payloads, fake tool chip stripping, injection attempts, boundary errors |
| `test_agent.py` | 18 | ReAct agent loop, tool execution, model cascade fallbacks |
| `test_cascade.py` | 7 | Dynamic Gemini model discovery, Flash-Lite prioritization, key rotation, skill loaders |
| `test_client.py` | 12 | WAHA HTTP client, retries, rate limiting, error responses |
| `test_data_integrity.py` | 5 | Concurrent file writes, JSON corruption resilience, atomic locking |
| `test_fuzz_vault.py` | 5 | Random fuzzing of filenames, paths, and document uploads |
| `test_google_reader.py` | 13 | Google Workspace reader (Docs, Sheets, Slides, Drive), published sheets (`pubhtml`) multi-tab parser, SSRF protection & sandbox caching |
| `test_guardrails_fidelity.py` | 12 | Two-step anti-hallucination guardrail, mutation claim detection, WhatsApp LaTeX to Unicode math conversion, extraction_mode badges, turn interception |
| `test_history.py` | 3 | Message deduplication, multi-turn history formatting |
| `test_memory.py` | 9 | Task creation, updating, completion, note storage, temporal context isolation |
| `test_mid_turn_steering_matrix.py` | 9 | Dynamic mid-turn user steering, binary media synchronization & multimodal inlineData |
| `test_pdf_tools.py` | 15 | PDF merge (zero-margin/A4), split, render image (PNG/JPG), images to PDF, PDF ⇄ DOCX, compression |
| `test_proactive_engine.py` | 6 | Scheduler evaluations, 2-stage lead-time buffers, nag loops |
| `test_queue.py` | 7 | FIFO per-chat debounce queue, 1.0s window burst batching |
| `test_quoted_messages.py` | 5 | Quoted message extraction across GOWS, NOWEB, and WEBJS |
| `test_scheduled_actions.py` | 6 | Polymorphic ToolJobExecutor, AgentLoopJobExecutor, near-horizon timers, expiration |
| `test_search.py` | 3 | DuckDuckGo and Tavily web search integration |
| `test_semantic_memory.py` | 4 | Gemini vector embeddings, cosine search, temporal supersession |
| `test_skills.py` | 6 | Dynamic on-demand skill discovery, playbook loading, prompt segregation |
| `test_vault.py` | 21 | Document Vault catalog, categories, link bookmark disambiguation, PDF text layer, force_ocr Vision mode & Office extractors (.docx, .pptx, .xlsx) |
| `test_vision_ocr.py` | 6 | Multimodal Gemini Vision OCR for raster scan PDFs, picture slides & image caching |

---

## 4. Mocking & Isolation Strategy

To ensure fast, deterministic, offline test execution:
- **Google Gemini API**: Mocked via `unittest.mock.AsyncMock` or `pytest-mock` to simulate tool calls, structured responses, and `429` rate limits.
- **WAHA HTTP Client**: Mocked via `httpx.AsyncClient` transport handlers.
- **Storage & Vault**: Isolated in temporary directories (`tmp_path` fixtures) that are cleanly torn down after each test.
