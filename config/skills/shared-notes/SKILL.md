---
name: shared-notes
description: Maintain a shared notes system for Gilang and Bunga. Categorized, searchable, and persistent.
---

# Shared Notes Skill

## Purpose
Maintain persistent, organized notes, lists, and reference items for Gilang and Bunga.

## Standard Categories
- `shopping`: Grocery lists, items to purchase.
- `travel`: Itineraries, packing checklists, booking notes.
- `ideas`: Brainstorms, project concepts, references.
- `home`: Household maintenance, appliances, chores.
- `work`: Work-related references and meeting summaries.
- `finance`: Budgets, shared expenses, tracking notes.
- `personal`: Individual notes.
- `general`: Default fallback category.

## Note Operations
1. **Creating Notes**: Call `save_note(title=..., content=..., category=...)`. Confirm briefly with title and category.
2. **Updating & Appending**: Call `save_note` with the existing title/id to overwrite or append new items (e.g. adding items to shopping lists).
3. **Retrieval**: Call `get_note` by title or `list_notes` by category. Present contents cleanly without decorative emojis.
4. **Search**: Search notes using keyword or semantic search across stored memory.
5. **Deletion**: Delete obsolete notes when requested via `delete_note`.
