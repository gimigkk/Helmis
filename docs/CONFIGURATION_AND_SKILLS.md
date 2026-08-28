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
| `skills/pdf-toolkit/` | On-demand PDF & document toolkit | Merging (zero-margin/A4), splitting, page-to-image preview, PDF ⇄ DOCX, compression |
| `skills/shared-notes/` | Categorized shared notebooks | Creating, updating, appending, and searching shared notes |
| `skills/proactive-check/` | Scheduler tick evaluations | Evaluating due reminders, lead-time thresholds, overdue nudges |
| `skills/reminder-engine/` | Time-based reminders | Setting one-shot and recurring reminders in WIB timezone |
| `skills/people-directory/` | Contacts & relationship directory | Tracking roles, phone numbers, emails, notes for actors |
| `skills/schedule-manager/` | Calendar events & class routines | Daily agendas, weekly schedules, class timetables in unified cards |

### On-Demand Progressive Skill Loading (`load_skill`)
To prevent prompt bloat and preserve sub-second response times, specialized toolkits (such as `pdf-toolkit`) are segregated into an **On-Demand Skills Index** in the base system prompt (~30 tokens). When Helmis encounters a complex domain task, it invokes `load_skill(name="<skill-name>")` to dynamically load the complete operational playbook into working memory.

---

## 3. Environment Variables (`.env`)

| Variable | Required | Default | Description |
|---|---|---|---|
| `OWNER_PHONE` / `GILANG_PHONE` | Yes | - | E.164 phone number for primary owner (e.g. `6281234567890`) |
| `OWNER_NAME` | No | `Gilang` | Name of the primary owner (e.g. `Alex`) |
| `PARTNER_PHONE` / `BUNGA_PHONE` | No | - | E.164 phone number for partner (for Duo mode; leave empty if Solo) |
| `PARTNER_NAME` | No | `Bunga` | Name of partner (for Duo mode; leave empty if Solo) |
| `BOT_PHONE` | Yes | - | E.164 phone number for the Helmis bot WhatsApp account |
| `TRIO_GROUP_JID` | No | - | JID for shared group chat (optional for Duo mode) |
| `GEMINI_KEY_1` | Yes | - | Primary Google Gemini API key |
| `GEMINI_KEY_2..N` | No | - | Secondary API keys for round-robin rotation & fallback |
| `WAHA_BASE_URL` | No | `http://waha:3000` | Internal WAHA REST API endpoint |
| `WAHA_API_KEY` | Yes | - | Secret token securing WAHA API calls |
| `WAHA_DASHBOARD_PASSWORD` | Yes | - | Password for WAHA web dashboard |
| `AGENT_WEBHOOK_PORT` | No | `8644` | Internal port for Starlette webhook listener |
| `MCP_WAHA_PORT` | No | `8765` | Internal port for FastMCP SSE server |
| `TZ` | No | `Asia/Jakarta` | Local timezone (defaults to WIB / UTC+7) |

---

## 4. Solo / Single-User Mode Setup (Clone & Upstream Sync Guide)

If you clone Helmis to run as a **personal solo AI executive secretary** (for 1 user rather than a duo/couple), follow this 2-minute zero-conflict setup:

### Step 1: Configure `.env`
Copy the environment template and configure your WhatsApp number and API keys:
```bash
cp .env.example .env
```
In `.env`, set:
```ini
OWNER_NAME="YourName"
OWNER_PHONE="628123456789"    # Your WhatsApp phone number in E.164 format
BOT_PHONE="628987654321"      # The WhatsApp number used by your WAHA bot
GEMINI_KEY_1="AIzaSy..."      # Your Google Gemini API key
```
*(Leave `PARTNER_NAME`, `PARTNER_PHONE` and `TRIO_GROUP_JID` empty or commented out).*

---

### Step 2: Set Up Local System Prompt (`system-prompt.local.md`)
To customize your assistant persona without causing git merge conflicts when pulling updates:
```bash
cp config/system-prompt.solo.example.md config/system-prompt.local.md
```
Edit `config/system-prompt.local.md` to specify your preferred assistant name, tasks, and persona.

> [!NOTE]
> The engine automatically prioritizes `config/system-prompt.local.md` over `config/system-prompt.md`. Because `*.local.md` is in `.gitignore`, you can run `git pull origin main` anytime without merge conflicts!

---

### Step 3: Launch Services
```bash
docker compose build
docker compose up -d
```
Open `http://localhost:3005` (or your VPS IP on port 3005) to scan the WhatsApp QR code via WAHA. Your personal executive secretary is now live!
