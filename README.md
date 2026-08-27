# Helmis

> **Self-hosted autonomous AI executive secretary for WhatsApp**, powered by Google Gemini, multi-step ReAct tool calling, localized semantic memory, and document vault.

[![Python](https://img.shields.io/badge/Python-3.12%20%7C%203.14-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![Google Gemini](https://img.shields.io/badge/Google%20Gemini-Cascade%20API-8E75C2?style=for-the-badge&logo=googlegemini&logoColor=white)](https://ai.google.dev/)
[![WhatsApp](https://img.shields.io/badge/WhatsApp-WAHA%20GOWS-25D366?style=for-the-badge&logo=whatsapp&logoColor=white)](https://waha.devlike.pro/)
[![FastMCP](https://img.shields.io/badge/MCP-FastMCP%20SSE-00D26A?style=for-the-badge&logo=fastapi&logoColor=white)](https://modelcontextprotocol.io/)
[![Docker](https://img.shields.io/badge/Docker%20Compose-v2-2496ED?style=for-the-badge&logo=docker&logoColor=white)](docker-compose.yml)
[![Tests](https://img.shields.io/badge/Tests-142%20Passed-4c1?style=for-the-badge&logo=pytest&logoColor=white)](helmis-agent/tests/)
[![Architecture](https://img.shields.io/badge/Engine-Autonomous%20ReAct-FF6B6B?style=for-the-badge&logo=diagram-next&logoColor=white)](docs/AGENT_CORE.md)
[![Timezone](https://img.shields.io/badge/Timezone-WIB%20(UTC%2B7)-F39C12?style=for-the-badge&logo=clockify&logoColor=white)](config/system-prompt.md)
[![License: MIT](https://img.shields.io/badge/License-MIT-111111?style=for-the-badge&logo=opensourceinitiative&logoColor=white)](LICENSE)

---

## What is Helmis?

Helmis is a private, zero-latency AI executive secretary built for real-world personal coordination over WhatsApp. Operating across private direct messages and a shared couple group chat (*Trio Helmis*), it manages schedules, tasks, contacts, shared notes, a categorized Document Vault, PDF manipulation & text extraction, live web search, dynamic media dispatching, and proactive deadline reminders with strict state fidelity and zero AI slop.

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
│                                                                      │
│   [Near-Horizon Exact-Second Timers (asyncio.sleep <= 10m)]          │
└──────────────────────────────────┬───────────────────────────────────┘
                                   ▲
                                   │ 1-min Cron Trigger (* * * * *)
                    ┌──────────────┴───────────────┐
                    │  Supercronic (Scheduler)     │
                    └──────────────────────────────┘
```

---

## Key Features

- **Domain-Driven Architecture**: Cleanly separated into `src/agent/` (brain & ReAct loop), `src/memory/` (storage & vector memory), `src/whatsapp/` (WAHA bridge & parser), and `src/tools/` (function dispatch & live search).
- **Gemini Multi-Key Cascade**: Seamless round-robin failover across multiple API keys and model tiers (`gemini-2.5-pro` → `gemini-2.5-flash` → `gemini-2.0-flash`).
- **Mid-Turn Mailbox Steering**: If a user sends a follow-up or correction while the agent is executing tools, the turn immediately steers to incorporate the new guidance without restarting.
- **Multimodal Intelligence & Dynamic Media Routing**: Handles voice notes, OCR, PDF extraction, and intelligent outbound media dispatch (inline photo bubbles via `/api/sendImage` or uncompressed raw files via `/api/sendFile` on request).
- **Categorized Document Vault**: Local persistent storage (`health`, `id_cards`, `travel`, `receipts`, `documents`, `media`, `projects`) with original filename preservation, atomic catalog locking, and clean caption delivery.
- **Proactive Cron & Exact-Second Timers**: Autonomous 1-minute crontab ticks (`* * * * *`) combined with near-horizon in-process asyncio countdown timers, polymorphic job executors (`ToolJobExecutor` & `AgentLoopJobExecutor`), 2-stage lead-time buffering, and 10-minute nag loops for critical tasks.
- **100% Single Source of Truth System Prompt**: Persona, behavior, group chat dynamics, and formatting rules live entirely in `config/system-prompt.md`.
- **Zero AI Slop**: Communicates in authentic Indonesian WhatsApp register (*sat-set*, direct, conversational) with strict zero-emoji enforcement and conscious multi-bubble splitting (`---`).

---

## Directory Layout

```
Helmis/
├── config/
│   ├── skills/                       # Markdown skill playbooks (9 modular skills)
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
│   └── tests/                        # 16 pytest test suites (122 tests passing)
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
