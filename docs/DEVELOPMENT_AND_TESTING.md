# Development, Testing & Observability

This document provides guidelines for local development, executing the automated test suite, using the structured agent tracer, and extending Helmis with new tools, skills, or model providers.

---

## 1. Local Development Setup

Helmis requires **Python 3.12 or newer**.

### Setting Up Local Virtual Environment

```bash
# Navigate to the agent package directory
cd helmis-agent

# Create virtual environment
python3 -m venv .venv

# Activate virtual environment
source .venv/bin/activate

# Install dependencies in editable mode with development tools
pip install -e ".[dev]"
```

### Static Analysis & Linting

Helmis maintains strict typing and clean code standards via **Ruff** and **Mypy**:

```bash
# Run Ruff linter and formatter checks
ruff check .
ruff format --check .

# Run Mypy strict type checking
mypy src/
```

---

## 2. Automated Test Suite (Pytest)

The test suite contains **82 comprehensive unit, integration, binary data-integrity, and red-team adversarial fuzzing tests** located under `helmis-agent/tests/`. Tests execute against local mocks without requiring live WhatsApp or Gemini API connections.

```bash
# Run entire test suite
pytest -v

# Run a specific test module
pytest tests/test_vault.py -v
pytest tests/test_fuzz_vault.py -v
pytest tests/test_data_integrity.py -v
```

### Test Suite Architecture

```
helmis-agent/tests/
├── conftest.py                   # Shared pytest fixtures & mock environment variables
├── test_agent.py                 # Tool schema validation, dispatcher & state fidelity tests
├── test_client.py                # WAHA REST client, HTTP error handling & typing indicators
├── test_data_integrity.py        # 100% SHA-256 binary fidelity, PDF/ZIP preservation & streaming
├── test_fuzz_vault.py            # Adversarial PDF bombs, path traversal, Unicode & 30-task race conditions
├── test_history.py               # Message deduplication cache & multi-turn history builder
├── test_memory.py                # Structured memory store, task lifecycle, Indonesian time expressions
├── test_proactive_engine.py      # Proactive reminder engine, 30m kickoff, snooze & escalation loops
├── test_queue.py                 # Per-chat burst debouncing & concurrent chat isolation
├── test_quoted_messages.py       # Quoted message, voice note, and video context extraction
├── test_search.py                # DuckDuckGo web search integration & timeout resilience
├── test_semantic_memory.py       # Cosine similarity vector math, embeddings & two-pass deletion
└── test_vault.py                 # Document Vault CRUD, catalog self-healing, directory guards & pypdf
```

### Key Test Scenarios Covered

| Test File | Key Test Cases |
|---|---|
| `test_agent.py` | Validates all Gemini tools conform to Gemini API schemas; verifies `verify_action_fidelity()` overrides hallucinated text; tests error handling. |
| `test_client.py` | Uses `pytest-httpx` to mock WAHA endpoints (`/api/sendText`, `/api/sendFile`, `/api/messages`, `/api/startTyping`, `/api/sessions`); verifies error mapping. |
| `test_data_integrity.py` | Validates 100% SHA-256 byte preservation on 270 kB PDFs, JPEGs, and ZIPs; ensures ReAct tools bypass text degradation when media bytes are present. |
| `test_fuzz_vault.py` | Hardened against corrupt/0-byte PDF bombs, path traversal attacks (`/etc/passwd`), extreme Unicode/emojis, 10MB payloads, and 30-task POSIX file lock concurrency. |
| `test_proactive_engine.py` | Verifies Stage 1 kickoff notifications, Stage 2 due alerts, 15m urgent nag loops, and partner escalation logic. |
| `test_vault.py` | Validates Document Vault save, search, move with collision auto-versioning (`_v2.pdf`), `read_vault_file` (`pypdf` + UTF-8), catalog auto-repair, and directory safety. |
| `test_semantic_memory.py` | Verifies floating-point cosine similarity calculations; tests episodic fact storage, similarity threshold filtering, and two-pass deletion. |

---

## 3. Observability & Agent Turn Tracer (`logger.py`)

Helmis features a dedicated ANSI-color hierarchical terminal tracer (`AgentTurnTracer`) that logs every reasoning step, tool call, execution latency, and dispatched response in real time.

### Real-Time Terminal Trace Example

```
┌── [AGENT TURN START] ──────────────────────────────────────────
│  User   : Gilang (6281234567890@c.us)
│  Input  : "Catat task beli susu besok pagi jam 8"
│
│  ── Step 1/5 [gemini-3.1-flash-lite | 412ms] ──────────────────
│  Tool   : add_task
│  Args   : {
│             "title": "Beli susu",
│             "due": "2026-08-26 08:00 WIB",
│             "assignee": "Gilang"
│           }
│  Result : {
│             "status": "success",
│             "message": "Task 'Beli susu' berhasil disimpan dengan deadline '2026-08-26 08:00 WIB' untuk Gilang."
│           }
│
│  ── Step 2/5 [gemini-3.1-flash-lite | 340ms] ──────────────────
│  Output : Sip, task *Beli susu* sudah dicatat untuk besok pagi 08:00 WIB.
│
│  ── Turn Dispatched [752ms | 2 steps] ─────────────────────────
│  Reply : Sip, task *Beli susu* sudah dicatat untuk besok pagi 08:00 WIB.
└── [AGENT TURN END] ────────────────────────────────────────────
```

### Persistent Audit Log (`agent_traces.jsonl`)

Every turn is automatically recorded as a JSON object in `data/agent_traces.jsonl`:

```json
{
  "timestamp": 1756123456,
  "sender": "Gilang",
  "chat_id": "6281234567890@c.us",
  "input_text": "Catat task beli susu besok pagi jam 8",
  "has_media": false,
  "total_ms": 752.0,
  "steps_count": 2,
  "steps": [
    {
      "step": 1,
      "model": "gemini-3.1-flash-lite",
      "elapsed_ms": 412.0,
      "tool_call": {
        "name": "add_task",
        "args": {"title": "Beli susu", "due": "2026-08-26 08:00 WIB", "assignee": "Gilang"}
      },
      "tool_result": {"status": "success"}
    },
    {
      "step": 2,
      "model": "gemini-3.1-flash-lite",
      "elapsed_ms": 340.0,
      "final_text": "Sip, task *Beli susu* sudah dicatat untuk besok pagi 08:00 WIB."
    }
  ],
  "final_reply": "Sip, task *Beli susu* sudah dicatat untuk besok pagi 08:00 WIB.",
  "status": "dispatched"
}
```

### Healthcheck Noise Filtering (`NoHealthLogFilter`)
To keep container logs readable, `NoHealthLogFilter` completely silences periodic `/health`, `/ping`, and empty scheduler tick logs.

---

## 4. Extensibility Guide

### Adding a New Agent Tool

To add a new tool to Helmis:

1. **Declare the Function Schema in `GEMINI_TOOLS` (`helmis-agent/src/agent.py`)**:
   ```python
   {
       "name": "calculate_budget",
       "description": "Calculate remaining monthly budget based on recorded expenses.",
       "parameters": {
           "type": "OBJECT",
           "properties": {
               "category": {"type": "STRING", "description": "Budget category (e.g. 'Groceries', 'Utilities')"}
           },
           "required": ["category"]
       }
   }
   ```

2. **Implement the Logic in `_execute_tool_call_raw` (`helmis-agent/src/agent.py`)**:
   ```python
   elif func_name == "calculate_budget":
       category = args.get("category", "all")
       result_data = compute_budget(category)
       return {
           "status": "success",
           "data": result_data,
           "message": f"Sisa budget untuk {category} adalah Rp {result_data['remaining']:,}."
       }
   ```

3. **Add Unit Tests in `helmis-agent/tests/test_agent.py`**:
   Verify both successful execution and edge cases (e.g. invalid arguments).

### Adding a New Skill Playbook

1. Create a directory under `config/skills/<skill-name>/`.
2. Create `SKILL.md` inside that directory with YAML frontmatter:
   ```markdown
   ---
   name: budget-manager
   description: Guidelines and formatting rules for tracking household finances.
   ---

   # Budget Manager Skill

   ## Directives
   - Always format currency in Rupiah without decimals (e.g., `Rp 150.000`).
   - Use WhatsApp bold for category names: `*Groceries*`.
   ```
3. Restart `helmis-agent`. The skill will be automatically discovered by `load_all_skills()`.
