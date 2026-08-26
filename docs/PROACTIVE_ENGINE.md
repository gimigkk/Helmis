# Proactive Engine & Scheduler Architecture

This document details the background proactive engine of Helmis, covering the **Supercronic Daemon**, **5-Minute Cron Webhook Triggers**, **Multi-Stage Lead-Time Buffering**, and **10-Minute Nag Loops** for critical tasks.

---

## 1. Scheduler Topology

The proactive engine operates as an independent background container (`helmis-scheduler`) orchestrated in `docker-compose.yml`.

```
┌────────────────────────────────────────────────────────┐
│  helmis-scheduler Container (Alpine Linux)              │
│                                                        │
│  Supercronic Cron Daemon                               │
│  └── Every 5 minutes (*/5 * * * *)                     │
│      └── /app/trigger.sh                               │
│          └── HTTP POST /webhooks/scheduler             │
└───────────────────────────┬────────────────────────────┘
                            │ Internal HTTP POST
                            ▼
┌────────────────────────────────────────────────────────┐
│  helmis-agent Container (Python ReAct)                 │
│                                                        │
│  Webhook Route: /webhooks/scheduler                    │
│  └── Evaluates active tasks, reminders, schedules      │
│  └── Dispatches WhatsApp alerts via WAHA API           │
└────────────────────────────────────────────────────────┘
```

---

## 2. Multi-Stage Reminder Lifecycle (`src/agent/proactive.py`)

Rather than merely firing at the exact deadline, Helmis evaluates tasks across 3 progressive stages:

```
[Now] ──────► [Stage 1: Lead-Time Buffer] ──────► [Stage 2: Due Alert] ──────► [Stage 3: Nag Loop]
                   (Heads-up prep window)              (Deadline reached)           (Urgent overdue nudge)
```

### Stage 1: Preparation Lead-Time Window
- Automatically calculated from `lead_time_minutes` (e.g. 120m for academic assignments, 90m for decks, 180m for flights, 30m for meetings).
- Dispatches a preparatory notification so the user has sufficient time to complete the work before the deadline.

### Stage 2: Exact Due Alert
- Fires when the deadline arrives, notifying the assignee that the task is due.

### Stage 3: Critical 10-Minute Nag Loop
- For tasks marked `priority="urgent"`: if the deadline passes without the task being marked complete, the scheduler sends persistent periodic nudges (every 10–15 minutes) until the user marks it completed or reschedules.

---

## 3. Anti-Spam Deduplication & Silence Invariant

- **Deduplication**: Once a stage notification is fired for a task, its stage is recorded in `reminded_stages`. It will never fire a second time for that threshold unless the task deadline is updated or rescheduled.
- **Silence on Inaction**: If no tasks, reminders, or schedule events are due during a 5-minute tick, the scheduler completes silently with zero output.
