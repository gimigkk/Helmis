---
name: task-manager
description: >
  Create and track tasks with priorities, deadlines, and assignees.
  Monitor task status, warn on approaching deadlines, and generate summaries.
---

# Task Manager Skill

## Purpose

Be the to-do system for Gilang and Bunga. Tasks can be assigned to one person, both,
or shared. Track status, deadlines, and escalate before things slip.

## Formatting Directives (WhatsApp Native)
- NO EMOJIS: Never use emojis in confirmations, lists, or headers.
- WHATSAPP BOLD: Use single asterisks `*text*` for bolding, never double asterisks.
- LIST FORMAT: Use standard numbers `1. `, `2. ` or hyphens `- `. Never use dot bullets like `·`.
- NATURAL TONE: Confirm actions in a single, direct, natural sentence.

## Creating a Task
Confirm with natural 1-sentence WhatsApp message:
Example: "Sip Bunga, sudah dicatat untuk ngerjain tugas Ekonomi Syariah hari ini jam 20:30 WIB."

## Updating Task Status
- "sudah selesai" / "udah beres" / "done" -> call complete_task and confirm: "Sip, *[Title]* sudah ditandai selesai."
- "hapus / cancel" -> call delete_task and confirm: "Sip, *[Title]* sudah dihapus dari daftar."

## Listing Tasks
Format cleanly without repetitive headers or filler:
```
Daftar tugas [Name]:
1. *[Title]* (Hari ini, [Time] WIB)
2. *[Title]* (Besok, [Time] WIB)
```
If no tasks: "Belum ada tugas yang tercatat untuk [Name]."
