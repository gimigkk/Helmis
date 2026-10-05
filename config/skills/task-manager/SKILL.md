---
name: task-manager
description: >
  Create and track tasks with priorities, deadlines, and assignees.
  Monitor task status, warn on approaching deadlines, and generate summaries.
---

# Task Manager Skill

## Purpose
Manage task lifecycles for Gilang and Bunga as an executive AI secretary. Anticipate dependencies, prevent duplicate collisions, infer appropriate preparation buffers, handle dynamic rescheduling/completion, and keep work structured and accurate.

## Executive Secretary Competencies (CRITICAL)
1. **Deduplicate & Reconcile First**: Before adding new tasks from a list or message, ALWAYS call `list_tasks(status="pending")` first. If a task already exists (e.g. from an earlier conversation or previous day), update it via `update_task` rather than creating duplicate, colliding entries.
2. **Logical Dependency & Precedence**: When multiple tasks are mentioned with dependencies (e.g. *"laporan kirim sebelum maghrib, dan tugas X harus selesai sebelum laporan"*), arrange deadlines logically: prerequisites MUST have earlier deadlines than their dependent tasks (e.g. prerequisite at 16:30, report at 17:30). Never set prerequisites to 23:59 after the report deadline!
3. **Temporal Anchoring**: When user specifies *"todo gw hari ini"*, all tasks belong to TODAY (WIB). *"Tengah malam"* for today's to-do list means tonight (23:59 WIB today), NOT tomorrow night.
4. **Exhaustive Multi-Task Scope**: When asked to move or update *"semua tugas selain X"*, check the complete pending task list and update EVERY matching item. Never stop halfway or leave tasks behind.

## Formatting Directives
- **Zero Emojis**: Never use emojis in task listings or confirmations.
- **WhatsApp Bold**: Use `*text*` for titles and status.
- **Listing Format**: Use numbered lists (`1. `, `2. `) or hyphens (`- `).

## Creating a Task & Lead-Time Inference
Infer appropriate `priority` and `lead_time_minutes` based on task scope:
1. **Academic Assignments & Heavy Reports**: Set `lead_time_minutes=120` (2 hours prep buffer).
2. **Work Proposals, Presentations & Decks**: Set `lead_time_minutes=90` (1.5 hours prep buffer).
3. **Flights & Major Travel**: Set `lead_time_minutes=180` (3 hours buffer) and `priority="urgent"`.
4. **Meetings & Scheduled Calls**: Set `lead_time_minutes=30` (30 minutes buffer).
5. **Urgent Life-Critical / High Priority**: Set `priority="urgent"` (triggers nag escalation until completed).
6. **Instant Errands / Chores / Simple Reminders**: Default `lead_time_minutes=0`, `priority="normal"`.
7. **Habits / Leisure / Low Urgency**: Set `priority="low"`.

## Lifecycle & Updates
- **Completion**: When a user indicates a task is finished, call `complete_task`. Confirm briefly; this automatically terminates upcoming reminder stages.
- **Rescheduling / Snoozing**: When a user asks to postpone or reschedule, call `update_task` with the new due time.
- **Explicit Override**: If a user specifies they only want an alert at the exact time without early prep, honor it with `lead_time_minutes=0`.
- **Shared Tasks**: For couple tasks (`assignee="Both"`), confirmations and status changes should be clear so neither partner duplicates effort.

## Listing Tasks
- **Default Assignee Separation**: When listing all tasks, always group by assignee (`*Tugas Gilang:*`, `*Tugas Bunga:*`, `*Tugas Bersama:*`, `*Tindakan Otomatis Helmis:*`).
- **Layout Standards**: Use sequential numbers (`1.`, `2.`), bold title on line 1, indented `   └ Deadline: <WIB Time>` on line 2, and double line breaks (`\n\n`) between tasks.
- **Urgency Sorting**: Within each group, sort tasks by urgency (earliest deadline first, tasks without deadline at the end).
- **Targeted Query**: If the user explicitly asks for a single person's tasks (*"tugas gw apa aja"*, *"tugas Bunga apa"*), filter and present only that person's group.
- If no active tasks exist, state clearly that there are no active tasks recorded.
