# Helmis

> **Self-hosted autonomous AI executive secretary for WhatsApp**, powered by Google Gemini, multi-step ReAct tool calling, and local semantic memory.

[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue.svg)](https://www.python.org/)
[![Docker Compose](https://img.shields.io/badge/docker--compose-v2-2496ED.svg)](docker-compose.yml)
[![Tests](https://img.shields.io/badge/tests-45%20passed-brightgreen.svg)](helmis-agent/tests/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

## What is Helmis?

Helmis is a zero-latency, private AI secretary built for real-world personal coordination over WhatsApp. It operates across private direct messages and a shared group chat, managing schedules, tasks, contacts, shared notes, live web search, and proactive reminders with strict state fidelity.

```
                    ┌──────────────────────────────┐
                    │      WhatsApp (WAHA GOWS)    │
                    └──────────────┬───────────────┘
                                   │  HTTP Webhook / REST
                                   ▼
┌──────────────────────────────────────────────────────────────────────┐
│  Helmis Agent (Starlette + FastMCP Server)                           │
│                                                                      │
│  [1. Inbound Filter] ──► [2. 1.0s Chat Queue] ──► [3. Voice/OCR]     │
│                                                          │           │
│  [6. State Guardrail] ◄── [5. ReAct Engine] ◄────────────┘           │
│           │                      │                                   │
│           ▼                      ▼                                   │
│     WhatsApp Reply       [20 Native Tools]                           │
│                                  │                                   │
│            ┌─────────────────────┴─────────────────────┐             │
│            ▼                                           ▼             │
│   Atomic JSON Store                           3072-dim Vector Store  │
│   (Tasks, Notes, People)                      (Semantic Memories)    │
└──────────────────────────────────┬───────────────────────────────────┘
                                   ▲
                                   │ 5-min Cron Trigger
                    ┌──────────────┴───────────────┐
                    │  Supercronic (Scheduler)     │
                    └──────────────────────────────┘
```

---

## Live Interaction Examples

### 1. Multi-Step Task Management with Proactive Reminders
```text
[Gilang]: Besok jam 18:30 ada meeting dengan Pak Budi di Kuningan, ingetin ya
[Helmis]: Siap, reminder *Meeting dengan Pak Budi di Kuningan* sudah dijadwalkan untuk besok pukul 18:30 WIB.
```

### 2. Quoted Voice Note Comprehension (Multimodal)
```text
> [Bunga]: "Pesan Suara / Voice Note (8 detik)"

[Gilang]: Ini maksudnya apa ya?
[Helmis]: Bunga mengingatkan untuk tidak lupa membayar tagihan listrik sebelum jam 12 siang hari ini.
```

### 3. Living Shared Lists & Live Web Search
```text
[Gilang]: Cariin restoran sunda enak dekat Senopati terus tambahin ke catatan rekomendasi kita
[Helmis]: Menemukan *Dapur Sunda Senopati* (buka sampai 22:00 WIB). Restoran sudah saya tambahkan ke catatan *Rekomendasi Restoran*.
```

---

## Core Engineering Primitives

| Primitive | Description |
|---|---|
| **Autonomous ReAct Core** | Up to 5-step ReAct reasoning loop with 20 native tools (`add_task`, `list_tasks`, `save_note`, `get_note`, `list_notes`, `append_to_note`, `web_search`, `send_whatsapp_media`, `send_whatsapp_message`, `send_status_update`, etc.). |
| **Model Cascade & Quota Rotation** | Dynamic speed-first model prioritization (`Flash-Lite` $\rightarrow$ `Flash` $\rightarrow$ `Gemma` $\rightarrow$ `Pro`) with multi-key round-robin rotation on HTTP 429 rate limits. |
| **Burst Debounce Queue** | Per-chat FIFO queues with a 1.0s sliding debounce window that merges rapid-fire text fragments into single unified turns. |
| **GOWS Protobuf Quote Parser** | Native extraction of WhatsApp quoted metadata across text, voice notes (with duration and transcription), images (with captions), documents, and stickers. |
| **State Fidelity Guardrails** | Structural output verification that forces the model to report exact database outcomes, eliminating sycophantic false confirmations. |
| **Dual Storage Engine** | Thread-safe atomic JSON writes (`helmis_memory.json`) for relational entities alongside 3072-dimensional vector embeddings (`semantic_memories.json`) for episodic recall. |
| **Supercronic Proactive Engine** | Standalone Alpine Linux scheduler container evaluating due dates in Jakarta time (`WIB`) every 5 minutes. |

---

## Quickstart

### 1. Bootstrap Host Environment
```bash
git clone https://github.com/your-username/helmis.git
cd helmis
chmod +x scripts/*.sh
./scripts/setup.sh
```

### 2. Configure Environment (`.env`)
```bash
cp .env.example .env
nano .env
```
Provide your `GEMINI_KEY_1`, `WAHA_API_KEY`, `GILANG_PHONE`, `BUNGA_PHONE`, and `BOT_PHONE`.

### 3. Authenticate WhatsApp Session
```bash
./scripts/auth.sh
```
Scan the terminal ASCII QR code with the bot's WhatsApp account.

### 4. Start Production Containers
```bash
docker compose up -d
```

---

## Developer & Operational Tooling

```bash
# Inspect container health & runtime status
docker compose ps

# Follow live agent turn traces & tool executions
docker compose logs -f agent

# Run the automated pytest suite (45 tests)
cd helmis-agent && .venv/bin/pytest -v

# Run type checker & linter
cd helmis-agent && .venv/bin/ruff check . && .venv/bin/mypy src tests

# Create manual persistent backup
./scripts/backup.sh
```

---

## Repository Structure

```
Helmis/
├── docker-compose.yml                         # Container stack orchestration
├── .env.example                               # Environment template
│
├── helmis-agent/                              # Core AI Agent & Webhook Bridge
│   ├── src/
│   │   ├── agent.py                           # Lean ReAct Loop Orchestrator (~230 lines)
│   │   ├── agent_tools.py                     # GEMINI_TOOLS Schema & 20-Tool Dispatcher
│   │   ├── cascade.py                         # Dynamic Model Cascade & Multi-Key Rotation
│   │   ├── client.py                          # Typed WAHA Async REST Client
│   │   ├── guardrails.py                      # State Fidelity Guardrails & Directives
│   │   ├── history.py                         # Message Deduplication & Turn Formatter
│   │   ├── logger.py                          # Structured ANSI Step Tracer
│   │   ├── memory.py                          # Thread-Safe Atomic JSON Store
│   │   ├── models.py                          # Pydantic v2 Schema Definitions
│   │   ├── proactive.py                       # Proactive Deadline & Task Evaluator
│   │   ├── queue.py                           # Per-Chat Burst Debounce Queue
│   │   ├── search.py                          # Live Web Search (DuckDuckGo & Tavily)
│   │   ├── semantic_memory.py                 # Vector Store & Background Fact Extractor
│   │   ├── server.py                          # FastMCP SSE Server Entry Point
│   │   ├── transcribe.py                      # Phase-1 Multimodal Speech Extraction
│   │   └── webhook.py                         # Starlette Webhook & GOWS Quote Extractor
│   └── tests/                                 # 46 Unit & Integration Tests
│
├── scheduler/                                 # Proactive Scheduler Container
│   ├── Dockerfile
│   ├── crontab                                # 5-minute periodic tick definition
│   └── trigger.sh                             # Webhook trigger script
│
├── config/                                    # Personas & Capability Playbooks
│   ├── system-prompt.md                       # Core Identity & Strict Zero-Emoji Rule
│   └── skills/                                # Modular Skill Directives
│
└── docs/                                      # Comprehensive Technical Documentation
    ├── INDEX.md                               # Master Documentation Hub
    ├── ARCHITECTURE.md                        # Architecture & Lifecycle
    ├── AGENT_CORE.md                          # ReAct Engine & Model Cascade
    ├── MEMORY_AND_STORAGE.md                  # Storage & Vector Memory
    ├── COMMUNICATION_AND_ROUTING.md           # WAHA Client, Quotes & Debounce Queue
    ├── PROACTIVE_ENGINE.md                    # Cron Scheduler & Reminders
    ├── CONFIGURATION_AND_SKILLS.md            # Prompts, Skills & Directives
    ├── DEVELOPMENT_AND_TESTING.md             # Pytest Suite & Turn Tracer
    ├── DEPLOYMENT_AND_OPERATIONS.md           # Runbooks & Troubleshooting
    └── SCENARIOS_AND_PLAYBOOKS.md             # 50 Real-World Scenarios & Thinking Out Loud Matrix
```

---

## Documentation

For comprehensive technical specifications, explore the **[Documentation Hub](docs/INDEX.md)**:

- **[System Architecture & Turn Lifecycle](docs/ARCHITECTURE.md)**
- **[Autonomous Agent Core & 15 Tools](docs/AGENT_CORE.md)**
- **[Memory Architecture & Vector Store](docs/MEMORY_AND_STORAGE.md)**
- **[Communication, Quotes & Debounce Queues](docs/COMMUNICATION_AND_ROUTING.md)**
- **[Proactive Reminder Subsystem](docs/PROACTIVE_ENGINE.md)**
- **[Configuration & Skills Playbooks](docs/CONFIGURATION_AND_SKILLS.md)**
- **[Development & Testing Guide](docs/DEVELOPMENT_AND_TESTING.md)**
- **[Deployment & Troubleshooting Runbook](docs/DEPLOYMENT_AND_OPERATIONS.md)**
- **[50 Real-World Scenarios & Playbooks](docs/SCENARIOS_AND_PLAYBOOKS.md)**

---

## License
 
Distributed under the MIT License. See [LICENSE](LICENSE) for details.
