---
name: recurring-reminders
description: How to create recurring reminders (weekly class attendance, routines) and nagging reminders that repeat until confirmed.
---

# Recurring & Nagging Reminders

## Recurring reminders (weekly classes, routines)

Anything that repeats (kuliah, absensi, gym, weekly reports) MUST use the `recurrence` object on `add_task` — never create separate one-shot tasks per day.

Exact shape:

```json
{
  "title": "Absensi Komunikasi Data dan Jaringan Komputer",
  "due": "2026-09-08 07:45 WIB",
  "assignee": "Gilang",
  "priority": "urgent",
  "recurrence": {
    "type": "weekly",
    "weekdays": ["selasa"],
    "time": "07:45",
    "timezone": "Asia/Jakarta"
  },
  "nag_policy": {"interval_minutes": 5, "max_nags": 6}
}
```

Rules:
- `due` = the FIRST occurrence. The series advances itself to the next matching day after each delivery/completion.
- One task per recurring event. Multiple days for the same class = list them all in `weekdays`.
- `weekdays` accepts Indonesian names: senin, selasa, rabu, kamis, jumat, sabtu, minggu (or English, or 0-6 with 0=Monday).
- `time` = HH:MM local time. Set it at class START (absensi opens when class starts).
- `timezone`: always `Asia/Jakarta` for us.

For attendance reminders, set the due time AT class start (not 30 min early unless asked) and add a `nag_policy` so Helmis re-reminds every few minutes until the user confirms they filled it.

## Nagging reminders (repeat until user confirms)

Set `nag_policy: {"interval_minutes": N, "max_nags": M}` — after the due reminder fires, Helmis re-reminds every N minutes up to M times if the user has not replied/confirmed. Stop conditions: user confirms done, max nags reached, or task completed.

Examples:
- "ingetin absen tiap 5 menit kalau belum diisi" → nag_policy interval 5, max 6
- deadlines without confirmation → no nag_policy needed; single due reminder is enough

## Non-negotiables

- NEVER create separate tasks per weekday for a recurring event — one task with `weekdays` list.
- NEVER claim a recurring reminder is set without the `recurrence` object actually passed to add_task.
- After creating a recurring task, state the schedule plainly: title, days, time, and that it repeats weekly.
