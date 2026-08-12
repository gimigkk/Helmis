---
name: proactive-check
description: >
  Run every 5 minutes via the scheduler. Checks for due reminders,
  approaching deadlines, and upcoming events. Sends WhatsApp messages
  proactively when action is needed.
---

# Proactive Check Skill

## Purpose

This skill is triggered by the cron scheduler every 5 minutes via the
`/webhooks/scheduler` route. It is the engine for Helmis's proactive behaviour.

**Important**: This skill must be fast and quiet. If nothing needs to be sent, do nothing.
Don't send "all clear" messages — silence is the correct output when nothing is due.

## Execution Order

Run these checks in sequence on every tick:

### 1. Due Reminders

Query all reminders with `status: "active"`.
For each reminder:
- If `fire_at` ≤ now (for one-shot): it's due → fire it
- If recurring and `fire_at` for this recurrence ≤ now: it's due → fire it
- Apply anti-spam guard: skip if `last_fired_at` was less than 4 minutes ago

**Firing a reminder:**
1. Send via `waha_send_message` to the correct chat
   - Format: `⏰ Reminder, [Name]: [message]`
2. Update the reminder in memory:
   - One-shot: set `status: "fired"`
   - Recurring: set `last_fired_at` to now, calculate next `fire_at`

### 2. Task Deadline Warnings

Query all tasks with `status` in `["todo", "in-progress"]` and a `due_date` set.

For each task, check these thresholds (send each warning only once):
- **Overdue**: `due_date` < today → "⚠️ [Name], [task title] was due [date] and isn't done yet."
- **Due today**: `due_date` == today and warning not yet sent today → "📅 [Name], [task] is due today."
- **Due tomorrow**: `due_date` == tomorrow and 1-day warning not yet sent → "📅 [Name], heads up — [task] is due tomorrow."
- **Due in 2 hours**: `due_time` set and (due_time - now) ≤ 2h and > 0 → "⏰ [Name], [task] is due in about 2 hours."

**Warning deduplication**: Track sent warnings in memory tagged `warning_sent`:
```
task_id + threshold → last_sent_at
```
Only send a warning if `last_sent_at` for that (task_id, threshold) pair is more than 20 hours ago.

### 3. Upcoming Calendar Events

Query all schedule events where `start_time` is in the next 24 hours.

For each event, check these thresholds:
- **1 day before**: send the day before, once
- **1 hour before**: send 60–65 minutes before start

Format:
```
📅 [Name], reminder: [Event Title]
🕐 [Day] at [Time] WIB
📍 [Location] (if set)
```

Apply same deduplication logic as task warnings.

### 4. Important Dates

Query memories tagged `important_date` (birthdays, anniversaries, etc.).
For each:
- **2 days before**: send a heads-up
- **On the day**: send a morning message (between 07:00–09:00 WIB only)

## Delivery Routing

Where to send proactive messages:
- If the event/task/reminder is assigned to one person only → send to their DM
- If assigned to "Both" → send to the group chat
- If it's an important date (e.g. a shared anniversary) → send to the group chat

## Failure Handling

If any check fails (e.g. WAHA is temporarily unreachable):
- Log the failure silently
- Do NOT crash the entire tick
- The next 5-minute tick will retry naturally

## Performance

This skill runs every 5 minutes. It must complete quickly:
- Use indexed/filtered memory queries, not full scans
- Bail out of each check early if nothing is found
- Total execution target: under 5 seconds
