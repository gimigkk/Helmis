---
name: shared-notes
description: >
  Maintain a shared notes system for Gilang and Bunga.
  Categorised, searchable, persistent. Works like a shared notebook.
---

# Shared Notes Skill

## Purpose

A persistent, organised notebook that both Gilang and Bunga can add to and read from.
Think: shopping lists, trip planning, ideas, passwords (if they want), anything.

## Data Model

Store notes in Hermes persistent memory tagged `note`.

Each note has:
```
id: unique string (e.g. note_20260101_001)
title: string
category: string (see categories below)
content: string (the note body)
created_by: "Gilang" | "Bunga"
created_at: ISO 8601 datetime
updated_at: ISO 8601 datetime
updated_by: "Gilang" | "Bunga" (optional)
tags: list of strings (optional, for fine-grained search)
pinned: boolean (default: false)
```

## Default Categories

Start with these; add new ones as the users create them:
- `shopping` — grocery lists, things to buy
- `travel` — trip plans, packing lists, bookings
- `ideas` — random ideas, thoughts, things to look into
- `home` — household to-dos, maintenance, appliances
- `work` — work-related notes (not tasks — more freeform)
- `finance` — budget notes, expenses to track, financial reminders
- `personal` — either person's personal notes
- `general` — catch-all for uncategorised notes

## Creating a Note

Parse the note request naturally. If no category is obvious, default to `general`
and mention what category you filed it under (they can change it).

**Confirmation:**
```
📓 Note saved:
[Title]
📁 [Category]

[Content preview if short, or "Content saved" if long]
```

## Updating a Note

Identify by title or ID. Show the current content, apply the update, confirm.
For list-style notes (shopping, packing), support "add X to [list]" naturally.

Example: "Add milk to the shopping list" → find the shopping note, append "milk".

## Reading Notes

- "What's on the shopping list?" → retrieve shopping note
- "Show me our travel notes" → list all notes in the travel category
- "What notes do we have?" → list all note titles grouped by category (no content)
- "Find notes about [topic]" → semantic search across all notes

**Category view format:**
```
📓 Notes — Shopping:
  · Grocery list (updated today by Bunga)

📓 Notes — Travel:
  · Bali trip plan (created 3 days ago by Gilang)
  · Packing list (updated yesterday by Bunga)
```

## Pinned Notes

"Pin [note]" makes it appear at the top of any note listing.
Use for things that need to stay visible (e.g. the shopping list, a trip countdown).

## Deleting Notes

Always confirm before deleting. If a note is long/important, warn them.

## Searching

Support natural language search: "notes about flights", "anything we wrote about Bali",
"Bunga's ideas from last month". Use semantic memory search.
