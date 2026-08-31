# Helmis

> **Self-hosted autonomous AI executive secretary for WhatsApp**, powered by Google Gemini, multi-step ReAct tool calling, localized semantic memory, and document vault.

[![Python 3.12+](https://img.shields.io/badge/Python-3.12+-3776AB?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)
[![Google Gemini](https://img.shields.io/badge/Google%20Gemini-Multimodal%20Cascade-8E75C2?style=flat-square&logo=googlegemini&logoColor=white)](https://ai.google.dev/)
[![WhatsApp Engine](https://img.shields.io/badge/WhatsApp-WAHA%20Core-25D366?style=flat-square&logo=whatsapp&logoColor=white)](https://waha.devlike.pro/)
[![Tests](https://img.shields.io/badge/Tests-179%20Passing-success?style=flat-square&logo=pytest&logoColor=white)](docs/DEVELOPMENT_AND_TESTING.md)
[![License](https://img.shields.io/badge/License-MIT-black?style=flat-square)](LICENSE)

---

## What is Helmis?

Helmis is a private, zero-latency **AI Executive Secretary** built for real-world personal coordination over WhatsApp. Supporting both **Personal Solo Mode** (1 user) and **Duo Mode** (couples/partners in a shared group chat), it manages schedules, tasks, contacts, shared notes, an encrypted Document Vault, PDF manipulation & text extraction, live web search, dynamic media dispatching, and proactive deadline reminders with strict state fidelity and zero AI slop.

```
                    ┌──────────────────────────────┐
                    │      WhatsApp (WAHA Core)    │
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

## Key Highlights

- **Forced Tool Calling & Anti-Promissory Guardrail**: Pre-emptive intent classification automatically sets `toolConfig.mode = "ANY"` on action turns, mathematically forcing Gemini to emit function calls instead of making unexecuted verbal promises (*"nanti gw geser"*).
- **Procedural Memory & Self-Learning Skills**: Learns new operational playbooks taught by users in WhatsApp (`create_skill`, `update_skill`, `list_skills`) and persists them as portable `SKILL.md` files adhering to the `agentskills.io` standard.
- **Autonomous Auto-Crystallization**: An asynchronous zero-latency background worker reflects on multi-step workflows and autonomously synthesizes reusable operational skills (Voyager & Hermes Agent pattern).
- **Universal Code Execution Sandbox**: Executes Python 3 in an isolated subprocess (`execute_code`) for dynamic calculations, date/time manipulation in WIB, and data processing without rigid tool constraints.
- **Autonomous ReAct Loop & Cascade**: Seamless round-robin failover across multiple Google Gemini API keys and tiers (`gemini-2.5-pro` → `gemini-2.5-flash` → `gemini-2.0-flash`).
- **Mid-Turn Mailbox Steering**: If a user sends a follow-up or correction while the agent is executing tools, the turn immediately steers to incorporate the new guidance in real-time.
- **Multimodal Intelligence & Vision OCR**: Extracts text from scanned PDFs, diagrams, spreadsheets, and presentation slides via Gemini Vision OCR (150 DPI page pixmaps).
- **Categorized Document Vault**: Local persistent storage (`health`, `id_cards`, `travel`, `receipts`, `documents`, `media`, `projects`) with original filename preservation, atomic catalog locking, and clean WhatsApp caption dispatch.
- **Google Workspace Reader**: Directly inspects published Google Sheets (`pubhtml` with multi-tab support), Google Docs, Slides, and Drive documents with 30-minute sandbox caching.
- **Proactive Cron & Exact-Second Timers**: Autonomous 1-minute crontab ticks combined with near-horizon in-process asyncio countdown timers, 2-stage lead-time buffering, and 10-minute nag loops for critical commitments.
- **100% Single Source of Truth System Prompt**: Persona, behavior, group chat dynamics, and formatting rules live entirely in `config/system-prompt.md` (with zero-conflict `config/system-prompt.local.md` support for clones).
- **Zero AI Slop**: Communicates in authentic Indonesian WhatsApp register (*sat-set*, direct, conversational) with strict zero-emoji enforcement and conscious multi-bubble splitting (`---`).

---

## Quickstart & Setup

### 1. Clone & Configure Environment
```bash
git clone https://github.com/gimigkk/Helmis.git
cd Helmis
cp .env.example .env
nano .env
```

Configure `.env` with:
- `OWNER_PHONE` and `OWNER_NAME` (E.164 formatted, e.g. `6281234567890`)
- `PARTNER_PHONE` and `PARTNER_NAME` (Optional: leave blank for Solo Mode)
- `BOT_PHONE`
- `GEMINI_KEY_1`, `GEMINI_KEY_2`, etc.
- `WAHA_API_KEY` and `WAHA_DASHBOARD_PASSWORD`

### 2. Start Services with Docker Compose
```bash
docker compose up -d --build
```

### 3. Connect WhatsApp
1. Open the WAHA dashboard in your browser: `http://<your-server-ip>:3005`.
2. Authenticate with `admin` and your `WAHA_DASHBOARD_PASSWORD`.
3. Scan the QR code using WhatsApp on your bot phone number.
4. Once the session status is `WORKING`, Helmis is live!

---

## Testing & Quality Assurance

Run the comprehensive test suite (21 modules, 179 test cases):

```bash
cd helmis-agent
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest
```

```text
============================= 179 passed in 3.32s ==============================
```

---

## Documentation Index

| Guide | Description |
|---|---|
| [Master Index](docs/INDEX.md) | Architecture map, roadmap, and complete module catalog. |
| [System Architecture](docs/ARCHITECTURE.md) | High-level topology, domain packages, container network, and lifecycle. |
| [Agent Core & ReAct Loop](docs/AGENT_CORE.md) | ReAct loop, Gemini cascade, mid-turn steering, and transparent footnote badges. |
| [Communication & Routing](docs/COMMUNICATION_AND_ROUTING.md) | WAHA integration, payload parser, queue debouncing, and group chat dynamics. |
| [Memory & Storage](docs/MEMORY_AND_STORAGE.md) | Atomic JSON store, vector semantic memory, Document Vault, and Google Workspace reader. |
| [Proactive Engine](docs/PROACTIVE_ENGINE.md) | Scheduler cron triggers, lead-time buffering, and nag loops. |
| [Configuration & Skills](docs/CONFIGURATION_AND_SKILLS.md) | Single Source of Truth prompt, skill playbooks, and Solo Mode guide. |
| [Deployment & Operations](docs/DEPLOYMENT_AND_OPERATIONS.md) | VPS deployment, zero-downtime updates, healthchecks, and backups. |
| [Development & Testing](docs/DEVELOPMENT_AND_TESTING.md) | Test suites, mock strategies, fixtures, and code standards. |
| [Scenarios & Playbooks](docs/SCENARIOS_AND_PLAYBOOKS.md) | Real-world operational scenarios, error handling, and multimodal workflows. |

---

## License

MIT License. See [LICENSE](LICENSE) for details.
