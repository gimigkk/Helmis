"""
agent.py — Autonomous ReAct Agent Loop & Gemini LLM Orchestrator.
"""

import logging
from typing import Any

import httpx

from .agent_tools import GEMINI_TOOLS, execute_tool_call
from .cascade import (
    GEMINI_KEYS,
    GEMINI_MODELS,
    fetch_available_gemini_models,
    get_next_gemini_key,
    load_all_skills,
    load_system_prompt,
)
from .client import WahaClient
from .guardrails import inject_tool_directive, verify_action_fidelity
from .history import build_multi_turn_contents
from .memory import get_memory_context_summary
from .transcribe import transcribe_audio_base64

# Re-export for public API and test suite backwards compatibility
__all__ = [
    "GEMINI_KEYS",
    "GEMINI_MODELS",
    "GEMINI_TOOLS",
    "execute_tool_call",
    "fetch_available_gemini_models",
    "get_next_gemini_key",
    "inject_tool_directive",
    "load_all_skills",
    "load_system_prompt",
    "run_agentic_react_loop",
    "transcribe_audio_base64",
    "verify_action_fidelity",
]

log = logging.getLogger("helmis-agent")


async def run_agentic_react_loop(
    client: WahaClient,
    sender_name: str,
    chat_id: str,
    message_text: str,
    media_data: dict[str, str] | None = None,
    max_steps: int = 5,
    tracer: Any | None = None,
) -> str | None:
    """
    Run multi-step ReAct agent loop:
    1. Agent reasons over text & multimodal inputs (images, PDFs)
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
        f"### OPERATIONAL PRINCIPLES:\n"
        f"1. ROLE & TONE:\n"
        f"   - You are Helmis, an executive personal assistant for Gilang and Bunga.\n"
        f"   - Communicate concisely, sharply, and directly in 1-2 natural sentences.\n"
        f"   - Do not use emojis in your responses. Keep formatting clean using standard WhatsApp markdown (*bold* for emphasis).\n"
        f"   - Do not add boilerplate pleasantries, repetitive greetings, or generic closing questions.\n\n"
        f"2. MULTIMODAL, QUOTES & CONVERSATIONAL DYNAMICS:\n"
        f"   - Quoted / Replied messages are prefixed with '> [Sender]: \"...\"'. When responding to a quote, address the content of that quoted message directly.\n"
        f"   - If a user asks what they quoted or asks about a quote, look ONLY at the '> [Sender]: ...' block in the current turn. If there is NO '> [Sender]:' block in the prompt, state truthfully: 'Tidak ada pesan atau media yang ter-quote pada pesan ini.' NEVER invent or hallucinate a quoted message!\n"
        f"   - Media (images, stickers, audio) are native context for conversation.\n"
        f"   - Never generate unsolicited alt-text or visual descriptions (do not describe stickers, memes, or casual photos).\n"
        f"   - Treat stickers and reaction images as emotional and conversational cues.\n"
        f"   - For receipts, invoices, documents, or schedules, extract and act on the actionable data directly.\n"
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
        f"   - Zero Spam on Fast Queries: For simple local lookups (checking tasks, notes, or memories), deliver the answer directly without intermediate status messages.\n"
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

    executed_tools: list[dict[str, Any]] = []

    for step in range(max_steps):
        log.debug("Running Agentic ReAct step %d/%d for [%s]...", step + 1, max_steps, sender_name)
        payload = {
            "systemInstruction": {"parts": [{"text": full_system_instruction}]},
            "contents": contents,
            "tools": GEMINI_TOOLS,
            "generationConfig": {"temperature": 0.0, "maxOutputTokens": 350},
        }

        # Attempt call with Multi-Model & Multi-Key Cascade
        response_data: dict[str, Any] | None = None
        active_model = GEMINI_MODELS[0] if GEMINI_MODELS else "gemini-flash-lite-latest"
        for model in GEMINI_MODELS:
            for _ in range(len(GEMINI_KEYS) or 1):
                api_key = get_next_gemini_key()
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
                try:
                    async with httpx.AsyncClient(timeout=5.0) as http_client:
                        resp = await http_client.post(url, json=payload)
                        if resp.status_code == 200:
                            response_data = resp.json()
                            active_model = model
                            break
                        elif resp.status_code == 429:
                            continue
                        elif resp.status_code == 404:
                            break
                        else:
                            continue
                except Exception:
                    # Timeout or connection error on this key, rotate immediately
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

            # Execute tool locally
            tool_result = await execute_tool_call(func_name, func_args, sender_name, client=client)
            executed_tools.append({"name": func_name, "args": func_args, "result": tool_result})

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
            continue

        # Case B: Model generated final text output
        text = candidate_part.get("text", "")
        if isinstance(text, str) and text.strip():
            raw_cleaned = text.strip()
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

    log.debug("Agent finished execution steps silently without emitting chat message.")
    return None
