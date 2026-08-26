"""
loop.py — Autonomous ReAct Agent Loop & Gemini LLM Orchestrator.
"""

import asyncio
import logging
from typing import Any

import httpx

from . import cascade
from .cascade import (
    GEMINI_KEYS,
    GEMINI_MODELS,
    fetch_available_gemini_models,
    get_cascade_models,
    get_next_gemini_key,
    load_all_skills,
    load_system_prompt,
)
from .guardrails import inject_tool_directive, verify_action_fidelity

log = logging.getLogger("helmis-agent")


async def drain_and_inject_mid_turn_mailbox(
    contents: list[dict[str, Any]],
    mailbox: asyncio.Queue[Any] | None,
    client: Any,
    sender_name: str,
    turn_state: dict[str, Any] | None = None,
) -> bool:
    """Drain all pending user messages from the active turn mailbox and inject as mid-turn steering."""
    if not mailbox or mailbox.empty():
        return False

    import sys
    transcribe_func = None
    if "src.agent" in sys.modules and hasattr(sys.modules["src.agent"], "transcribe_audio_base64"):
        transcribe_func = sys.modules["src.agent"].transcribe_audio_base64
    if not transcribe_func:
        from ..whatsapp.transcribe import transcribe_audio_base64
        transcribe_func = transcribe_audio_base64

    injected_texts: list[str] = []
    while not mailbox.empty():
        evt = mailbox.get_nowait()
        t = str(getattr(evt, "text", "") or "").strip()
        if getattr(evt, "has_media", False) and getattr(evt, "media_url", None):
            try:
                m_res = await client.download_media_base64(evt.media_url)
                if m_res:
                    m_mime, m_b64 = m_res
                    if m_mime.startswith("audio/"):
                        vn_t = await transcribe_func(m_b64, m_mime)
                        if vn_t:
                            t = f'{t} (Pesan Suara: "{vn_t}")' if t else f'Pesan Suara: "{vn_t}"'
                    else:
                        fn_label = getattr(evt, "media_filename", None) or m_mime
                        t = f'{t} [Lampiran Media: {fn_label}]' if t else f'[Lampiran Media: {fn_label}]'
            except Exception as e:
                log.warning("Could not download/transcribe mid-turn media: %s", e)

        if t:
            injected_texts.append(t)

    if not injected_texts:
        return False

    combined_injection = "\n".join(injected_texts)
    banner = f'[Pesan Tambahan dari {sender_name} saat kamu sedang memproses]: "{combined_injection}"'
    log.info("Mid-turn steering injected into active ReAct turn for [%s]: %s", sender_name, combined_injection[:60])

    if turn_state is not None:
        turn_state["has_mid_turn_update"] = True

    # Inject into contents adhering to Gemini API schema
    if contents and contents[-1].get("role") == "user":
        contents[-1]["parts"].append({"text": banner})
    else:
        contents.append({"role": "user", "parts": [{"text": banner}]})

    return True


async def run_agentic_react_loop(
    client: Any,
    sender_name: str,
    chat_id: str,
    message_text: str,
    media_data: dict[str, Any] | None = None,
    max_steps: int = 12,
    tracer: Any | None = None,
    turn_state: dict[str, Any] | None = None,
    mailbox: asyncio.Queue[Any] | None = None,
) -> str | None:
    """
    Run multi-step ReAct agent loop:
    1. Agent reasons over text & multimodal inputs (images, PDFs)
    2. Executes tools in Python and verifies results on disk
    3. Feeds tool responses back into the conversation turn
    4. Synthesizes concise final response with verified outcomes
    """
    from ..agent_tools import GEMINI_TOOLS, execute_tool_call
    from ..memory.semantic import search_memories
    from ..memory.store import get_memory_context_summary
    from ..whatsapp.history import build_multi_turn_contents

    system_prompt = load_system_prompt()
    skills_context = load_all_skills()
    memory_context = get_memory_context_summary()

    # Semantically retrieve personal memories/facts related to current conversation
    relevant_memories = await search_memories(
        query=message_text,
        user_id=sender_name,
        top_k=5,
        min_score=0.62,
    )
    semantic_context = ""
    if relevant_memories:
        fact_lines = [
            f"- [Recorded: {m.get('created_at', 'Past')}] {m['fact']}"
            for m in relevant_memories
            if m.get("fact")
        ]
        if fact_lines:
            semantic_context = (
                "### RELEVANT PERSONAL PREFERENCES & LONG-TERM MEMORY:\n"
                + "\n".join(fact_lines)
                + "\n\n"
            )

    full_system_instruction = (
        f"{system_prompt}\n\n{skills_context}\n\n{memory_context}\n\n{semantic_context}"
        f"### OPERATIONAL PRINCIPLES:\n"
        f"1. LINGUISTIC PERSONA & CASUAL WHATSAPP DYNAMICS (CRITICAL):\n"
        f"   - Adopt the persona of an agile, trusted personal secretary communicating in authentic modern Indonesian WhatsApp register ('sat-set', relaxed, direct).\n"
        f"   - Negative Style Constraints: Never use bureaucratic passive phrasing ('Berdasarkan data...', 'Berikut adalah...'), customer service pleasantries, or redundant repetition of entity titles.\n"
        f"   - Discourse Density: Casual banter, corrections, and acknowledgments must be exactly 1 natural, punchy sentence. Stop generating immediately when resolved.\n"
        f"   - Midnight Relative Framing: In the early morning window [00:00, 05:00) WIB, events on the same calendar date are strictly relative to 'hari ini / nanti sore', NEVER 'besok'.\n"
        f"   - Temporal Memory Supersession: When retrieved long-term memories contain conflicting past routines, schedules (e.g. old vs new semester classes), addresses, or preferences, ALWAYS prioritize the entry with the more recent '[Recorded: ...]' timestamp as active ground truth.\n"
        f"   - Conscious Multi-Bubble Messaging ('---'): You have full conscious control over WhatsApp bubbles. The system will ONLY split your response into separate bubbles if you place '---' on its own line.\n"
        f"   - Human WhatsApp Cadence: For casual banter, quick confirmations + proactive follow-ups, or shifts in thought, naturally use '---' to split into 2 short, punchy bubbles (e.g. 'Sip udah dicatet ya.\\n---\\nBtw nanti sore ada les jam 3, mau disiapin materinya?').\n"
        f"   - Atomic Structures in ONE Bubble: Class schedules, task lists, tables, document summaries, multi-day breakdowns, and code must NEVER contain '---'. Keep the entire list/schedule unified in 1 cohesive bubble.\n"
        f"   - WhatsApp Markdown & Visual Readability (Zero AI Slop): Never use cheesy AI greetings or robotic closings. Start directly with the title block (using '> *Title*') or answer. Use *bold* for key anchors (days, times, titles), _italics_ for secondary metadata (rooms, notes, status). Avoid markdown tables/hashes (#) which do not render in WhatsApp.\n"
        f"   - Absolute Zero Emoji constraint. Use single asterisks *bold* for emphasis.\n\n"
        f"2. GROUP DYNAMICS, CONVERSATIONAL CONNOTATIONS & SILENCE ([NO_REPLY]):\n"
        f"   - Group Context ('Trio Helmis'): Gilang and Bunga are in a relationship and constantly talk, ask questions, and banter directly with EACH OTHER.\n"
        f"   - Pronoun Awareness: 'km', 'kamu', 'lu', 'beb', 'sayang' from Gilang refers to Bunga; from Bunga it refers to Gilang. Never assume you are being addressed unless called by name ('Helmis', 'mis') or given an explicit secretary command.\n"
        f"   - Human-to-Human Non-Intervention: When users ask each other questions ('Anjay udh dimasukin jadwal km?'), answer each other ('udahhh'), quote each other (> [Gilang] or > [Bunga]), or exchange casual banter/reactions ('wkwk', 'cie'), DO NOT INTERRUPT. Output '[NO_REPLY]'.\n"
        f"   - Only reply in groups when: (1) Directly addressed ('Helmis', 'mis'), (2) Given a direct command/inquiry meant for secretary ('jadwal kuliah ak apa aja', 'catet tugas ini'), (3) Directly quoting a Helmis message with feedback/follow-up (> [Helmis]: ...).\n"
        f"   - Connotations: Colloquial banter ('Anjay...') expresses human reaction, NOT a bug report or complaint about your previous response. Never invent unprompted apologies or unasked advice.\n"
        f"   - Quoted / Replied messages: Prefix '> [Sender]: \"...\"' indicates who is being replied to. If a user asks what they quoted or asks about a quote, look ONLY at the '> [Sender]: ...' block in the current turn. If there is NO '> [Sender]:' block in the prompt, state truthfully: 'Tidak ada pesan atau media yang ter-quote pada pesan ini.' NEVER invent or hallucinate a quoted message!\n"
        f"   - Media (images, stickers, audio) are native context for conversation. Never generate unsolicited alt-text or visual descriptions.\n"
        f"   - If no reply is required or conversational intent is silence, output '[NO_REPLY]'.\n\n"
        f"3. ACTION & TOOL FIDELITY:\n"
        f"   - State mutations (tasks, notes, reminders, memories) must always be performed via their respective tools.\n"
        f"   - Always faithfully reflect tool results: if a tool reports 'not_found' or 0 items, state clearly that the item was not found.\n"
        f"   - Never claim an action succeeded unless its tool returned status 'success'.\n"
        f"   - Never invent or fabricate data. If a user refers to an unattached file, state that it has not been received.\n\n"
        f"4. TASK & ASSIGNMENT LOGIC:\n"
        f"   - Single-person tasks: When Gilang asks for a reminder for himself, assign to 'Gilang'. When asking to remind Bunga, assign to 'Bunga'.\n"
        f"   - Shared / Couple tasks: When a task involves both ('kita', 'kita berdua', 'bersama', 'shared', 'bareng', 'agenda kita'), assign to 'Both'. Shared task reminders will be dispatched to both partners or the Trio group chat.\n"
        f"   - Urgency-First Presentation: When listing tasks to the user, ALWAYS present them sorted by urgency (soonest deadline / overdue first) by default, unless the user explicitly requests otherwise (e.g. alphabetical or by creation date).\n"
        f"   - When listing tasks, if the user asks for all tasks or general tasks, list both individual and 'Both' shared tasks.\n"
        f"   - Use 'update_task' to modify existing tasks/reassign between 'Gilang', 'Bunga', or 'Both', and 'complete_task' when finished.\n\n"
        f"5. CONTEXTUAL THINKING & CROSS-PARTY COORDINATION:\n"
        f"   - When executing actions that resolve conflicts or involve complex breakdowns, naturally include your reasoning context in the final response (e.g. why a specific time was chosen or how costs were split).\n"
        f"   - Cross-Party Delegation: When a user asks you to inform, ask, or message the other partner (e.g. Gilang asks to notify Bunga), invoke 'send_whatsapp_message(recipient=\"Bunga\", ...)' mid-turn, and confirm to the sender in your final response.\n"
        f"   - Zero Spam on Fast Queries: For simple local lookups (checking tasks, notes, or memories), deliver the answer directly without intermediate status messages.\n\n"
        f"6. DOCUMENT VAULT & ZERO HALLUCINATION MANDATE:\n"
        f"   - When saving an uploaded document or file, ALWAYS PRESERVE the user's original uploaded filename (e.g. 'P2_Gilang Muhamad Widiagung_M0403241117_02.pdf'). Never invent synthetic slug filenames for named files.\n"
        f"   - Only generate descriptive slug filenames when the incoming file is an unnamed camera capture or generic media ('IMG-...', 'image.jpeg', 'document.pdf').\n"
        f"   - When asked what the original filename was, report 'original_filename' from the vault record accurately.\n"
        f"   - NEVER make up or guess file names, file contents, line items, numbers, or existence of files in the Document Vault.\n"
        f"   - To answer questions about stored files, ALWAYS execute 'read_vault_file(file_id_or_name=...)' or 'search_vault_files(query=...)' first.\n"
        f"   - If a file is not found, state honestly: 'File ... tidak ditemukan di brankas dokumen.' NEVER fabricate imaginary file contents.\n"
        f"   - Categorization: 'health' (BPJS, lab), 'id_cards' (KTP, SIM, Paspor), 'travel' (e-tickets), 'receipts' (invoices, transfer proofs), 'documents' (CV, contracts), 'media' (photos, videos), 'projects' (custom workspaces).\n"
        f"   - File Moves: Use 'move_vault_files(target=..., destination_directory=...)'. File Deletions: Use 'delete_vault_files(target=...)'.\n"
    )

    # Fetch recent chat history from WAHA
    history: list[Any] = []
    try:
        history = await client.get_messages(chat_id=chat_id, limit=12)
    except Exception as e:
        log.warning("Could not fetch chat history for %s: %s", chat_id, e)

    # Build clean multi-turn contents with native media data (no synthetic prompt strings)
    contents = build_multi_turn_contents(
        history_messages=history,
        sender_name=sender_name,
        current_text=message_text,
        media_data=media_data,
    )

    is_video = bool(media_data and media_data.get("mimeType", "").startswith("video/"))
    candidate_models = get_cascade_models(is_video=is_video)
    timeout_secs = 25.0 if is_video else 6.0
    executed_tools: list[dict[str, Any]] = []
    active_model = candidate_models[0] if candidate_models else "gemini-flash-lite-latest"

    step = 0
    total_steps = 0
    while step < max_steps and total_steps < 18:
        total_steps += 1
        log.debug("Running Agentic ReAct step %d (total %d/18) for [%s]...", step + 1, total_steps, sender_name)

        # Check for mid-turn user input before calling the model
        has_new_input = await drain_and_inject_mid_turn_mailbox(
            contents=contents,
            mailbox=mailbox,
            client=client,
            sender_name=sender_name,
            turn_state=turn_state,
        )
        if has_new_input:
            step = max(0, step - 3)

        payload = {
            "systemInstruction": {"parts": [{"text": full_system_instruction}]},
            "contents": contents,
            "tools": GEMINI_TOOLS,
            "generationConfig": {"temperature": 0.0, "maxOutputTokens": 2048},
        }

        # Attempt call with Multi-Model & Multi-Key Cascade
        response_data: dict[str, Any] | None = None
        active_candidates = candidate_models[:4]
        for model in active_candidates:
            keys_count = len(getattr(cascade, "GEMINI_KEYS", [])) or 1
            for _ in range(min(keys_count, 2)):
                api_key = get_next_gemini_key()
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
                try:
                    async with httpx.AsyncClient(timeout=timeout_secs) as http_client:
                        resp = await http_client.post(url, json=payload)
                        if resp.status_code == 200:
                            response_data = resp.json()
                            active_model = model
                            break
                        elif resp.status_code == 429:
                            log.warning("Rate limit (429) on %s with key %s..., rotating", model, api_key[:8])
                            continue
                        elif resp.status_code == 404:
                            break
                        else:
                            continue
                except Exception as ex:
                    log.warning("Timeout or connection error on %s: %s", model, ex)
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
            log.debug("Agent selected tool call: %s(%s)", func_name, func_args)

            # Update real-time turn state for dynamic watchdog status
            if turn_state is not None:
                turn_state["current_tool"] = func_name
                turn_state["tool_args"] = func_args

            # Execute tool locally
            tool_result = await execute_tool_call(
                func_name, func_args, sender_name, client=client, media_data=media_data
            )
            executed_tools.append({"name": func_name, "args": func_args, "result": tool_result})

            if turn_state is not None:
                if func_name in ("send_vault_file", "send_whatsapp_media", "send_whatsapp_message") and tool_result.get("status") == "success":
                    turn_state["dispatched_items"] = turn_state.get("dispatched_items", 0) + 1
                turn_state["last_completed_tool"] = func_name

            if tracer:
                tracer.log_step(
                    step=step + 1,
                    max_steps=max_steps,
                    model_name=active_model,
                    tool_call={"name": func_name, "args": func_args},
                    tool_result=tool_result,
                )

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

            # Check mailbox immediately after tool execution
            has_tool_input = await drain_and_inject_mid_turn_mailbox(
                contents=contents,
                mailbox=mailbox,
                client=client,
                sender_name=sender_name,
                turn_state=turn_state,
            )
            if has_tool_input:
                step = max(0, step - 3)

            step += 1
            continue

        # Case B: Model generated final text output
        text = candidate_part.get("text", "")
        if isinstance(text, str) and text.strip():
            raw_cleaned = text.strip()
            for prefix in ("[Helmis]:", "[Helmis]: ", "[Gilang]:", "[Gilang]: ", "[Bunga]:", "[Bunga]: "):
                if raw_cleaned.startswith(prefix):
                    raw_cleaned = raw_cleaned[len(prefix):].strip()
            cleaned = verify_action_fidelity(raw_cleaned, executed_tools)
            if tracer:
                tracer.log_step(
                    step=step + 1,
                    max_steps=max_steps,
                    model_name=active_model,
                    final_text=cleaned,
                )
            if cleaned in ("[NO_REPLY]", "NO_REPLY", "None"):
                log.debug("Agent decided no reply is needed for this turn.")
                return None
            log.debug("Agent finalized response in %d steps: %s", step + 1, cleaned[:60])
            return cleaned

    # If loop finished after executing tools without emitting final text, synthesize clean confirmation
    if executed_tools:
        success_tools = [t for t in executed_tools if t.get("result", {}).get("status") == "success"]
        if success_tools:
            contents.append({
                "role": "user",
                "parts": [{"text": "Beri konfirmasi santai dalam 1-2 kalimat bahwa tindakan di atas sudah selesai dilakukan."}]
            })
            payload = {
                "systemInstruction": {"parts": [{"text": full_system_instruction}]},
                "contents": contents,
                "generationConfig": {"temperature": 0.0, "maxOutputTokens": 256},
            }
            try:
                api_key = get_next_gemini_key()
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{active_model}:generateContent?key={api_key}"
                async with httpx.AsyncClient(timeout=5.0) as http_client:
                    resp = await http_client.post(url, json=payload)
                    if resp.status_code == 200:
                        data = resp.json()
                        cand = data.get("candidates", [])
                        if cand:
                            txt = cand[0].get("content", {}).get("parts", [{}])[0].get("text", "")
                            if txt and txt.strip():
                                return verify_action_fidelity(txt.strip(), executed_tools)
            except Exception as ex:
                log.warning("Final synthesis error: %s", ex)
            return f"Sip, {len(success_tools)} tindakan berhasil diproses."

    log.debug("Agent finished execution steps silently without emitting chat message.")
    return None
