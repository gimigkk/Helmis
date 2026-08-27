"""
schema.py — Declarative Gemini JSON Schema Definitions for All Native Tools.
"""

from typing import Any

GEMINI_TOOLS: list[dict[str, Any]] = [
    {
        "function_declarations": [
            {
                "name": "add_task",
                "description": "Save a task, appointment, deadline, or scheduled action to Helmis persistent storage. Can be used for human reminders ('Gilang', 'Bunga', 'Both') OR for autonomous bot actions scheduled for Helmis ('assignee': 'Helmis', 'task_type': 'scheduled_action').",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "title": {
                            "type": "STRING",
                            "description": "The task, reminder, or scheduled action description",
                        },
                        "due": {
                            "type": "STRING",
                            "description": "Date and time in WIB, e.g. '2026-08-26 18:00 WIB' or relative time like '30 menit lagi'",
                        },
                        "assignee": {
                            "type": "STRING",
                            "description": "Entity responsible: 'Gilang', 'Bunga', 'Both' (for human reminders), or 'Helmis' (for bot actions scheduled to execute autonomously)",
                        },
                        "priority": {
                            "type": "STRING",
                            "description": "Urgency level: 'urgent' (activates 10-minute nag escalation loop for humans until confirmed), 'normal' (standard reminder/action), or 'low'",
                        },
                        "lead_time_minutes": {
                            "type": "INTEGER",
                            "description": "Preparation buffer in minutes for human tasks (e.g. 120 for assignments/proposals, 30 for meetings). Set to 0 for bot actions or instant tasks.",
                        },
                        "task_type": {
                            "type": "STRING",
                            "description": "Type of task: 'reminder' (default for human todos/deadlines) or 'scheduled_action' (for actions Helmis executes autonomously when due).",
                        },
                        "job": {
                            "type": "OBJECT",
                            "description": "Polymorphic job execution descriptor for scheduled actions. E.g. {'kind': 'tool', 'tool_name': 'waha_send_message', 'tool_args': {'chat_id': '...', 'text': '...'}} or {'kind': 'tool', 'tool_name': 'send_vault_file_to_chat', 'tool_args': {'filename': '...', 'chat_id': '...'}} or {'kind': 'agent', 'prompt': '...', 'target_chat': '...'}",
                        },
                    },
                    "required": ["title", "due"],
                },
            },
            {
                "name": "list_tasks",
                "description": "List current tasks, reminders, and scheduled actions from storage. By default, items are sorted by urgency (earliest deadline first).",
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
                        "task_type": {
                            "type": "STRING",
                            "description": "Filter by task type: 'all' (default), 'reminder' (human todos only), or 'scheduled_action' (Helmis bot jobs only)",
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
                "description": "Update or reassign an existing task (change assignee, deadline, priority, lead time, title, or scheduled job descriptor).",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "title": {
                            "type": "STRING",
                            "description": "Existing task title or keyword to find",
                        },
                        "new_assignee": {
                            "type": "STRING",
                            "description": "New assignee: 'Gilang', 'Bunga', 'Both', or 'Helmis'",
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
                        "new_task_type": {
                            "type": "STRING",
                            "description": "New task type: 'reminder' or 'scheduled_action'",
                        },
                        "new_job": {
                            "type": "OBJECT",
                            "description": "Updated polymorphic job execution descriptor",
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
                        "as_document": {
                            "type": "BOOLEAN",
                            "description": "Set to true if user specifically asks to send as a document/file (uncompressed original quality). Defaults to false (sends images/videos as native preview bubbles).",
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
            {
                "name": "read_vault_file",
                "description": "Read and inspect the full text or content of a file from the Document Vault. Supports reading text/markdown/code/json/csv files, extracting text from PDF documents, and viewing image OCR summaries.",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "file_id_or_name": {
                            "type": "STRING",
                            "description": "File ID (e.g. 'doc_12345_abc') or exact filename (e.g. 'brosur_elera_education.pdf', 'catatan.md') to read.",
                        },
                        "max_chars": {
                            "type": "INTEGER",
                            "description": "Optional max characters to read. Defaults to 8000.",
                        },
                    },
                    "required": ["file_id_or_name"],
                },
            },
            {
                "name": "save_vault_file",
                "description": "Save an incoming document, scan, receipt, image, or text file into the Document Vault with metadata cataloging.",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "filename": {
                            "type": "STRING",
                            "description": "Clean filename for the saved document (e.g. 'scan_bpjs_kesehatan_gilang.pdf', 'ktp_bunga.jpg')",
                        },
                        "category": {
                            "type": "STRING",
                            "description": "Category for the file: 'health', 'id_cards', 'travel', 'receipts', 'documents', 'media', 'projects'. Defaults to 'documents'.",
                        },
                        "owner": {
                            "type": "STRING",
                            "description": "Owner of the document: 'Gilang', 'Bunga', or 'Both'/'Shared'. Defaults to sender.",
                        },
                        "subfolder": {
                            "type": "STRING",
                            "description": "Optional custom subfolder path inside vault (e.g. 'projects/kriyamic', 'travel/bali_trip').",
                        },
                        "description": {
                            "type": "STRING",
                            "description": "Human-readable description of what this file contains.",
                        },
                        "tags": {
                            "type": "ARRAY",
                            "items": {"type": "STRING"},
                            "description": "Searchable tags (e.g. ['bpjs', 'kesehatan', 'asuransi']).",
                        },
                        "ocr_summary": {
                            "type": "STRING",
                            "description": "Extracted OCR text or key data points from the file.",
                        },
                        "content_text": {
                            "type": "STRING",
                            "description": "Optional text/markdown content ONLY when creating a brand new text file from scratch. DO NOT supply this if the user uploaded an attachment or document, because the actual incoming binary file is saved automatically.",
                        },
                    },
                    "required": ["filename"],
                },
            },
            {
                "name": "search_vault_files",
                "description": "Search stored documents and files in the Document Vault across filenames, descriptions, tags, and OCR text.",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "query": {
                            "type": "STRING",
                            "description": "Search query keywords (e.g. 'scan bpjs', 'tiket garuda bali', 'ktp', 'cv', 'kontrak').",
                        },
                        "owner": {
                            "type": "STRING",
                            "description": "Filter by owner: 'Gilang', 'Bunga', or 'Both'.",
                        },
                        "category": {
                            "type": "STRING",
                            "description": "Filter by category: 'health', 'id_cards', 'travel', 'receipts', 'documents', 'media', 'projects'.",
                        },
                        "limit": {
                            "type": "INTEGER",
                            "description": "Maximum number of search results to return (default 10).",
                        },
                    },
                    "required": ["query"],
                },
            },
            {
                "name": "list_vault_files",
                "description": "List stored documents in the Document Vault filtered by owner, category, or subfolder directory.",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "owner": {
                            "type": "STRING",
                            "description": "Filter by owner: 'Gilang', 'Bunga', or 'Both'.",
                        },
                        "category": {
                            "type": "STRING",
                            "description": "Filter by category: 'health', 'id_cards', 'travel', 'receipts', 'documents', 'media', 'projects'.",
                        },
                        "directory": {
                            "type": "STRING",
                            "description": "Filter by specific directory path inside the vault.",
                        },
                    },
                },
            },
            {
                "name": "send_vault_file",
                "description": "Send a file stored in the Document Vault directly to a WhatsApp chat (DM or Trio Group).",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "file_id_or_name": {
                            "type": "STRING",
                            "description": "The file ID (from catalog) or filename (e.g. 'scan_bpjs_kesehatan_gilang.pdf').",
                        },
                        "recipient": {
                            "type": "STRING",
                            "description": "Recipient of the file: 'Gilang', 'Bunga', 'group' (Trio group), or 'current'.",
                        },
                        "caption": {
                            "type": "STRING",
                            "description": "Optional caption message accompanying the sent file.",
                        },
                        "as_document": {
                            "type": "BOOLEAN",
                            "description": "Set to true if user specifically asks to send as a document/file (uncompressed original quality). Defaults to false (sends images/videos as native preview bubbles).",
                        },
                    },
                    "required": ["file_id_or_name"],
                },
            },
            {
                "name": "move_vault_files",
                "description": "Dynamic tool to move single or multiple files in bulk to a new destination folder, category, or owner. Target can be a filename, a file ID, a list of IDs, or a search query string (e.g. 'kriyamic', '2025').",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "target": {
                            "type": "STRING",
                            "description": "The file ID, exact filename, list of IDs, or search query keywords to match files to move.",
                        },
                        "destination_directory": {
                            "type": "STRING",
                            "description": "Destination directory path inside vault (e.g. 'projects/kriyamic', 'receipts/archive_2025').",
                        },
                        "new_category": {
                            "type": "STRING",
                            "description": "Optional updated category name (e.g. 'receipts', 'health').",
                        },
                        "new_owner": {
                            "type": "STRING",
                            "description": "Optional updated owner: 'Gilang', 'Bunga', or 'Both'.",
                        },
                    },
                    "required": ["target"],
                },
            },
            {
                "name": "delete_vault_files",
                "description": "Dynamic tool to delete single or multiple files in bulk from the Document Vault. Target can be a filename, a file ID, a list of IDs, or a search query string.",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "target": {
                            "type": "STRING",
                            "description": "The file ID, exact filename, list of IDs, or search query keywords to match files to delete.",
                        },
                    },
                    "required": ["target"],
                },
            },
            {
                "name": "create_vault_directory",
                "description": "Create a new custom directory or nested subfolder inside the Document Vault.",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "directory_path": {
                            "type": "STRING",
                            "description": "Directory path to create inside the vault (e.g. 'projects/kriyamic', 'wedding/vendor_contracts').",
                        },
                    },
                    "required": ["directory_path"],
                },
            },
            {
                "name": "delete_vault_directory",
                "description": "Delete a directory from the Document Vault. Supports empty folder removal or recursive deletion with all files inside.",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "directory_path": {
                            "type": "STRING",
                            "description": "Directory path to delete inside the vault.",
                        },
                        "recursive": {
                            "type": "BOOLEAN",
                            "description": "Set to true to delete the folder along with all files inside. If false, fails if folder is not empty.",
                        },
                    },
                    "required": ["directory_path"],
                },
            },
        ]
    }
]
