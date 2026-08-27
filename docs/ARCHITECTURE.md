# System Architecture & Component Design

This document details the architectural design of **Helmis**, covering high-level system topology, domain modularity, container orchestration, network routing, and the end-to-end turn execution lifecycle.

---

## 1. System Topology Overview

Helmis operates 24/7 on a private server (VPS). It bridges WhatsApp communication via WAHA with Google Gemini LLMs, atomic local storage, and a vector semantic memory store.

```mermaid
graph TD
    subgraph "External WhatsApp Network"
        UserG["Gilang (WhatsApp DM)"]
        UserB["Bunga (WhatsApp DM)"]
        GroupT["Trio Group Chat (Gilang, Bunga, Helmis)"]
    end

    subgraph "Docker Host (helmis-net)"
        subgraph "WAHA Service (Port 3000)"
            WAHA["WAHA Container (GOWS Engine)<br/>WhatsApp Web WebSocket Bridge"]
            WAHADash["WAHA Web Dashboard / QR (Port 3005)"]
        end

        subgraph "Helmis Agent Container (Ports 8644 & 8765)"
            WH["Starlette Webhook Server<br/>(Port 8644: /webhooks/waha)"]
            AuthF["Security & Auth Filter<br/>(Whitelist & Banter Gate)"]
            QueueMgr["ChatQueueManager<br/>(1.0s Burst Debounce & Per-Chat Workers)"]
            ReActLoop["ReAct Agentic Loop<br/>(Multi-Step Tool Engine & Steering)"]
            ToolDisp["Tool Dispatcher & Registry<br/>(Function Declarations & Handlers)"]
            Guardrail["State Fidelity Guardrail<br/>(Fidelity Verification)"]
            Tracer["AgentTurnTracer<br/>(Structured Terminal & JSONL Trace)"]
            MCP["MCPServer (FastMCP)<br/>(Port 8765: /sse)"]
        end

        subgraph "Scheduler Container"
            Cron["Supercronic Daemon<br/>(Alpine Linux)"]
            Trigger["trigger.sh<br/>(1-Minute Periodic HTTP POST)"]
        end

        subgraph "Local Persistent Storage (./data)"
            JSONStore[("helmis_memory.json<br/>Tasks, Scheduled Jobs, Directory, Notes")]
            VaultStore[("vault/ & file_catalog.json<br/>PDFs, Binary Files & Catalog")]
            VecStore[("semantic_memories.json<br/>Episodic Vector Embeddings")]
            TraceLog[("agent_traces.jsonl<br/>Execution Logs")]
        end
    end

    subgraph "External Cloud Services (Google AI & Search)"
        GeminiAPI["Google Gemini API<br/>Models: Pro, Flash, 2.0 Flash<br/>Embeddings: text-embedding-004<br/>Key Pool: GEMINI_KEY_1..N"]
        SearchAPI["DuckDuckGo / Tavily Search"]
    end

    UserG <-->|WhatsApp Protocol| WAHA
    UserB <-->|WhatsApp Protocol| WAHA
    GroupT <-->|WhatsApp Protocol| WAHA

    WAHA -->|HTTP POST Webhook| WH
    Cron -->|Runs every 1 min| Trigger
    Trigger -->|HTTP POST /webhooks/waha| WH

    WH --> AuthF
    AuthF --> QueueMgr
    QueueMgr --> ReActLoop
    ReActLoop <-->|Multi-Key LLM Calls| GeminiAPI
    ReActLoop <--> ToolDisp
    ToolDisp <--> JSONStore
    ToolDisp <--> VaultStore
    ToolDisp <--> VecStore
    ToolDisp <--> SearchAPI
    ToolDisp -->|Outbound WhatsApp| WAHA
    ReActLoop --> Guardrail
    Guardrail -->|Verified Reply| WAHA
    ReActLoop --> Tracer
    Tracer --> TraceLog
```

---

## 2. Domain-Driven Package Layout

The agent codebase is organized into 4 distinct domain packages under `helmis-agent/src/`:

```
helmis-agent/src/
├── agent/                  # Brain, ReAct Loop & Cascade Orchestration
│   ├── cascade.py          # Gemini model fallback cascade & multi-key rotation
│   ├── guardrails.py       # State fidelity verification & footnote chips
│   ├── loop.py             # Autonomous multi-step ReAct agent loop & mailbox steering
│   ├── proactive.py        # Proactive reminder evaluator, 2-stage lead buffer & nag loops
│   ├── tracer.py           # Structured execution tracer & ANSI debugging
│   └── __init__.py
├── memory/                 # Storage, Episodic Memory & Vault
│   ├── semantic.py         # Vector embeddings & semantic memory search
│   ├── store.py            # JSON-backed tasks, people, schedules & notes
│   ├── vault.py            # Document vault, catalog, categorization & PDF extractor
│   └── __init__.py
├── whatsapp/               # WhatsApp / WAHA Integration
│   ├── client.py           # HTTP client with retry & rate limiting
│   ├── history.py          # Message deduplication & multi-turn history builder
│   ├── models.py           # WAHA & WhatsApp Pydantic models
│   ├── parser.py           # Payload, quoted message & identity resolution
│   ├── processor.py        # Batched turn processor, watchdog & bubble splitter
│   ├── queue.py            # Per-chat FIFO queue & 1.0s debouncer
│   ├── transcribe.py       # Audio & voice note transcription
│   ├── webhook.py          # Starlette HTTP controller (< 120 LOC)
│   └── __init__.py
├── tools/                  # Function Tool Declarations & Handlers
│   ├── contacts.py         # Contact lookup & storage tool
│   ├── files.py            # Document vault tool handlers
│   ├── mcp_export.py       # FastMCP SSE tool registration
│   ├── memory.py           # Semantic memory tool handlers
│   ├── notes.py            # Quick notes tool handlers
│   ├── registry.py         # Tool registry decorator & dispatcher
│   ├── schema.py           # Gemini Tool function declarations
│   ├── search.py           # Live DuckDuckGo / Tavily web search engine
│   ├── tasks.py            # Task & reminder tool handlers
│   ├── web.py              # Web search tool handler
│   ├── whatsapp.py         # WhatsApp message sending tool handlers
│   └── __init__.py
├── server.py               # Main runtime entry point (FastMCP SSE & Webhook runner)
└── __init__.py             # Package exports
```

---

## 3. Container Network & Deployment Topology

Orchestrated via `docker-compose.yml` on a shared bridge network (`helmis-net`):

### Services & Port Mappings

| Container Name | Base Image / Context | Internal Port | Exposed Port | Purpose |
|---|---|---|---|---|
| `helmis-waha` | `devlikeapro/waha:latest` | `3000` | `3005:3000` | WhatsApp Web WebSocket bridge (GOWS engine) + Dashboard |
| `helmis-agent` | `./helmis-agent` (Python 3.12-slim) | `8644`, `8765` | `8644` (Internal), `8765` (Internal) | Core AI ReAct Brain, Webhooks, Storage, FastMCP SSE server |
| `helmis-scheduler` | `./scheduler` (Alpine Linux) | N/A | N/A | Crontab runner triggering proactive check evaluations |

### Persistent Volume Layout

```
Host Filesystem
├── ./data/                                  <== Mounted into /app/data:z
│   ├── helmis_memory.json                   # Structured persistent state (tasks, notes, contacts)
│   ├── file_catalog.json                    # Metadata catalog for Document Vault
│   ├── vault/                               # Binary PDFs, photos, scans, receipts & workspaces
│   ├── semantic_memories.json               # Episodic vector embeddings & facts
│   └── agent_traces.jsonl                   # Step-by-step turn execution traces
│
├── ./config/                                <== Mounted into /app/config:ro,z
│   ├── system-prompt.md                     # 100% Single Source of Truth System Prompt
│   └── skills/                              # Specialized secretary playbooks (Markdown)
│
└── waha-sessions (Docker Volume)            <== Mounted into /app/.sessions
    └── ...                                  # WhatsApp Web token session files
```

---

## 4. End-to-End Turn Execution Lifecycle

```mermaid
sequenceDiagram
    autonumber
    actor User as Gilang / Bunga
    participant WAHA as WAHA (Bridge)
    participant WH as Webhook Receiver (/webhooks/waha)
    participant Queue as ChatQueueManager (Debouncer)
    participant Agent as ReAct Agent Loop
    participant Gemini as Google Gemini API
    participant Mem as Local Storage (JSON & Vector)

    User->>WAHA: Sends WhatsApp message (Text / Image / Voice Note)
    WAHA->>WH: HTTP POST /webhooks/waha (JSON payload)
    
    Note over WH: Stage 1: Ingestion & Auth Validation
    WH->>WH: Validate Sender Phone / LID against Whitelist
    WH->>WH: Deduplicate message ID (60s cache)
    
    WH->>Queue: Dispatch IncomingMessageEvent
    Note over Queue: Stage 2: 1.0s Burst Debounce Window
    Queue->>Queue: Coalesce rapid consecutive messages into single turn
    
    Queue->>WAHA: Send 'startTyping' indicator
    Queue->>Agent: Execute Turn (batched messages)
    
    Note over Agent: Stage 3: Multimodal Preprocessing & Context Loading
    Agent->>Mem: Query Semantic Memory & Active Tasks
    Agent->>WAHA: Fetch recent chat history
    
    Note over Agent: Stage 4: ReAct Tool Execution & Steering
    loop Up to 12 Iterations
        Agent->>Gemini: Generate turn step (System Prompt + History + Tools)
        Gemini-->>Agent: Returns Tool Call or Final Response
        alt Tool Call Requested
            Agent->>Mem: Execute tool (Store / Vault / Search / WhatsApp)
            Mem-->>Agent: Tool outcome returned
            Agent->>Queue: Check Mailbox for Mid-Turn User Steering
        end
    end
    
    Note over Agent: Stage 5: Guardrails & Footnotes
    Agent->>Agent: State Fidelity Check & ↳ Footnote Generation
    
    Note over Agent: Stage 6: Dispatch & Background Fact Extraction
    Agent->>WAHA: Send response (Split on '---' into bubbles)
    Agent-->>Gemini: Background fact extraction -> Update semantic memory
```
