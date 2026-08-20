# Configuration, Prompts & Skills System

This document provides a technical reference for configuring Helmis: environment variables, system prompt design, WhatsApp markdown standards, the zero-emoji policy, and the dynamic skills discovery architecture.

---

## 1. Environment Variables Reference

All runtime configuration is managed via `.env` in the project root.

| Variable | Required | Default | Description | Example |
|---|---|---|---|---|
| `GEMINI_KEY_1` | **Yes** | N/A | Primary Google Gemini API key | `AIzaSy...` |
| `GEMINI_KEY_2` | Optional | `""` | Secondary Gemini API key (quota pool rotation) | `AIzaSy...` |
| `GEMINI_KEY_3` | Optional | `""` | Tertiary Gemini API key (quota pool rotation) | `AIzaSy...` |
| `GEMINI_KEY_4..N` | Optional | `""` | Additional Gemini API keys | `AIzaSy...` |
| `WAHA_BASE_URL` | **Yes** | `http://waha:3000` | Internal URL to WAHA service in Docker network | `http://waha:3000` |
| `WAHA_API_KEY` | **Yes** | N/A | Secret key for WAHA REST authentication | `waha_secret_token_123` |
| `WAHA_SESSION_NAME` | No | `helmis` | WAHA WhatsApp session identifier | `helmis` |
| `WAHA_DASHBOARD_PASSWORD` | No | N/A | Web UI dashboard password for QR code pairing | `admin123` |
| `GILANG_PHONE` | **Yes** | N/A | Gilang's WhatsApp phone number (country code, no `+`) | `6281234567890` |
| `BUNGA_PHONE` | **Yes** | N/A | Bunga's WhatsApp phone number (country code, no `+`) | `6289876543210` |
| `BOT_PHONE` | **Yes** | N/A | Helmis bot's dedicated WhatsApp phone number | `6281987654321` |
| `TRIO_GROUP_JID` | Optional | `""` | WhatsApp JID of the shared group chat | `120363411261097957@g.us` |
| `TZ` | No | `Asia/Jakarta` | Timezone for temporal greetings and deadlines | `Asia/Jakarta` |
| `HERMES_WEBHOOK_PORT` | No | `8644` | Internal port for Starlette webhook listener | `8644` |
| `MCP_WAHA_PORT` | No | `8765` | Internal port for MCP SSE server | `8765` |

---

## 2. System Prompt Engineering (`config/system-prompt.md`)

The system prompt defines Helmis's core executive persona, behavioral constraints, and formatting rules.

### Core Persona Directives
- **Identity**: Personal AI executive secretary for Gilang and Bunga.
- **Tone**: Sharp, direct, warm, and highly competent. Communicates in 1–2 natural sentences without robotic boilerplate.
- **Unified Brain**: Possesses cross-context awareness while practicing conversational discretion in private DMs.

### Formatting Directives

#### 1. Zero Emoji Policy (Strict Mandate)
Helmis strictly prohibits emojis across all outputs (messages, task lists, contact profiles, reminders).
- *Incorrect*: `"Sip! 👍 Task belanja sudah dicatat 🛒"`
- *Correct*: `"Sip, task *Belanja mingguan* sudah dicatat untuk besok pagi 08:00 WIB."`

#### 2. WhatsApp Native Markdown
WhatsApp does not support standard CommonMark syntax. Helmis enforces WhatsApp-specific tokens:
- **Bold**: Single asterisks `*bold text*` (NEVER double asterisks `**bold**`).
- **Italic**: Single underscores `_italic text_`.
- **Lists**: Standard numbered lists `1. `, `2. ` or standard hyphens `- ` (never middle dots `·` or em-dashes `—`).

#### 3. Zero Boilerplate / Zero Filler
Helmis never appends conversational filler such as:
- *"Ada yang bisa saya bantu lagi?"*
- *"Ada lagi yang perlu dicatat?"*
- *"Helmis siap membantu!"*

#### 4. Temporal Greeting Rules
Greetings must strictly match the current time in Jakarta (`Asia/Jakarta`, UTC+7):
- `05:00 – 11:59 WIB`: Pagi (*"Selamat pagi"*)
- `12:00 – 14:59 WIB`: Siang (*"Selamat siang"*)
- `15:00 – 18:59 WIB`: Sore (*"Selamat sore"*)
- `19:00 – 04:59 WIB`: Malam (*"Selamat malam"*)

#### 5. Indonesian Natural Time Resolution
The system accurately maps natural Indonesian colloquial time expressions:
- *"jam set 9 malam ini"* / *"setengah sembilan malam"* $\rightarrow$ `20:30 WIB`
- *"jam set 8 pagi"* $\rightarrow$ `07:30 WIB`
- *"nanti sore jam 5"* $\rightarrow$ `17:00 WIB`
- *"besok siang jam 1"* $\rightarrow$ `13:00 WIB`

---

## 3. Dynamic Skills Discovery Architecture

Helmis loads specialized capability playbooks from `config/skills/*/SKILL.md` at runtime via `load_all_skills()` in `agent.py`.

```
config/skills/
├── people-directory/
│   └── SKILL.md             # Contact profiles and directory management
├── schedule-manager/
│   └── SKILL.md             # Calendar events, appointments and conflicts
├── task-manager/
│   └── SKILL.md             # Task prioritization, status and assignment
├── reminder-engine/
│   └── SKILL.md             # Timed reminder configuration and relative times
├── document-reader/
│   └── SKILL.md             # Multimodal OCR and structured data extraction
├── shared-notes/
│   └── SKILL.md             # Shared shopping lists, memos and trip plans
└── proactive-check/
    └── SKILL.md             # Periodic proactive outreach protocol
```

### Discovery Mechanism
When building the system instruction, `load_all_skills()` scans the skills directory, reads each markdown file, and concatenates them into the agent's prompt under `## ACTIVE SKILLS & BEHAVIORAL PLAYBOOKS:`.

### Skills Catalog

#### 1. `people-directory`
- **Scope**: Manages directory profiles for friends, family, coworkers, doctors, and vendors.
- **Output Format**:
  ```
  *[Name]* ([Relationship / Role])
  - Telepon: [Phone]
  - Email: [Email]
  - Catatan: [Notes]
  ```

#### 2. `schedule-manager`
- **Scope**: Evaluates calendar availability, schedules appointments, detects scheduling conflicts between Gilang and Bunga.

#### 3. `task-manager`
- **Scope**: Tracks action items, assigns responsibilities (`assignee: "Gilang" | "Bunga"`), and handles task completion workflows (`complete_task`).

#### 4. `reminder-engine`
- **Scope**: Parses natural language reminder requests, determines target recipients, and calculates precise WIB deadlines.

#### 5. `document-reader`
- **Scope**: Governs multimodal OCR on invoices, electricity bills, receipts, and identity documents. Instructs the model to extract amounts, dates, and account numbers without generating conversational filler.

#### 6. `shared-notes`
- **Scope**: Maintains collaborative household lists (grocery lists, packing checklists, project notes).

#### 7. `proactive-check`
- **Scope**: Dictates the behavioral protocol for scheduled cron evaluations and outbound morning briefings.
