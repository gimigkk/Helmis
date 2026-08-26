---
name: reminder-engine
description: Set, manage, and fire time-based reminders for Gilang and Bunga.
---

# Reminder Engine Skill

## Purpose
Set, manage, and fire time-based reminders.

## Operational Directives
- **Zero Emojis**: Never use emojis in reminder confirmations or proactive notifications.
- **WhatsApp Bold**: Use `*text*` for titles and times.
- **Natural Confirmations**: Confirm scheduled reminders in one crisp, natural sentence specifying the target time and task.
- **Timezone**: Resolve all relative time expressions (e.g. *nanti sore*, *jam set 9 malam*, *besok siang*) against the current WIB reference clock.

## Firing Reminders
- When a reminder is due, deliver a concise notification to the target recipient or group.
- State the task title and time clearly.
