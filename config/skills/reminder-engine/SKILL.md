---
name: reminder-engine
description: >
  Set, manage, and fire time-based reminders for Gilang and Bunga.
  Supports one-shot and recurring reminders. Checked every 5 minutes by the scheduler.
---

# Reminder Engine Skill

## Purpose

Be the alarm clock and follow-up system. When someone says "remind me to X at Y",
store it, fire it at the right time, and confirm it was handled.

## Formatting Directives (WhatsApp Native)
- NO EMOJIS: Never use emojis in confirmations or notifications.
- WHATSAPP BOLD: Use single asterisks `*text*`, never double asterisks.
- NATURAL CONVERSATIONAL: Confirm with a natural sentence without boilerplate cards.

## Parsing & Confirming
- "jam set 9 malam ini" -> `Hari ini, 20:30 WIB`
- "besok pagi jam 8" -> `Besok, 08:00 WIB`

Confirmation Example:
- Single: "Oke [Name], nanti jam [Time] WIB akan saya ingatkan untuk *[Task]*."
- Shared / Couple: "Siap, nanti jam [Time] WIB akan saya ingatkan kalian berdua untuk *[Task]*."

## Firing a Proactive Reminder
When a reminder triggers:
- Individual: "Halo [Name], pengingat: *[Task]* (Waktu: [Due])."
- Shared / Group: "Halo Guys, pengingat bersama: *[Task]* (Waktu: [Due])."
