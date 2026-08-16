"""
agent.py — Autonomous ReAct Agent Loop, Tool Dispatcher, and Gemini LLM Client.
"""

import logging
import os
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from .client import WahaClient
from .history import build_multi_turn_contents
from .memory import (
    add_person,
    add_task,
    complete_task,
    delete_task,
    get_memory_context_summary,
    get_person,
    list_tasks,
    save_note,
    search_memory,
    update_task,
)

log = logging.getLogger("helmis-agent")

# Dynamically collect all configured Gemini API keys (GEMINI_KEY_1, GEMINI_KEY_2, etc.)
GEMINI_KEYS = [
    v.strip() for k, v in sorted(os.environ.items()) if k.startswith("GEMINI_KEY") and v.strip()
]


def fetch_available_gemini_models() -> list[str]:
    """Dynamically query Google API for all available models supporting generateContent."""
    discovered: list[str] = []
    for key in GEMINI_KEYS:
        try:
            resp = httpx.get(
                f"https://generativelanguage.googleapis.com/v1beta/models?key={key}", timeout=5.0
            )
            if resp.status_code == 200:
                raw_models = resp.json().get("models", [])
                for m in raw_models:
                    name = m.get("name", "").replace("models/", "")
                    methods = m.get("supportedGenerationMethods", [])
                    if "generateContent" in methods and not any(
                        skip in name
                        for skip in [
                            "tts",
                            "image",
                            "banana",
                            "robotics",
                            "computer-use",
                            "research",
                            "clip",
                        ]
                    ):
                        if name not in discovered:
                            discovered.append(name)
                if discovered:
                    break
        except Exception as e:
            log.warning("Could not fetch models dynamically with key: %s", e)

    if not discovered:
        # Fallback list if offline
        return [
            "gemini-3.1-flash-lite",
            "gemini-3.5-flash-lite",
            "gemini-3.1-flash-lite-preview",
            "gemini-flash-lite-latest",
            "gemini-3.5-flash",
            "gemini-3.6-flash",
            "gemini-3.7-flash",
            "gemini-2.5-flash",
            "gemini-flash-latest",
            "gemini-3.1-pro-preview",
            "gemini-2.5-pro",
            "gemini-pro-latest",
        ]

    # Sort: Flash-Lite first (sub-second speed), then Flash, then Gemma, then Pro
    def score_model(m: str) -> int:
        m_lower = m.lower()
        if "flash-lite" in m_lower or "flash_lite" in m_lower:
            return 1
        elif "flash" in m_lower:
            return 2
        elif "gemma" in m_lower:
            return 3
        elif "pro" in m_lower:
            return 4
        return 5

    discovered.sort(key=score_model)
    return discovered


# Dynamically Discovered Model Cascade
GEMINI_MODELS = fetch_available_gemini_models()
log.info(
    "Initialized dynamic Gemini model cascade with %d models: %s", len(GEMINI_MODELS), GEMINI_MODELS
)

# Agentic Tool Declarations
GEMINI_TOOLS = [
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
                            "description": "Person responsible: 'Gilang' or 'Bunga'",
                        },
                    },
                    "required": ["title", "due"],
                },
            },
            {
                "name": "list_tasks",
                "description": "List current tasks and reminders from storage to inspect pending or scheduled items.",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "status": {
                            "type": "STRING",
                            "description": "Filter by status: 'pending', 'completed', or 'all'",
                        }
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
                "description": "Update or reassign an existing task (change assignee, deadline, or title).",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "title": {
                            "type": "STRING",
                            "description": "Existing task title or keyword to find",
                        },
                        "new_assignee": {
                            "type": "STRING",
                            "description": "New assignee: 'Gilang' or 'Bunga'",
                        },
                        "new_due": {
                            "type": "STRING",
                            "description": "New deadline in WIB, e.g. '2026-08-25 19:00 WIB'",
                        },
                        "new_title": {
                            "type": "STRING",
                            "description": "New title if renaming",
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
                "description": "Save a shared note, memo, or key fact to persistent storage.",
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
        ]
    }
]


_key_index = 0


def get_next_gemini_key() -> str:
    """Round-robin rotation across available Gemini keys."""
    global _key_index
    if not GEMINI_KEYS:
        raise ValueError("No GEMINI_KEY configured in environment")
    key = GEMINI_KEYS[_key_index % len(GEMINI_KEYS)]
    _key_index += 1
    return key


def load_system_prompt() -> str:
    """Load system prompt from config."""
    prompt_path = os.environ.get("SYSTEM_PROMPT_PATH", "/hermes-config/system-prompt.md")
    if not os.path.exists(prompt_path):
        prompt_path = "config/system-prompt.md"
    try:
        with open(prompt_path, encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        log.warning("Could not read system prompt file (%s), using default: %s", prompt_path, e)
        return "You are Helmis, personal AI secretary for Gilang and Bunga. Address them by name and be proactive and concise."


def load_all_skills() -> str:
    """Load all markdown skills defined under /hermes-config/skills or config/skills."""
    skills_dir = os.environ.get("SKILLS_DIR", "/hermes-config/skills")
    if not os.path.exists(skills_dir):
        skills_dir = "config/skills"
    if not os.path.exists(skills_dir):
        return ""

    skill_texts = []
    for root, _, files in os.walk(skills_dir):
        for file in files:
            if file.endswith(".md"):
                full_path = os.path.join(root, file)
                try:
                    with open(full_path, encoding="utf-8") as f:
                        skill_name = os.path.basename(os.path.dirname(full_path))
                        skill_texts.append(f"### SKILL: {skill_name}\n{f.read()}")
                except Exception as ex:
                    log.warning("Could not load skill %s: %s", full_path, ex)

    if not skill_texts:
        return ""
    return "\n\n## ACTIVE SKILLS & BEHAVIORAL PLAYBOOKS:\n" + "\n\n---\n\n".join(skill_texts)


async def execute_tool_call(
    func_name: str,
    args: dict[str, Any],
    default_sender: str,
    client: WahaClient | None = None,
) -> dict[str, Any]:
    """Execute local memory function and return structured result or error message."""
    log.info("Agent executing tool: %s with args: %s", func_name, args)
    try:
        if func_name == "add_task":
            title = args.get("title", "")
            due = args.get("due", "")
            assignee = args.get("assignee", default_sender)
            if not title:
                return {
                    "status": "error",
                    "error": "Judul task tidak boleh kosong.",
                    "help_needed": "Minta user menyebutkan nama task yang ingin dicatat.",
                }
            task = add_task(title=title, due=due, assignee=assignee)
            return {
                "status": "success",
                "task": task,
                "message": f"Task '{title}' berhasil disimpan dengan deadline '{due}' untuk {assignee}.",
            }

        elif func_name == "list_tasks":
            status = args.get("status", "pending")
            tasks = list_tasks(status=status)
            return {"status": "success", "count": len(tasks), "tasks": tasks}

        elif func_name == "complete_task":
            title = args.get("title", "")
            completed = complete_task(title)
            if completed:
                return {
                    "status": "success",
                    "task": completed,
                    "message": f"Task '{completed.get('title')}' berhasil ditandai selesai.",
                }
            return {
                "status": "not_found",
                "error": f"Tidak ditemukan task pending dengan nama '{title}'.",
            }

        elif func_name == "update_task":
            title = args.get("title", "")
            new_title = args.get("new_title")
            new_due = args.get("new_due")
            new_assignee = args.get("new_assignee")
            updated = update_task(
                title=title,
                new_title=new_title,
                new_due=new_due,
                new_assignee=new_assignee,
            )
            if updated:
                return {
                    "status": "success",
                    "task": updated,
                    "message": f"Task '{updated.get('title')}' berhasil diupdate (Assignee: {updated.get('assignee')}, Due: {updated.get('due')}).",
                }
            return {
                "status": "not_found",
                "error": f"Tidak ditemukan task dengan nama '{title}'.",
            }

        elif func_name == "delete_task":
            title = args.get("title", "")
            deleted = delete_task(title)
            if deleted:
                return {
                    "status": "success",
                    "message": f"Task dengan kata kunci '{title}' berhasil dihapus.",
                }
            return {
                "status": "not_found",
                "error": f"Tidak ditemukan task dengan nama '{title}'.",
                "help_needed": "Tanyakan judul task yang tepat kepada user.",
            }

        elif func_name == "add_person":
            name = args.get("name", "")
            phone = args.get("phone", "")
            role = args.get("role", "")
            notes = args.get("notes", "")
            person = add_person(name=name, phone=phone, role=role, notes=notes)
            return {
                "status": "success",
                "person": person,
                "message": f"Kontak '{name}' berhasil disimpan.",
            }

        elif func_name == "get_person":
            name = args.get("name", "")
            found_person = get_person(name)
            if found_person:
                return {"status": "success", "person": found_person}
            return {
                "status": "not_found",
                "error": f"Kontak '{name}' belum ada di direktori.",
                "help_needed": "Tanyakan detail kontak baru kepada user jika ingin disimpan.",
            }

        elif func_name == "save_note":
            title = args.get("title", "")
            content = args.get("content", "")
            note = save_note(title=title, content=content)
            return {
                "status": "success",
                "note": note,
                "message": f"Catatan '{title}' berhasil disimpan.",
            }

        elif func_name == "remember_fact":
            fact = str(args.get("fact", "")).strip()
            user_id = str(args.get("user_id") or default_sender).strip()
            if not fact:
                return {"status": "error", "error": "Fakta/preferensi tidak boleh kosong."}
            from . import semantic_memory

            saved = await semantic_memory.add_memory(fact=fact, user_id=user_id)
            return {
                "status": "success",
                "saved_fact": saved,
                "message": f"Fakta/preferensi '{fact}' untuk {user_id} berhasil diingat ke memori jangka panjang.",
            }

        elif func_name == "recall_memory":
            query = str(args.get("query", "")).strip()
            if not query:
                return {"status": "error", "error": "Query pencarian memori tidak boleh kosong."}
            from . import semantic_memory

            results = await semantic_memory.search_memories(
                query=query, user_id=default_sender, top_k=5
            )
            return {"status": "success", "count": len(results), "results": results}

        elif func_name == "search_memory":
            keyword = args.get("keyword") or args.get("query", "")
            mem_results = search_memory(str(keyword))
            return {"status": "success", "results": mem_results}

        elif func_name == "send_whatsapp_message":
            recipient = str(args.get("recipient", "")).strip()
            text = str(args.get("text", "")).strip()
            if not text:
                return {"status": "error", "error": "Teks pesan tidak boleh kosong."}
            if not client:
                return {"status": "error", "error": "WAHA client tidak tersedia."}

            gilang_phone = (
                os.environ.get("GILANG_PHONE", "6281932062070")
                .replace("+", "")
                .replace(" ", "")
                .replace("-", "")
            )
            bunga_phone = (
                os.environ.get("BUNGA_PHONE", "6281398971445")
                .replace("+", "")
                .replace(" ", "")
                .replace("-", "")
            )
            trio_group = os.environ.get("TRIO_GROUP_JID", "120363411261097957@g.us")

            target_jid: str
            if "gilang" in recipient.lower():
                target_jid = f"{gilang_phone}@c.us"
            elif "bunga" in recipient.lower():
                target_jid = f"{bunga_phone}@c.us"
            elif "group" in recipient.lower() or "trio" in recipient.lower():
                target_jid = trio_group
            else:
                clean = recipient.replace("+", "").replace(" ", "").replace("-", "")
                target_jid = f"{clean}@c.us"

            quote_id = args.get("quote_message_id")
            if quote_id:
                quote_id = str(quote_id).strip()

            await client.send_message(chat_id=target_jid, text=text, reply_to_message_id=quote_id)
            from .memory import log_activity

            log_activity(f'Direct message sent to {recipient} ({target_jid}): "{text}"')

            log.info(
                "Agent sent direct WhatsApp message to %s (quote: %s): %s",
                target_jid,
                quote_id,
                text[:40],
            )
            return {
                "status": "success",
                "message": f"Pesan WhatsApp berhasil dikirim ke {recipient}.",
            }

        elif func_name == "get_whatsapp_messages":
            target = str(args.get("target", "")).strip()
            limit = int(args.get("limit") or 20)
            date_filter = str(args.get("date", "")).strip().lower() if args.get("date") else None
            since_hours_ago = (
                int(args["since_hours_ago"]) if args.get("since_hours_ago") is not None else None
            )

            if not client:
                return {"status": "error", "error": "WAHA client tidak tersedia."}

            gilang_phone = (
                os.environ.get("GILANG_PHONE", "6281932062070")
                .replace("+", "")
                .replace(" ", "")
                .replace("-", "")
            )
            bunga_phone = (
                os.environ.get("BUNGA_PHONE", "6281398971445")
                .replace("+", "")
                .replace(" ", "")
                .replace("-", "")
            )
            trio_group = os.environ.get("TRIO_GROUP_JID", "120363411261097957@g.us")

            if "gilang" in target.lower():
                target_jid = f"{gilang_phone}@c.us"
            elif "bunga" in target.lower():
                target_jid = f"{bunga_phone}@c.us"
            elif "group" in target.lower() or "trio" in target.lower():
                target_jid = trio_group
            else:
                clean = target.replace("+", "").replace(" ", "").replace("-", "")
                target_jid = f"{clean}@c.us"

            # Calculate timestamp bounds for date range filtering
            tz = ZoneInfo(os.environ.get("TZ", "Asia/Jakarta"))
            now_dt = datetime.now(tz)
            min_ts: float | None = None
            max_ts: float | None = None

            if since_hours_ago:
                min_ts = (now_dt - timedelta(hours=since_hours_ago)).timestamp()
            elif date_filter:
                if date_filter in ("today", "hari ini"):
                    target_day = now_dt.date()
                elif date_filter in ("yesterday", "kemarin"):
                    target_day = (now_dt - timedelta(days=1)).date()
                else:
                    try:
                        target_day = datetime.strptime(date_filter, "%Y-%m-%d").date()
                    except Exception:
                        target_day = None

                if target_day:
                    start_dt = datetime(
                        target_day.year, target_day.month, target_day.day, 0, 0, 0, tzinfo=tz
                    )
                    end_dt = datetime(
                        target_day.year,
                        target_day.month,
                        target_day.day,
                        23,
                        59,
                        59,
                        tzinfo=tz,
                    )
                    min_ts = start_dt.timestamp()
                    max_ts = end_dt.timestamp()

            fetch_limit = max(min(limit * 2 if (min_ts or max_ts) else limit, 50), 10)
            msgs = await client.get_messages(chat_id=target_jid, limit=fetch_limit)

            formatted_msgs = []
            for m in msgs:
                ts = m.timestamp
                if min_ts and ts < min_ts:
                    continue
                if max_ts and ts > max_ts:
                    continue
                msg_time_str = (
                    datetime.fromtimestamp(ts, tz).strftime("%Y-%m-%d %H:%M WIB")
                    if ts > 0
                    else "Unknown"
                )
                formatted_msgs.append(
                    {
                        "sender": m.sender_phone,
                        "text": m.text,
                        "time": msg_time_str,
                        "timestamp": ts,
                    }
                )
            return {
                "status": "success",
                "target": target,
                "chat_id": target_jid,
                "filter_applied": {"date": date_filter, "since_hours_ago": since_hours_ago},
                "count": len(formatted_msgs),
                "messages": formatted_msgs[:limit],
            }

        return {"status": "error", "error": f"Tool '{func_name}' tidak dikenal."}

    except Exception as e:
        log.error("Tool execution failed for %s: %s", func_name, e)
        return {
            "status": "error",
            "error": str(e),
            "help_needed": "Ada kendala teknis saat menjalankan tool. Beritahu user apa kendalanya dan minta konfirmasi ulang.",
        }


async def run_agentic_react_loop(
    client: WahaClient,
    sender_name: str,
    chat_id: str,
    message_text: str,
    media_data: dict[str, str] | None = None,
    max_steps: int = 5,
) -> str | None:
    """
    Run multi-step ReAct agent loop:
    1. Agent reasons over text & multimodal inputs (audio voice notes, images, PDFs)
    2. Executes tools in Python and verifies results on disk
    3. Feeds tool responses back into the conversation turn
    4. Synthesizes concise final response with verified outcomes
    """
    system_prompt = load_system_prompt()
    skills_context = load_all_skills()
    memory_context = get_memory_context_summary()

    # Semantically retrieve personal memories/facts related to current conversation
    from . import semantic_memory

    relevant_memories = await semantic_memory.search_memories(
        query=message_text,
        user_id=sender_name,
        top_k=5,
        min_score=0.62,
    )
    semantic_context = ""
    if relevant_memories:
        fact_lines = [f"- {m['fact']}" for m in relevant_memories if m.get("fact")]
        if fact_lines:
            semantic_context = (
                "### RELEVANT PERSONAL PREFERENCES & LONG-TERM MEMORY:\n"
                + "\n".join(fact_lines)
                + "\n\n"
            )

    full_system_instruction = (
        f"{system_prompt}\n\n{skills_context}\n\n{memory_context}\n\n{semantic_context}"
        f"### CORE OPERATIONAL DIRECTIVES:\n"
        f"1. IDENTITY & TONE:\n"
        f"   - You are Helmis, an executive personal assistant for Gilang and Bunga.\n"
        f"   - Communicate concisely and directly in 1-2 natural sentences.\n"
        f"   - Never use emojis anywhere in your output.\n"
        f"   - Never append boilerplate pleasantries or repetitive closing questions.\n"
        f"   - Format with single asterisks *bold* for emphasis, and standard clean lists.\n\n"
        f"2. CONVERSATIONAL INTENT & SILENCE COMPLIANCE:\n"
        f"   - Respond promptly, naturally, and helpfully to the user.\n"
        f"   - If the user's intent is to dismiss you, request silence, or test silence, obey completely by outputting ONLY '[NO_REPLY]'. Do not send a message confirming silence.\n\n"
        f"3. FACT GROUNDING & ZERO ASSUMPTION:\n"
        f"   - Never assume whether messages, reminders, or tasks exist or were dispatched. Check memory context and tools before stating facts.\n"
        f"   - To verify actual WhatsApp history or sent messages, invoke 'get_whatsapp_messages'.\n"
        f"   - Only state facts confirmed by tool results or memory records.\n\n"
        f"4. TASK & REMINDER LOGIC:\n"
        f"   - When a user asks to be reminded to do an action towards another person, the assignee is the user requesting the reminder.\n"
        f"   - When a user asks to remind another person, the assignee is the other person.\n"
        f"   - When updating or reassigning an existing task, always use 'update_task' rather than creating duplicates with 'add_task'.\n"
        f"   - When a task is reported completed, invoke 'complete_task'.\n\n"
        f"5. MULTIMODAL INPUTS:\n"
        f"   - Audio / Voice Notes: Transcribe and understand spoken audio, executing any requested commands.\n"
        f"   - Images & Documents: Accurately read screenshots, documents, receipts, and PDFs.\n\n"
        f"6. ERROR TRANSPARENCY:\n"
        f"   - If a tool encounters an error, state clearly what happened and ask for clarification.\n"
    )

    # Fetch recent chat history from WAHA
    history: list[Any] = []
    try:
        history = await client.get_messages(chat_id=chat_id, limit=12)
    except Exception as e:
        log.warning("Could not fetch chat history for %s: %s", chat_id, e)

    effective_text = message_text or (
        "Tolong proses dan tanggapi pesan media ini (voice note / gambar / dokumen)."
        if media_data
        else ""
    )
    contents = build_multi_turn_contents(history, sender_name, effective_text)

    # Attach media inlineData to current turn if present
    if media_data and contents:
        contents[-1]["parts"].insert(0, {"inlineData": media_data})

    for step in range(max_steps):
        log.info("Running Agentic ReAct step %d/%d for [%s]...", step + 1, max_steps, sender_name)
        payload = {
            "systemInstruction": {"parts": [{"text": full_system_instruction}]},
            "contents": contents,
            "tools": GEMINI_TOOLS,
            "generationConfig": {"temperature": 0.1, "maxOutputTokens": 350},
        }

        # Attempt call with Multi-Model & Multi-Key Cascade
        response_data: dict[str, Any] | None = None
        for model in GEMINI_MODELS:
            for _ in range(len(GEMINI_KEYS) or 1):
                api_key = get_next_gemini_key()
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
                try:
                    async with httpx.AsyncClient(timeout=25.0) as http_client:
                        resp = await http_client.post(url, json=payload)
                        if resp.status_code == 200:
                            response_data = resp.json()
                            break
                        elif resp.status_code == 429:
                            log.warning("Model %s / key rate-limited (429), rotating key...", model)
                            continue
                        elif resp.status_code == 404:
                            log.warning("Model %s not found (404), trying next model...", model)
                            break
                        else:
                            log.error(
                                "Gemini %s error %d on key: %s, rotating key...",
                                model,
                                resp.status_code,
                                resp.text[:100],
                            )
                            continue
                except Exception as ex:
                    log.error("Gemini HTTP exception for %s: %s, rotating key...", model, ex)
                    continue

            if response_data:
                break

        if not response_data:
            return "Maaf, Helmis sedang mengalami gangguan koneksi ke AI provider. Mohon coba sesaat lagi ya."

        candidates = response_data.get("candidates", [])
        if not candidates:
            return "Maaf, tidak ada respon dari model AI."

        candidate_part = candidates[0].get("content", {}).get("parts", [{}])[0]

        # Case A: Model wants to invoke a tool
        if "functionCall" in candidate_part:
            fc = candidate_part["functionCall"]
            func_name = str(fc.get("name", ""))
            func_args = dict(fc.get("args", {}))
            log.info("Agent selected tool call: %s(%s)", func_name, func_args)

            # Execute tool locally
            tool_result = await execute_tool_call(func_name, func_args, sender_name, client=client)

            # Append model functionCall turn (preserving thoughtSignature) and functionResponse turn
            contents.append({"role": "model", "parts": [candidate_part]})
            contents.append(
                {
                    "role": "user",
                    "parts": [
                        {
                            "functionResponse": {
                                "name": func_name,
                                "response": {"output": tool_result},
                            }
                        }
                    ],
                }
            )
            continue

        # Case B: Model generated final text output
        text = candidate_part.get("text", "")
        if isinstance(text, str) and text.strip():
            cleaned = text.strip()
            if cleaned in ("[NO_REPLY]", "NO_REPLY", "None"):
                log.info("Agent decided no reply is needed for this turn.")
                return None
            log.info("Agent finalized response in %d steps: %s", step + 1, cleaned[:60])
            return cleaned

    log.info("Agent finished execution steps silently without emitting chat message.")
    return None
