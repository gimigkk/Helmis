# Helmis Documentation Hub

Welcome to the comprehensive technical documentation for **Helmis** — the autonomous, multi-step personal AI secretary for Gilang and Bunga, powered by Google Gemini and delivered via WhatsApp.

This documentation is designed to provide complete transparency, deep architectural clarity, and actionable operational playbooks so that any developer, maintainer, or systems operator can understand, extend, debug, and maintain the system indefinitely.

---

## Documentation Navigation

```
Helmis/
├── README.md                                  # High-level overview & Quickstart guide
└── docs/
    ├── INDEX.md                               # You are here: Master Documentation Index
    ├── ARCHITECTURE.md                        # System topology, container orchestration & turn lifecycle
    ├── AGENT_CORE.md                          # Multi-step ReAct loop, model cascade, tools & guardrails
    ├── MEMORY_AND_STORAGE.md                  # JSON store, vector embeddings & episodic fact extractor
    ├── COMMUNICATION_AND_ROUTING.md           # WAHA gateway, webhooks, per-chat queues & auth security
    ├── PROACTIVE_ENGINE.md                    # Supercronic scheduler, reminder evaluator & cron ticks
    ├── CONFIGURATION_AND_SKILLS.md            # Environment vars, system prompt & skills playbooks
    ├── DEVELOPMENT_AND_TESTING.md             # Local setup, pytest suite, tracer logging & extensibility
    └── DEPLOYMENT_AND_OPERATIONS.md           # Docker Compose, VPS provisioning, backups & troubleshooting
```

---

## Document Summaries

### 1. [System Architecture & Lifecycle](file:///home/gimigkk/Desktop/Projects/Helmis/docs/ARCHITECTURE.md)
Detailed architectural overview of Helmis:
- System topology: WAHA WhatsApp Bridge, Helmis Agent Brain, Google Gemini API, and Cron Scheduler.
- Network topology, Docker bridge network (`helmis-net`), container dependency orchestration.
- The 6-stage message processing pipeline: Inbound Webhook -> Per-Chat Debounce Queue -> Multimodal Ingestion/Audio Transcription -> ReAct Agent Loop & Tool Dispatch -> State Fidelity Guardrails -> Dispatch & Background Episodic Fact Extraction.
- Complete Mermaid architecture, component, and sequence diagrams.

### 2. [Autonomous Agent Core & ReAct Engine](file:///home/gimigkk/Desktop/Projects/Helmis/docs/AGENT_CORE.md)
The intelligence layer of Helmis:
- **Dynamic Model Cascade**: Dynamic query of Google Gemini models with intelligent speed/capability prioritization (`Flash-Lite` -> `Flash` -> `Gemma` -> `Pro`).
- **Multi-Key Quota Rotation**: Round-robin key rotation across independent Google accounts to bypass rate limits (429/404 handling).
- **Tool Calling System**: Detailed specifications, JSON schemas, parameters, and return types for all 12 agentic tools.
- **Multi-Turn Context Builder**: Chronological history construction, speaker attribution (`[Gilang]`, `[Bunga]`), and native multimodal media injection.
- **State Fidelity Guardrail**: Output verification that prevents hallucinations when items are not found or operations fail.
- **Voice Note & Document OCR**: 2-phase pipeline featuring dedicated zero-hallucination speech transcription and multimodal document analysis.

### 3. [Memory Architecture & Semantic Vector Store](file:///home/gimigkk/Desktop/Projects/Helmis/docs/MEMORY_AND_STORAGE.md)
Data persistence and long-term intelligence:
- **Unified Brain Architecture**: Cross-user contextual awareness with privacy discretion.
- **Structured Storage (`helmis_memory.json`)**: Thread-safe atomic file writes (`os.fsync`), schema definitions for tasks, people directory, shared notes, and activity logs.
- **Semantic Vector Memory (`semantic_memories.json`)**: 3072-dimensional vector embeddings via `gemini-embedding-001`, cosine similarity search, and score thresholding.
- **Background Episodic Memory Extractor**: Passive extraction of personal facts, habits, and preferences after each turn without adding latency to the conversation.
- **Task Lifecycle**: Full state transitions (`pending` -> `reminded` -> `completed` / `deleted`).

### 4. [Communication, Webhooks & Per-Chat Queues](file:///home/gimigkk/Desktop/Projects/Helmis/docs/COMMUNICATION_AND_ROUTING.md)
WhatsApp ingestion, routing, and transport:
- **WAHA REST Client (`WahaClient`)**: Async HTTP client for `/api/sendText`, `/api/sendFile`, `/api/messages`, and typing indicators.
- **Webhook Receiver**: Starlette HTTP server running in a dedicated thread on port 8644.
- **Multi-Filter Authorization**: Strict sender whitelisting (`GILANG_PHONE`, `BUNGA_PHONE`, WhatsApp LIDs, notifyName), dropping unauthorized users silently.
- **Group Chat Discretion & Banter Filter**: Heuristic mention detection (`@helmis`, `mis `) to avoid interrupting human conversation in group chats.
- **Per-Chat Debounce Queue**: Independent async workers per chat ID with a 1.0-second burst debounce window that coalesces rapid multi-message bursts into a single prompt.

### 5. [Proactive Reminder & Scheduler Subsystem](file:///home/gimigkk/Desktop/Projects/Helmis/docs/PROACTIVE_ENGINE.md)
Proactive intelligence and cron triggers:
- **Scheduler Container**: Lightweight Alpine Linux container running Supercronic.
- **Cron Trigger**: `trigger.sh` dispatching periodic ticks to `/webhooks/scheduler`.
- **Proactive Evaluator (`handle_proactive_scheduler_tick`)**: Inspects pending tasks against live Jakarta time (`WIB`), identifies upcoming deadlines, prompts Gemini for structured reminder output, delivers WhatsApp messages, and flags tasks as reminded.

### 6. [Configuration, Prompts & Skills System](file:///home/gimigkk/Desktop/Projects/Helmis/docs/CONFIGURATION_AND_SKILLS.md)
Behavioral tuning and capability playbooks:
- **Environment Variables**: Comprehensive reference table with types, default values, and security best practices.
- **System Prompt Architecture**: Identity, tone, WhatsApp markdown rules (`*bold*`, `_italic_`), ZERO EMOJI mandate, and Indonesian temporal greetings rules.
- **Dynamic Skills Architecture**: Automatic discovery and injection of `SKILL.md` playbooks from `config/skills/`.
- **Skill Playbooks**: Detailed breakdown of `people-directory`, `schedule-manager`, `task-manager`, `reminder-engine`, `document-reader`, `shared-notes`, and `proactive-check`.

### 7. [Development, Testing & Observability](file:///home/gimigkk/Desktop/Projects/Helmis/docs/DEVELOPMENT_AND_TESTING.md)
Developer setup, test suite, and step tracing:
- **Local Environment**: Python 3.12+ virtualenv setup and package management via `pyproject.toml`.
- **Test Suite**: 32 unit and integration tests covering agent loops, HTTP clients, deduplication, memory, queues, and vector math.
- **Structured Step Tracer (`AgentTurnTracer`)**: ANSI-formatted real-time console tracing and persistent JSON Lines audit logging (`agent_traces.jsonl`).
- **Extensibility Guide**: Step-by-step instructions for adding new tools, skills, and model providers.

### 8. [Deployment, Operations & Troubleshooting](file:///home/gimigkk/Desktop/Projects/Helmis/docs/DEPLOYMENT_AND_OPERATIONS.md)
Production operations and disaster recovery:
- **Docker Compose Topology**: Container configurations, persistent volume mounts, and health checks.
- **Deployment Runbook**: Setup script (`scripts/setup.sh`) and terminal ASCII QR code authentication (`scripts/auth.sh`).
- **Backup & Disaster Recovery**: Automated snapshots via `scripts/backup.sh` and restoration procedures.
- **Troubleshooting Matrix**: Root cause analysis and step-by-step remediation for WhatsApp disconnections, Gemini 429 rate limits, and audio decoding issues.

### 9. [Scenarios & Thinking-Out-Loud Playbook](file:///home/gimigkk/Desktop/Projects/Helmis/docs/SCENARIOS_AND_PLAYBOOKS.md)
Comprehensive behavioral catalog and decision matrix:
- **50+ Real-World Scenarios**: Full coverage of cross-party messaging, finance tracking, split bills, travel itineraries, medication routines, and voice notes.
- **Thinking-Out-Loud Decision Matrix**: Exact criteria for when to send intermediate status updates vs silent execution vs cross-party messages.
- **The 6 Universal Architectural Primitives**: End-to-end mapping from primitives to real-world user workflows.

---

## Role-Based Reading Recommendations

| Your Role | Recommended Reading Order |
|---|---|
| **Software Architect** | 1. [ARCHITECTURE.md](file:///home/gimigkk/Desktop/Projects/Helmis/docs/ARCHITECTURE.md)<br>2. [AGENT_CORE.md](file:///home/gimigkk/Desktop/Projects/Helmis/docs/AGENT_CORE.md)<br>3. [MEMORY_AND_STORAGE.md](file:///home/gimigkk/Desktop/Projects/Helmis/docs/MEMORY_AND_STORAGE.md) |
| **Backend / AI Engineer** | 1. [AGENT_CORE.md](file:///home/gimigkk/Desktop/Projects/Helmis/docs/AGENT_CORE.md)<br>2. [COMMUNICATION_AND_ROUTING.md](file:///home/gimigkk/Desktop/Projects/Helmis/docs/COMMUNICATION_AND_ROUTING.md)<br>3. [DEVELOPMENT_AND_TESTING.md](file:///home/gimigkk/Desktop/Projects/Helmis/docs/DEVELOPMENT_AND_TESTING.md) |
| **DevOps / Sysadmin** | 1. [DEPLOYMENT_AND_OPERATIONS.md](file:///home/gimigkk/Desktop/Projects/Helmis/docs/DEPLOYMENT_AND_OPERATIONS.md)<br>2. [PROACTIVE_ENGINE.md](file:///home/gimigkk/Desktop/Projects/Helmis/docs/PROACTIVE_ENGINE.md)<br>3. [CONFIGURATION_AND_SKILLS.md](file:///home/gimigkk/Desktop/Projects/Helmis/docs/CONFIGURATION_AND_SKILLS.md) |
| **Prompt / AI Ops Engineer** | 1. [CONFIGURATION_AND_SKILLS.md](file:///home/gimigkk/Desktop/Projects/Helmis/docs/CONFIGURATION_AND_SKILLS.md)<br>2. [AGENT_CORE.md](file:///home/gimigkk/Desktop/Projects/Helmis/docs/AGENT_CORE.md)<br>3. [MEMORY_AND_STORAGE.md](file:///home/gimigkk/Desktop/Projects/Helmis/docs/MEMORY_AND_STORAGE.md) |

---

## Core System Invariants

1. **Zero Emojis**: Helmis strictly uses clean, professional text formatting. Emojis are never generated in chat outputs or reminders.
2. **State Fidelity**: The agent must never report an action as successful unless the underlying tool confirms `status: "success"`.
3. **Temporal Precision**: All times, deadlines, and greetings must strictly match Jakarta Local Time (`WIB`, UTC+7).
4. **Sender Authorization**: Unrecognized senders are silently dropped to ensure zero unauthorized exposure of personal data.
5. **Deduplication & Debouncing**: Inbound message bursts are combined within a 1.0-second window, and duplicate webhook payloads are rejected.
