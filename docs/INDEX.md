# Documentation Index

Welcome to the **Helmis Technical Documentation**. This directory provides complete architectural, operational, and development documentation for the Helmis self-hosted autonomous AI executive secretary.

---

## Documentation Roadmap

```
docs/
├── INDEX.md                         # Master Documentation Hub (You are here)
├── ARCHITECTURE.md                  # System Topology, Domain Packages, & Container Network
├── AGENT_CORE.md                    # Autonomous ReAct Loop, Multi-Key Cascade, Steering & State Guardrails
├── COMMUNICATION_AND_ROUTING.md     # WAHA Bridge, Debounce Queue, Mid-Turn Media & Routing
├── MEMORY_AND_STORAGE.md            # Atomic JSON Store, Vector Semantic Memory, Vault & Temp Sandbox
├── PROACTIVE_ENGINE.md              # Scheduler Cron Triggers, Lead-Time Buffering, & Nag Loops
├── CONFIGURATION_AND_SKILLS.md      # Single Source of Truth Prompt & Skill Playbooks
├── DEPLOYMENT_AND_OPERATIONS.md     # VPS Deployment, Healthchecks, Zero-Downtime, & Backups
├── DEVELOPMENT_AND_TESTING.md       # Pytest Suites (41 Modules, 466 Tests), Fixtures, & Contribution Guide
└── SCENARIOS_AND_PLAYBOOKS.md       # Operational Real-World Scenarios & Failure Playbooks
```

## Rebuild Tracking

- [RELIABILITY_REBUILD_PLAN.md](RELIABILITY_REBUILD_PLAN.md) is the canonical reliability rebuild plan and decision record.
- [IMPLEMENTATION_TRACKING.md](IMPLEMENTATION_TRACKING.md) is the single implementation status tracker.
- [production-evidence/README.md](production-evidence/README.md) contains sanitized production evidence and regression cases.

---

## Core System Highlights

| Domain | Key Capabilities | Primary Reference |
|---|---|---|
| **Architecture** | Pure domain packaging (`src/agent`, `src/memory`, `src/whatsapp`, `src/tools`), Docker bridge network, FastMCP SSE server | [ARCHITECTURE.md](ARCHITECTURE.md) |
| **Agent Core** | Autonomous ReAct loop, hedged multi-model cascade (2-model race + failure cooldowns), compact query mode (domain-scoped tools/skills), chat fast path, mid-turn binary mailbox steering, two-step anti-hallucination guardrail, contextual footnote chips | [AGENT_CORE.md](AGENT_CORE.md) |
| **Web & Google Reader** | Zero-dependency multi-tab Published Google Sheets parser (`pubhtml`), Docs, Slides, Drive & Web scraper with SSRF protection | [AGENT_CORE.md](AGENT_CORE.md) |
| **Communication** | WAHA GOWS engine, dynamic media endpoint routing (photo bubbles vs uncompressed documents), 1.0s burst debouncing, multimodal inlineData | [COMMUNICATION_AND_ROUTING.md](COMMUNICATION_AND_ROUTING.md) |
| **Storage & Memory** | SQLite/WAL task repository (stable IDs, versions, categories, recurrence) + atomic JSON sidecar (people/notes/activity with env fallback), 3072-dim Gemini embeddings, categorized Document Vault, Temp Sandbox Workspace | [MEMORY_AND_STORAGE.md](MEMORY_AND_STORAGE.md) |
| **Proactive Engine** | 1-minute cron evaluations, polymorphic job execution (`ToolJobExecutor` & `AgentLoopJobExecutor`), near-horizon exact-second timers, policy-driven nag loops, weekly recurrence with downtime advance, routine-category filtering | [PROACTIVE_ENGINE.md](PROACTIVE_ENGINE.md) |
| **Configuration** | 100% Single Source of Truth `config/system-prompt.md`, modular skills in `config/skills/`, default assignee separation & hierarchical WhatsApp formatting | [CONFIGURATION_AND_SKILLS.md](CONFIGURATION_AND_SKILLS.md) |
| **Operations** | Zero-downtime container updates, auto-restarting services, automated backup scripts | [DEPLOYMENT_AND_OPERATIONS.md](DEPLOYMENT_AND_OPERATIONS.md) |
| **Testing** | 21 test suites covering 179 test cases with comprehensive mocking of external APIs | [DEVELOPMENT_AND_TESTING.md](DEVELOPMENT_AND_TESTING.md) |
