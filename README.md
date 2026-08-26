# Helmis

> **Self-hosted autonomous AI executive secretary for WhatsApp**, powered by Google Gemini, multi-step ReAct tool calling, localized semantic memory, and document vault.

[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue.svg)](https://www.python.org/)
[![Docker Compose](https://img.shields.io/badge/docker--compose-v2-2496ED.svg)](docker-compose.yml)
[![Tests](https://img.shields.io/badge/tests-107%20passed-brightgreen.svg)](helmis-agent/tests/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

## What is Helmis?

Helmis is a private, zero-latency AI executive secretary built for real-world personal coordination over WhatsApp. Operating across private direct messages and a shared couple group chat (*Trio Helmis*), it manages schedules, tasks, contacts, shared notes, a categorized Document Vault, PDF text extraction, live web search, and proactive deadline reminders with strict state fidelity and zero AI slop.

```
                    ┌──────────────────────────────┐
                    │      WhatsApp (WAHA GOWS)    │
                    └──────────────┬───────────────┘
                                   │  HTTP Webhook / REST API
                                   ▼
┌──────────────────────────────────────────────────────────────────────┐
│  Helmis Agent Container (Starlette Webhook + FastMCP SSE Server)     │
│                                                                      │
│  [1. Inbound Filter] ──► [2. 1.0s Chat Queue] ──► [3. Voice/OCR/PDF] │
│                                                          │           │
│  [6. State Guardrail] ◄── [5. ReAct Engine] ◄────────────┘           │
│           │                      │                                   │
│           ▼                      ▼                                   │
│     WhatsApp Reply       [Tools & Web Search]                        │
│                                  │                                   │
│            ┌─────────────────────┼─────────────────────┐             │
│            ▼                     ▼                     ▼             │
│   Atomic JSON Store     Document Vault        Vector Store           │
│   (Tasks, Notes)        (PDFs, Files, Docs)   (Semantic Memories)    │
└──────────────────────────────────┬───────────────────────────────────┘
                                   ▲
                                   │ 5-min Cron Trigger
                    ┌──────────────┴───────────────┐
                    │  Supercronic (Scheduler)     │
                    └──────────────────────────────┘
```

---

## Key Features

- **Domain-Driven Architecture**: Cleanly separated into `src/agent/` (brain & ReAct loop), `src/memory/` (storage & vector memory), `src/whatsapp/` (WAHA bridge & parser), and `src/tools/` (function dispatch & live search).
- **Gemini Multi-Key Cascade**: Seamless round-robin failover across multiple API keys and model tiers (`gemini-2.5-pro` → `gemini-2.5-flash` → `gemini-2.0-flash`).
- **Mid-Turn Mailbox Steering**: If a user sends a follow-up or correction while the agent is executing tools, the turn immediately steers to incorporate the new guidance without restarting.
- **Multimodal Intelligence**: Handles voice notes (via dedicated audio transcription), scanned images/receipts (OCR), digital PDFs (`pypdf` layer extraction), and quoted WhatsApp messages across GOWS, NOWEB, and WEBJS engines.
- **Categorized Document Vault**: Local persistent storage (`health`, `id_cards`, `travel`, `receipts`, `documents`, `media`, `projects`) with original filename preservation and atomic catalog locking.
- **Proactive Cron Engine**: Autonomous 5-minute evaluation loop with 2-stage lead-time buffering, deadline alerts, and 10-minute nag loops for critical tasks.
- **100% Single Source of Truth System Prompt**: Persona, behavior, group chat dynamics, and formatting rules live entirely in `config/system-prompt.md`.
- **Zero AI Slop**: Communicates in authentic Indonesian WhatsApp register (*sat-set*, direct, conversational) with strict zero-emoji enforcement and conscious multi-bubble splitting (`---`).

---

## Directory Layout

```
Helmis/
├── config/
│   ├── skills/                       # Markdown skill playbooks (8 modular skills)
│   └── system-prompt.md              # Single source of truth system prompt
├── data/                             # Local persistent storage (gitignored)
│   ├── helmis_memory.json            # Tasks, notes, directory records
│   ├── file_catalog.json             # Document vault metadata catalog
│   ├── semantic_memories.json        # 3072-dim episodic vector embeddings
│   ├── vault/                        # Binary documents, PDFs, scans, receipts
│   └── agent_traces.jsonl            # Execution traces & step logs
├── docs/                             # Complete technical documentation (10 guides)
├── helmis-agent/
│   ├── src/
│   │   ├── agent/                    # ReAct loop, cascade, proactive, tracer
│   │   ├── memory/                   # Atomic store, semantic vector, vault
│   │   ├── whatsapp/                 # Client, history, models, parser, processor, queue
│   │   ├── tools/                    # Tool registrations, schemas, search
│   │   ├── server.py                 # FastMCP SSE & Starlette webhook entry point
│   │   └── __init__.py
│   └── tests/                        # 14 pytest test suites (107 tests passing)
├── scheduler/                        # Supercronic proactive cron runner
├── docker-compose.yml                # Multi-container orchestration
└── .env                              # Environment secrets and phone numbers
```

---

## Quickstart & Setup

### 1. Clone & Configure Environment
```bash
git clone https://github.com/gimigkk/Helmis.git
cd Helmis
cp .env.example .env
nano .env
```

Configure your `.env` with:
- `GILANG_PHONE` and `BUNGA_PHONE` (E.164 formatted, e.g. `6281234567890`)
- `BOT_PHONE`
- `GEMINI_KEY_1`, `GEMINI_KEY_2`, etc.
- `WAHA_API_KEY` and `WAHA_DASHBOARD_PASSWORD`

### 2. Start Services with Docker Compose
```bash
docker compose up -d --build
```

### 3. Connect WhatsApp
1. Open the WAHA dashboard in your browser: `http://<your-server-ip>:3005` (or mapped port).
2. Authenticate with `admin` and your `WAHA_DASHBOARD_PASSWORD`.
3. Scan the QR code using WhatsApp on your bot phone number.
4. Once the session is `WORKING`, Helmis is live!

---

## Testing & Quality Assurance

Run the comprehensive test suite locally:

```bash
cd helmis-agent
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest
```

```text
============================= 107 passed in 2.47s ==============================
```

---

## Documentation Index

| Guide | Description |
|---|---|
| [System Architecture](docs/ARCHITECTURE.md) | High-level topology, domain packages, container network, and lifecycle. |
| [Agent Core & ReAct Loop](docs/AGENT_CORE.md) | ReAct loop, Gemini cascade, mid-turn steering, and tracing. |
| [Communication & Routing](docs/COMMUNICATION_AND_ROUTING.md) | WAHA integration, payload parser, queue debouncing, and group chat dynamics. |
| [Memory & Storage](docs/MEMORY_AND_STORAGE.md) | Atomic JSON store, vector semantic memory, and Document Vault. |
| [Proactive Engine](docs/PROACTIVE_ENGINE.md) | Scheduler cron triggers, lead-time buffering, and nag loops. |
| [Configuration & Skills](docs/CONFIGURATION_AND_SKILLS.md) | Single Source of Truth prompt, skill playbooks, and environment variables. |
| [Deployment & Operations](docs/DEPLOYMENT_AND_OPERATIONS.md) | VPS deployment, zero-downtime updates, healthchecks, and backups. |
| [Development & Testing](docs/DEVELOPMENT_AND_TESTING.md) | Test suites, mock strategies, fixtures, and code standards. |
| [Scenarios & Playbooks](docs/SCENARIOS_AND_PLAYBOOKS.md) | Real-world operational scenarios, error handling, and multimodal workflows. |

---

## License

MIT License. See [LICENSE](LICENSE) for details.
