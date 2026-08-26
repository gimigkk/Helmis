# Configuration & Skill Playbooks

This document details the configuration system of Helmis: the **Single Source of Truth System Prompt**, **Skill Playbooks**, and **Environment Variables**.

---

## 1. Single Source of Truth System Prompt (`config/system-prompt.md`)

Helmis uses `config/system-prompt.md` as its **100% Single Source of Truth** for identity, persona, group chat non-intervention rules, and formatting standards.

- **Zero In-Code Duplication**: No operational prompt strings are hardcoded in Python code.
- **Dynamic Context Assembly**: At runtime, `src/agent/loop.py` composes the full instruction by cleanly combining:
  ```python
  full_system_instruction = f"{system_prompt}\n\n{skills_context}\n\n{memory_context}\n\n{semantic_context}".strip()
  ```
- **Hot-Reloadable**: Changes to `config/system-prompt.md` take effect immediately on container reload without recompiling.

---

## 2. Skill Playbooks (`config/skills/`)

Skills provide specialized domain knowledge and procedures. Each skill is defined as a `SKILL.md` markdown file in its own subdirectory:

| Skill Directory | Purpose | Key Operations |
|---|---|---|
| `skills/task-manager/` | Task lifecycle & lead-time inference | Creating tasks, setting lead buffers, completion, rescheduling |
| `skills/vault-manager/` | Document vault & file storage | Saving files, original filename preservation, search, dispatch |
| `skills/document-reader/` | Multimodal document inspection | Extracting text, digital PDF parsing, invoice data extraction |
| `skills/shared-notes/` | Categorized shared notebooks | Creating, updating, appending, and searching shared notes |
| `skills/proactive-check/` | Scheduler tick evaluations | Evaluating due reminders, lead-time thresholds, overdue nudges |
| `skills/reminder-engine/` | Time-based reminders | Setting one-shot and recurring reminders in WIB timezone |
| `skills/people-directory/` | Contacts & relationship directory | Tracking roles, phone numbers, emails, notes for actors |
| `skills/schedule-manager/` | Calendar events & class routines | Daily agendas, weekly schedules, class timetables in unified cards |

---

## 3. Environment Variables (`.env`)

| Variable | Required | Default | Description |
|---|---|---|---|
| `GILANG_PHONE` | Yes | - | E.164 phone number for Gilang (e.g. `6281234567890`) |
| `BUNGA_PHONE` | Yes | - | E.164 phone number for Bunga (e.g. `6289876543210`) |
| `BOT_PHONE` | Yes | - | E.164 phone number for the Helmis bot WhatsApp account |
| `TRIO_GROUP_JID` | No | - | JID for the shared couple group chat (e.g. `120363...@g.us`) |
| `GEMINI_KEY_1` | Yes | - | Primary Google Gemini API key |
| `GEMINI_KEY_2..N` | No | - | Secondary API keys for round-robin rotation & fallback |
| `WAHA_BASE_URL` | No | `http://waha:3000` | Internal WAHA REST API endpoint |
| `WAHA_API_KEY` | Yes | - | Secret token securing WAHA API calls |
| `WAHA_DASHBOARD_PASSWORD` | Yes | - | Password for WAHA web dashboard |
| `AGENT_WEBHOOK_PORT` | No | `8644` | Internal port for Starlette webhook listener |
| `MCP_WAHA_PORT` | No | `8765` | Internal port for FastMCP SSE server |
| `TZ` | No | `Asia/Jakarta` | Local timezone (defaults to WIB / UTC+7) |
