"""
schema.py — Declarative Gemini JSON Schema Definitions for All Native Tools.
"""

from typing import Any

GEMINI_TOOLS: list[dict[str, Any]] = [
    {
        "function_declarations": [
            {
                "name": "add_task",
                "description": "Save a task, appointment, deadline, or reminder to Helmis persistent storage.",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "title": {
                            "type": "STRING",
                            "description": "The task or reminder description",
                        },
                        "due": {
                            "type": "STRING",
                            "description": "Date and time in WIB, e.g. '2026-08-26 18:00 WIB'",
                        },
                        "assignee": {
                            "type": "STRING",
                            "description": "Person responsible: 'Gilang', 'Bunga', or 'Both' (for shared couple/team tasks)",
                        },
                        "priority": {
                            "type": "STRING",
                            "description": "Urgency level: 'urgent' (activates 10-minute nag escalation loop until confirmed), 'normal' (standard single reminder), or 'low' (gentle/backlog)",
                        },
                        "lead_time_minutes": {
                            "type": "INTEGER",
                            "description": "Preparation buffer in minutes for non-instant tasks (e.g. 120 for assignments/proposals, 180 for flights, 30 for meetings). 0 for instant tasks.",
                        },
                    },
                    "required": ["title", "due"],
                },
            },
            {
                "name": "list_tasks",
                "description": "List current tasks and reminders from storage. By default, items are sorted by urgency (earliest deadline first).",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "status": {
                            "type": "STRING",
                            "description": "Filter by status: 'pending', 'completed', or 'all'",
                        },
                        "sort_by": {
                            "type": "STRING",
                            "description": "Sorting criteria: 'urgency' (default, earliest deadline/overdue first), 'created' (newest first), or 'alphabetical'",
                        },
                    },
                },
            },
            {
                "name": "complete_task",
                "description": "Mark an active task as finished/completed when user says it is done ('sudah selesai', 'udah beres', 'done').",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "title": {
                            "type": "STRING",
                            "description": "Task title or keyword to mark completed",
                        }
                    },
                    "required": ["title"],
                },
            },
            {
                "name": "update_task",
                "description": "Update or reassign an existing task (change assignee, deadline, priority, lead time, or title).",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "title": {
                            "type": "STRING",
                            "description": "Existing task title or keyword to find",
                        },
                        "new_assignee": {
                            "type": "STRING",
                            "description": "New assignee: 'Gilang', 'Bunga', or 'Both'",
                        },
                        "new_due": {
                            "type": "STRING",
                            "description": "New deadline in WIB, e.g. '2026-08-25 19:00 WIB'",
                        },
                        "new_title": {
                            "type": "STRING",
                            "description": "New title if renaming",
                        },
                        "new_priority": {
                            "type": "STRING",
                            "description": "New priority: 'urgent', 'normal', or 'low'",
                        },
                        "new_lead_time_minutes": {
                            "type": "INTEGER",
                            "description": "New preparation buffer in minutes",
                        },
                    },
                    "required": ["title"],
                },
            },
            {
                "name": "delete_task",
                "description": "Delete or cancel a task from storage entirely.",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "title": {
                            "type": "STRING",
                            "description": "Task title or keyword to delete",
                        }
                    },
                    "required": ["title"],
                },
            },
            {
                "name": "add_person",
                "description": "Save or update a person in the contacts directory (friends, colleagues, managers, doctors, family).",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "name": {"type": "STRING", "description": "Person's name or alias"},
                        "phone": {"type": "STRING", "description": "Phone number if provided"},
                        "role": {
                            "type": "STRING",
                            "description": "Role or relationship (e.g. 'Gilang manager', 'Bunga sister')",
                        },
                        "notes": {
                            "type": "STRING",
                            "description": "Important context, preferences, or details",
                        },
                    },
                    "required": ["name"],
                },
            },
            {
                "name": "get_person",
                "description": "Look up contact details and notes for a person by name from the directory.",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "name": {"type": "STRING", "description": "Name of the person to look up"}
                    },
                    "required": ["name"],
                },
            },
            {
                "name": "save_note",
                "description": "Save or completely overwrite a shared note, memo, or document in persistent storage.",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "title": {"type": "STRING", "description": "Note title"},
                        "content": {"type": "STRING", "description": "Note body"},
                    },
                    "required": ["title", "content"],
                },
            },
            {
                "name": "get_note",
                "description": "Retrieve the complete text and details of a specific note or memo by its title.",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "title": {"type": "STRING", "description": "Title or keyword of the note to retrieve"}
                    },
                    "required": ["title"],
                },
            },
            {
                "name": "list_notes",
                "description": "List all shared notes, memos, and documents currently saved in memory.",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {},
                },
            },
            {
                "name": "append_to_note",
                "description": "Append text or items to an existing note, or create a new note if it does not exist yet. Ideal for living lists like groceries, packing lists, gift ideas, or recommendations.",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "title": {"type": "STRING", "description": "Title of the note to append to"},
                        "text": {"type": "STRING", "description": "The item or text to append to the note"},
                    },
                    "required": ["title", "text"],
                },
            },
            {
                "name": "delete_note",
                "description": "Delete a note from storage by title or keyword match.",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "title": {"type": "STRING", "description": "Title or keyword of the note to delete"}
                    },
                    "required": ["title"],
                },
            },
            {
                "name": "remember_fact",
                "description": "Store a durable personal fact, preference, habit, relationship, dietary detail, or context about Gilang or Bunga in episodic semantic memory.",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "fact": {
                            "type": "STRING",
                            "description": "The exact fact or preference to remember (e.g. 'Gilang tidak suka kopi manis')",
                        },
                        "user_id": {
                            "type": "STRING",
                            "description": "Target person: 'Gilang', 'Bunga', or 'Both'",
                        },
                    },
                    "required": ["fact"],
                },
            },
            {
                "name": "delete_memory",
                "description": "Delete personal facts, preferences, habits, or context from semantic vector memory by keyword or description.",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "query": {
                            "type": "STRING",
                            "description": "Fact or keyword to delete from memory",
                        },
                        "user_id": {
                            "type": "STRING",
                            "description": "Optional: 'Gilang', 'Bunga', or 'Both'",
                        },
                    },
                    "required": ["query"],
                },
            },
            {
                "name": "recall_memory",
                "description": "Search semantic vector memory for personal preferences, past discussions, habits, or biographical facts about Gilang or Bunga.",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "query": {
                            "type": "STRING",
                            "description": "Topic, question, or keyword to semantically search for",
                        }
                    },
                    "required": ["query"],
                },
            },
            {
                "name": "search_memory",
                "description": "Search across all tasks, contacts, and notes for any keyword.",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "query": {
                            "type": "STRING",
                            "description": "Keyword to search across memory",
                        }
                    },
                    "required": ["query"],
                },
            },
            {
                "name": "send_status_update",
                "description": "Send a brief 1-line intermediate progress update or acknowledgment to the user in the current chat while you continue processing a multi-step task (e.g. 'Siap Gilang, sedang saya kumpulkan 3 opsi venue di Bogor ya...'). Use this ONLY for multi-step research, heavy document analysis, or complex coordination. NEVER use for instant single-step queries.",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "text": {
                            "type": "STRING",
                            "description": "Brief, natural 1-line progress update or acknowledgment with ZERO EMOJIS",
                        }
                    },
                    "required": ["text"],
                },
            },
            {
                "name": "send_whatsapp_message",
                "description": "Send a WhatsApp message directly to a recipient ('Gilang', 'Bunga', 'group', or phone number). Optionally quote a specific message ID for clarification or context.",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "recipient": {
                            "type": "STRING",
                            "description": "Target: 'Gilang', 'Bunga', 'group', or phone number",
                        },
                        "text": {
                            "type": "STRING",
                            "description": "Message content in WhatsApp markdown with ZERO EMOJIS",
                        },
                        "quote_message_id": {
                            "type": "STRING",
                            "description": "Optional WhatsApp message ID to quote (e.g. for clarification or replying to a specific question)",
                        },
                    },
                    "required": ["recipient", "text"],
                },
            },
            {
                "name": "get_whatsapp_messages",
                "description": "Fetch verified WhatsApp chat messages from a DM (Gilang/Bunga) or the Trio group chat. Supports date range filtering (e.g. 'today', 'yesterday', '2026-08-25', or since_hours_ago). Use this whenever asked whether someone sent a message or to inspect actual chat history.",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "target": {
                            "type": "STRING",
                            "description": "Target chat: 'Gilang' (DM), 'Bunga' (DM), or 'Group' (Trio Helmis group chat)",
                        },
                        "date": {
                            "type": "STRING",
                            "description": "Optional date filter: 'today', 'yesterday', or 'YYYY-MM-DD' (e.g. '2026-08-25')",
                        },
                        "since_hours_ago": {
                            "type": "INTEGER",
                            "description": "Optional filter for messages within the last N hours (e.g. 1, 3, 24)",
                        },
                        "limit": {
                            "type": "INTEGER",
                            "description": "Number of messages to retrieve (default 20, max 50)",
                        },
                    },
                    "required": ["target"],
                },
            },
            {
                "name": "send_whatsapp_media",
                "description": "Send a media attachment (image, photo, document, PDF) directly to a WhatsApp recipient ('Gilang', 'Bunga', 'group', or phone number).",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "recipient": {
                            "type": "STRING",
                            "description": "Target: 'Gilang', 'Bunga', 'group', or phone number",
                        },
                        "media_url": {
                            "type": "STRING",
                            "description": "Public URL or accessible local path of the media/image/document file",
                        },
                        "caption": {
                            "type": "STRING",
                            "description": "Optional caption for the media in WhatsApp markdown with ZERO EMOJIS",
                        },
                    },
                    "required": ["recipient", "media_url"],
                },
            },
            {
                "name": "web_search",
                "description": "Search the live web for real-time information, places, restaurants, operating hours, recipes, weather, news, or factual lookups.",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "query": {
                            "type": "STRING",
                            "description": "Search query keywords (e.g. 'restoran sunda senopati jam buka', 'cuaca bandung besok')",
                        },
                    },
                    "required": ["query"],
                },
            },
        ]
    }
]
