# Helmis

**Personal AI Executive Secretary for Gilang and Bunga** — powered by Google Gemini, autonomous multi-step reasoning, and persistent vector memory, delivered directly through WhatsApp.

---

## 📚 Deep Dive Technical Documentation

For complete architectural details, developer guides, and operational playbooks, explore our dedicated documentation suite:

| Document | Topic |
|---|---|
| 📖 **[Documentation Hub](file:///home/gimigkk/Desktop/Projects/Helmis/docs/INDEX.md)** | Master table of contents, maintainer paths & core system invariants |
| 🏗️ **[System Architecture](file:///home/gimigkk/Desktop/Projects/Helmis/docs/ARCHITECTURE.md)** | System topology, container orchestration & turn execution lifecycle |
| 🧠 **[Autonomous Agent Core](file:///home/gimigkk/Desktop/Projects/Helmis/docs/AGENT_CORE.md)** | Multi-step ReAct loop, dynamic model cascade, 12 tools & state guardrails |
| 💾 **[Memory & Vector Storage](file:///home/gimigkk/Desktop/Projects/Helmis/docs/MEMORY_AND_STORAGE.md)** | Atomic JSON store, 3072-dim embeddings & background fact extractor |
| 📡 **[Communication & Queues](file:///home/gimigkk/Desktop/Projects/Helmis/docs/COMMUNICATION_AND_ROUTING.md)** | WAHA REST client, webhook engine, per-chat 1.0s debouncing & auth |
| ⏰ **[Proactive Reminder Engine](file:///home/gimigkk/Desktop/Projects/Helmis/docs/PROACTIVE_ENGINE.md)** | Supercronic scheduler, reminder evaluator & automated WhatsApp dispatch |
| ⚙️ **[Configuration & Skills](file:///home/gimigkk/Desktop/Projects/Helmis/docs/CONFIGURATION_AND_SKILLS.md)** | Environment variables, system prompt, zero-emoji policy & skills |
| 🧪 **[Development & Testing](file:///home/gimigkk/Desktop/Projects/Helmis/docs/DEVELOPMENT_AND_TESTING.md)** | Local setup, 32-test pytest suite, step tracer & extensibility guide |
| 🚀 **[Deployment & Operations](file:///home/gimigkk/Desktop/Projects/Helmis/docs/DEPLOYMENT_AND_OPERATIONS.md)** | Docker Compose runbook, terminal QR auth, backups & troubleshooting |

---

## Key Capabilities

- 💬 **Native WhatsApp Delivery**: Communicates via private DMs and a shared Trio group chat with zero emojis and crisp WhatsApp formatting.
- 🧠 **Unified Brain with Discretion**: Remembers shared context, tasks, and directory contacts while preserving DM privacy.
- 📅 **Task & Schedule Intelligence**: Tracks deadlines, reassigns owners, updates statuses, and evaluates time in Jakarta local time (`WIB`).
- 🎙️ **Voice Notes & Multimodal OCR**: Dedicated 2-phase pipeline for verbatim audio transcription and visual document parsing (receipts, bills, schedules).
- ⚡ **Multi-Key Quota Rotation**: Dynamic cascade across Gemini models (`Flash-Lite` $\rightarrow$ `Flash` $\rightarrow$ `Gemma` $\rightarrow$ `Pro`) with automatic key rotation on rate limits (429).
- ⏰ **Proactive Outreach**: Periodic cron evaluations automatically dispatch reminders to WhatsApp before deadlines arrive.
- 🛡️ **State Fidelity Guardrails**: Validates that agent responses strictly match actual database outcomes without sycophancy or hallucinated confirmations.

---

## Tech Stack

| Component | Technology |
|---|---|
| **AI Agent Core** | Autonomous ReAct Engine with Google Gemini (`gemini-3.1-flash-lite`, `gemini-2.5-flash`, `gemini-2.5-pro`) |
| **Vector Embeddings** | Google `gemini-embedding-001` (3072-dimensional vector space with cosine similarity) |
| **WhatsApp Bridge** | [WAHA](https://waha.devlike.pro) (GOWS Native Engine) |
| **Webhook & Transport** | Starlette ASGI + Uvicorn + FastMCP SSE Server |
| **Proactive Triggers** | Supercronic (Alpine Linux Container) |
| **Orchestration** | Docker Compose v2 |

---

## Architecture Overview

```
WhatsApp Network ──► WAHA (GOWS) ──HTTP Webhook──► Helmis Agent Container
                                                         │
                         ┌───────────────────────────────┼───────────────────────────────┐
                         ▼                               ▼                               ▼
                 Google Gemini API               Local Persistence                Proactive Scheduler
             (Multi-Key Round-Robin)          (Atomic JSON & Vectors)          (5-minute periodic tick)
                         │                               │                               │
             ├── Flash-Lite / Flash / Pro        ├── Tasks & Directory           └── trigger.sh -> Webhook
             ├── 3072-dim Embeddings             ├── Semantic Episodic Facts
             └── Native Vision & Audio           └── Step Traces (JSONL)
```

---

## Project Structure

```
Helmis/
├── README.md                                  # You are here: Project Overview
├── docker-compose.yml                         # Production container stack
├── .env.example                               # Environment template
│
├── docs/                                      # Complete Deep Dive Documentation
│   ├── INDEX.md                               # Master Documentation Hub
│   ├── ARCHITECTURE.md                        # Architecture & Turn Lifecycle
│   ├── AGENT_CORE.md                          # ReAct Engine & Model Cascade
│   ├── MEMORY_AND_STORAGE.md                  # Storage & Vector Memory
│   ├── COMMUNICATION_AND_ROUTING.md           # WAHA Client & Debounce Queue
│   ├── PROACTIVE_ENGINE.md                    # Cron Scheduler & Reminders
│   ├── CONFIGURATION_AND_SKILLS.md            # Prompts, Skills & Directives
│   ├── DEVELOPMENT_AND_TESTING.md             # Pytest Suite & Turn Tracer
│   └── DEPLOYMENT_AND_OPERATIONS.md           # Runbooks & Troubleshooting
│
├── helmis-agent/                              # Core AI Agent & Bridge
│   ├── Dockerfile
│   ├── pyproject.toml
│   ├── src/
│   │   ├── agent.py                           # ReAct Loop, Cascade & Tools
│   │   ├── client.py                          # Typed WAHA REST Client
│   │   ├── history.py                         # Message Deduplication & Turns
│   │   ├── logger.py                          # Structured ANSI Step Tracer
│   │   ├── memory.py                          # Structured JSON Persistence
│   │   ├── models.py                          # Pydantic v2 Data Shapes
│   │   ├── proactive.py                       # Proactive Reminder Evaluator
│   │   ├── queue.py                           # Per-Chat Debounce Queue
│   │   ├── semantic_memory.py                 # Vector Store & Background Extractor
│   │   ├── server.py                          # FastMCP & Webhook Entry Point
│   │   └── webhook.py                         # Starlette Webhook Receiver
│   └── tests/                                 # 32 Automated Unit & Integration Tests
│
├── scheduler/                                 # Proactive Cron Container
│   ├── Dockerfile
│   ├── crontab
│   └── trigger.sh
│
├── config/                                    # System Prompts & Skills
│   ├── system-prompt.md                       # Core Persona & Formatting Rules
│   └── skills/                                # Specialized Capability Playbooks
│       ├── people-directory/
│       ├── schedule-manager/
│       ├── task-manager/
│       ├── reminder-engine/
│       ├── document-reader/
│       ├── shared-notes/
│       └── proactive-check/
│
└── scripts/
    ├── setup.sh                               # First-time host provisioning
    ├── auth.sh                                # Terminal ASCII QR code pairing
    └── backup.sh                              # Data backup & archive script
```

---

## Quickstart Guide

### 1. Clone & Run Setup
```bash
git clone https://github.com/your-username/helmis.git
cd helmis
chmod +x scripts/*.sh
./scripts/setup.sh
```

### 2. Configure Credentials (`.env`)
```bash
nano .env
```
Fill in your `GEMINI_KEY_1`, `WAHA_API_KEY`, `GILANG_PHONE`, `BUNGA_PHONE`, and `BOT_PHONE`.

### 3. Pair WhatsApp in Terminal
```bash
./scripts/auth.sh
```
Scan the ASCII QR code that appears in your terminal with the bot's WhatsApp phone.

### 4. Launch Stack
```bash
docker compose up -d
```

---

## Operational Commands

```bash
# Check service status
docker compose ps

# View live agent reasoning trace
docker compose logs -f agent

# View WhatsApp bridge logs
docker compose logs -f waha

# Run automated test suite
cd helmis-agent && .venv/bin/pytest -v

# Perform manual backup
./scripts/backup.sh
```

---

## License

Private repository for personal use by Gilang & Bunga.
