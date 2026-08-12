# Helmis

Personal AI secretary for Gilang and Bunga — powered by Hermes Agent + Gemini, delivered through WhatsApp.

## What It Does

- 💬 Receives messages via WhatsApp (group chat + individual DMs)
- 🧠 One persistent brain — remembers everything, knows who said what
- 📅 Manages schedules, tasks, and reminders for both users
- 📄 Reads and summarises documents and images (via Gemini vision)
- 📝 Maintains shared notes (shopping lists, trip plans, ideas, etc.)
- ⏰ Proactive — sends reminders and deadline warnings without being asked
- 🔧 Full-capability agent — web search, file ops, terminal commands, and more

## Stack

| Component | Technology |
|---|---|
| AI Agent | [Hermes Agent](https://hermes-agent.nousresearch.com) |
| LLM | Gemini 2.5 Pro / Flash (free tier, 3-key rotation) |
| WhatsApp Bridge | [WAHA](https://waha.devlike.pro) (GOWS engine) |
| WAHA ↔ Hermes | Custom MCP server (`mcp-waha`, Python) |
| Proactive Triggers | Cron (supercronic, Alpine) |
| Orchestration | Docker Compose |

## Architecture

```
WhatsApp ──► WAHA ──webhook──► Hermes Agent
                                    │
                      ┌─────────────┼─────────────┐
                      │             │             │
                  Gemini API    MCP tools      Memory
                 (key pool)   (WAHA send)    (SQLite)
                      │             │
                    Skills       Scheduler
               (schedule,       (cron tick
                tasks, etc.)     every 5min)
```

## Project Structure

```
Helmis/
├── docker-compose.yml        # Single entry point — starts everything
├── .env.example              # Config template — copy to .env
├── .gitignore
│
├── mcp-waha/                 # MCP server: WAHA API wrapper
│   ├── Dockerfile
│   ├── pyproject.toml
│   ├── src/
│   │   ├── server.py         # Entry point
│   │   ├── client.py         # WAHA HTTP client (all HTTP here)
│   │   ├── models.py         # All data shapes (Pydantic v2)
│   │   └── tools/            # One file per MCP tool
│   │       ├── send_message.py
│   │       ├── send_media.py
│   │       └── get_messages.py
│   └── tests/
│       └── test_client.py
│
├── scheduler/                # Cron container — proactive trigger
│   ├── Dockerfile
│   ├── trigger.sh
│   └── crontab
│
├── config/                   # Hermes configuration (read-only mount)
│   ├── hermes.toml           # Provider, credentials, webhook, MCP
│   ├── system-prompt.md      # Helmis personality and rules
│   └── skills/               # Secretary skills
│       ├── people-directory/
│       ├── schedule-manager/
│       ├── task-manager/
│       ├── reminder-engine/
│       ├── document-reader/
│       ├── shared-notes/
│       └── proactive-check/
│
└── scripts/
    ├── setup.sh              # One-command first-time setup
    └── backup.sh             # Data backup (run or cron-schedule)
```

## Setup

### Prerequisites

- A VPS (Linux, 4 cores, 6 GB RAM minimum)
- Docker + Docker Compose v2 installed
- A WhatsApp number for the bot (dedicated number recommended)
- At least 1 Gemini API key (3 recommended, from separate Google accounts)

### First-time setup

```bash
# 1. Clone the repo
git clone <your-repo-url> helmis
cd helmis

# 2. Run the setup script
chmod +x scripts/setup.sh
./scripts/setup.sh

# 3. Authenticate WhatsApp directly in your terminal:
./scripts/auth.sh

# Scan the ASCII QR code that appears in your terminal using the bot's phone.
# Once paired, start the remaining services:
docker compose up -d
```

That's it. Helmis is live.

### Manual .env setup

If you prefer to configure manually:

```bash
cp .env.example .env
# Edit .env with your values
docker compose up -d
```

## Configuration

All configuration lives in `.env` and `config/`.

### Key env vars

| Variable | Description |
|---|---|
| `GEMINI_KEY_1/2/3` | Gemini API keys (separate Google accounts) |
| `WAHA_API_KEY` | WAHA authentication key |
| `GILANG_PHONE` | Gilang's WA number (e.g. `628123456789`) |
| `BUNGA_PHONE` | Bunga's WA number |
| `BOT_PHONE` | Helmis bot's WA number |
| `TZ` | Timezone (default: `Asia/Jakarta`) |

### Hermes config

`config/hermes.toml` — model provider, credential pools, webhook routes, MCP servers, memory settings.

### System prompt

`config/system-prompt.md` — Helmis's personality, behaviour rules, and identity awareness.
Edit this to tune how Helmis communicates.

### Skills

`config/skills/*/SKILL.md` — Each skill is a self-contained markdown file.
Hermes reads these to know how to handle scheduling, tasks, reminders, etc.

## Usage

### Commands (natural language)

Helmis understands natural language — no slash commands needed.

**Scheduling:**
- "Schedule a dentist appointment for Thursday at 2pm"
- "What do I have this week?"
- "Is Bunga free Saturday morning?"

**Tasks:**
- "Add a task: submit the proposal, due Friday, high priority"
- "What tasks are overdue?"
- "Mark the proposal as done"

**Reminders:**
- "Remind me to call the bank at 3pm"
- "Remind Bunga to take her medicine every morning at 8"
- "Cancel the bank reminder"

**Notes:**
- "Add milk to the shopping list"
- "Save this idea: [idea]"
- "What's on our shopping list?"

**Documents:**
- Just send any image, photo, or document — Helmis reads and remembers it automatically
- "What was in that electricity bill?"

**General:**
- Ask it anything — web search, writing, calculations, research
- "Remind me to follow up on this in 3 days" after any conversation

## Operations

### Common commands

```bash
# Check status of all services
docker compose ps

# Live logs
docker compose logs -f hermes     # AI brain
docker compose logs -f waha       # WhatsApp bridge
docker compose logs -f mcp-waha   # MCP tool server
docker compose logs -f scheduler  # Cron triggers

# Restart a single service
docker compose restart hermes

# Stop everything
docker compose down

# Stop and remove all data (destructive!)
docker compose down -v
```

### Backup

```bash
# Manual backup (saved to ./backups/)
./scripts/backup.sh

# Or backup to a specific location
./scripts/backup.sh /mnt/external/helmis-backups

# Schedule daily backups at 3am on the host:
# Add to crontab: 0 3 * * * /path/to/helmis/scripts/backup.sh
```

### Adding a Gemini key later

1. Add the key to `.env`: `GEMINI_KEY_4=...`
2. Add it to `config/hermes.toml` credential pool
3. `docker compose restart hermes`

## Troubleshooting

**WhatsApp session expired / QR code needed again**
```bash
# Access the WAHA dashboard
# SSH tunnel: ssh -L 3000:localhost:3000 user@your-vps
# Then open: http://localhost:3000/dashboard
```

**Hermes not responding**
```bash
docker compose logs hermes --tail=50
docker compose restart hermes
```

**Gemini rate limits hit**
```bash
# Check which keys are exhausted in Hermes logs
docker compose logs hermes | grep "429\|rate limit"
# Add more keys to .env and hermes.toml if needed
```

**Proactive messages not sending**
```bash
# Check scheduler is running
docker compose logs scheduler --tail=20
# Check Hermes webhook is receiving ticks
docker compose logs hermes | grep "scheduler.tick"
```
