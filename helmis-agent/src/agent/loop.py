"""
loop.py — Autonomous ReAct Agent Loop & Gemini LLM Orchestrator.
"""

import asyncio
import logging
from typing import Any

import httpx

from . import cascade
from .cascade import (
    get_cascade_models,
    get_next_gemini_key,
    load_all_skills,
    load_system_prompt,
)
from .crystallize import auto_crystallize_turn
from .guardrails import (
    detect_unexecuted_mutation_claims,
    is_no_fluff_request,
    verify_action_fidelity,
)
from .intent import (
    build_turn_plan,
    plan_system_directive,
    resolve_task_entities,
    should_force_tools,
)

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
    inline_media_parts: list[dict[str, Any]] = []

    while not mailbox.empty():
        evt = mailbox.get_nowait()
        t = str(getattr(evt, "text", "") or "").strip()
        if getattr(evt, "has_media", False) and getattr(evt, "media_url", None):
            try:
                m_res = await client.download_media_base64(evt.media_url)
                if m_res:
                    m_mime, m_b64 = m_res
                    fn_label = getattr(evt, "media_filename", None) or m_mime
                    new_media_data = {
                        "mimeType": m_mime,
                        "data": m_b64,
                        "filename": fn_label,
                    }
                    if turn_state is not None:
                        turn_state["media_data"] = new_media_data

                    if m_mime.startswith("audio/"):
                        vn_t = await transcribe_func(m_b64, m_mime)
                        if vn_t:
                            t = f'{t} (Pesan Suara: "{vn_t}")' if t else f'Pesan Suara: "{vn_t}"'
                    else:
                        t = f'{t} [Lampiran Media: {fn_label}]' if t else f'[Lampiran Media: {fn_label}]'
                        # For images and PDFs, provide native inlineData part directly to Gemini
                        if m_mime.startswith("image/") or m_mime == "application/pdf":
                            inline_media_parts.append({
                                "inlineData": {
                                    "mimeType": m_mime,
                                    "data": m_b64,
                                }
                            })
            except Exception as e:
                log.warning("Could not download/transcribe mid-turn media: %s", e)

        if t:
            injected_texts.append(t)

    if not injected_texts and not inline_media_parts:
        return False

    combined_injection = "\n".join(injected_texts) if injected_texts else "[Lampiran Media Baru]"
    banner = f'[Pesan Tambahan dari {sender_name} saat kamu sedang memproses]: "{combined_injection}"'
    log.info("Mid-turn steering injected into active ReAct turn for [%s]: %s", sender_name, combined_injection[:60])

    if turn_state is not None:
        turn_state["has_mid_turn_update"] = True

    # Inject banner text and any native inlineData parts into contents adhering to Gemini API schema
    new_parts: list[dict[str, Any]] = [{"text": banner}]
    new_parts.extend(inline_media_parts)

    if contents and contents[-1].get("role") == "user":
        contents[-1]["parts"].extend(new_parts)
    else:
        contents.append({"role": "user", "parts": new_parts})

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
    from ..memory.semantic import search_memories
    from ..memory.store import get_memory_context_summary
    from ..tools import GEMINI_TOOLS, execute_tool_call
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
        f"{system_prompt}\n\n{skills_context}\n\n{memory_context}\n\n{semantic_context}".strip()
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

    # Typed intent/action plan: classify, resolve entities, gate side effects
    turn_plan = build_turn_plan(message_text)
    no_fluff = is_no_fluff_request(message_text)
    log.debug(
        "Turn plan for [%s]: intent=%s domain=%s action=%s destructive=%s confirm=%s (no_fluff=%s)",
        sender_name,
        turn_plan.intent,
        turn_plan.domain,
        turn_plan.action_type,
        turn_plan.destructive,
        turn_plan.requires_confirmation,
        no_fluff,
    )
    if turn_plan.intent == "action":
        turn_plan = resolve_task_entities(turn_plan)
    plan_directive = plan_system_directive(turn_plan)
    if plan_directive:
        full_system_instruction = f"{full_system_instruction}\n\n{plan_directive}"

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
            # Re-plan on mid-turn steering (user may have changed direction)
            last_user_parts = [p.get("text", "") for c in contents if c.get("role") == "user" for p in c.get("parts", []) if "text" in p]
            if last_user_parts:
                turn_plan = build_turn_plan(last_user_parts[-1])
                if turn_plan.intent == "action":
                    turn_plan = resolve_task_entities(turn_plan)

        payload: dict[str, Any] = {
            "systemInstruction": {"parts": [{"text": full_system_instruction}]},
            "contents": contents,
            "tools": GEMINI_TOOLS,
            "generationConfig": {"temperature": 0.0, "maxOutputTokens": 2048},
        }

        # Forced Tool Calling: On first step with unambiguous action plan, force model
        # to emit functionCall. After step 0, revert to AUTO for final text synthesis.
        if step == 0 and should_force_tools(turn_plan):
            payload["toolConfig"] = {
                "functionCallingConfig": {"mode": "ANY"}
            }
            log.debug("Forced tool calling (mode=ANY) for action intent on step 0")

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
                            log.warning("Model not found (404) on %s, skipping", model)
                            break
                        else:
                            log.error("Gemini API error (%d) on %s: %s", resp.status_code, model, resp.text[:400])
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

        parts: list[dict[str, Any]] = candidates[0].get("content", {}).get("parts", []) or []

        # Case A: Model wants to invoke one or more tools (parallel function calls)
        function_call_parts = [p for p in parts if "functionCall" in p]
        text_parts = [p for p in parts if isinstance(p.get("text"), str) and p["text"].strip()]

        if function_call_parts:
            # Preserve the full model turn (all parts, including any interleaved text
            # and thoughtSignature) before appending function responses.
            contents.append({"role": "model", "parts": parts})

            responses: list[dict[str, Any]] = []
            for call_part in function_call_parts:
                fc = call_part["functionCall"]
                func_name = str(fc.get("name", ""))
                func_args = dict(fc.get("args", {}))
                log.debug("Agent selected tool call: %s(%s)", func_name, func_args)

                # Update real-time turn state for dynamic watchdog status
                if turn_state is not None:
                    turn_state["current_tool"] = func_name
                    turn_state["tool_args"] = func_args

                # Execute tool locally with dynamically synchronized media_data
                current_exec_media = (turn_state.get("media_data") if turn_state else None) or media_data
                tool_result = await execute_tool_call(
                    func_name, func_args, sender_name, client=client, media_data=current_exec_media, chat_id=chat_id
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

                responses.append(
                    {
                        "functionResponse": {
                            "name": func_name,
                            "response": {"output": tool_result},
                        }
                    }
                )

            contents.append({"role": "user", "parts": responses})

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

        # Case B: Model generated final text output (collect text across all text parts)
        text = "".join(p.get("text", "") for p in text_parts)
        if isinstance(text, str) and text.strip():
            raw_cleaned = text.strip()
            for prefix in ("[Helmis]:", "[Helmis]: ", "[Gilang]:", "[Gilang]: ", "[Bunga]:", "[Bunga]: "):
                if raw_cleaned.startswith(prefix):
                    raw_cleaned = raw_cleaned[len(prefix):].strip()

            # Anti-Hallucination Guardrail: Intercept unexecuted mutation claims before returning text
            unexecuted_claim = detect_unexecuted_mutation_claims(raw_cleaned, executed_tools)
            if unexecuted_claim and step < max_steps - 1:
                log.warning(
                    "Turn Intercepted: Model emitted unexecuted mutation claim '%s' on step %d without calling tool. Steering to functionCall...",
                    unexecuted_claim,
                    step + 1,
                )
                contents.append({"role": "model", "parts": parts})
                contents.append({
                    "role": "user",
                    "parts": [
                        {
                            "text": (
                                f"SYSTEM INTEGRITY FAULT: Kamu baru saja mengklaim telah melakukan tindakan '{unexecuted_claim}', "
                                "tetapi kamu BELUM mengeksekusi functionCall ke tool terkait! "
                                "Dilarang membuat konfirmasi teks sebelum tool berhasil dijalankan. "
                                "Kamu WAJIB mengeksekusi functionCall ke tool yang tepat sekarang."
                            )
                        }
                    ],
                })
                step += 1
                continue

            cleaned = verify_action_fidelity(raw_cleaned, executed_tools, no_fluff=no_fluff)
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

            # Autonomous Auto-Crystallization: Spawn background reflection worker for novel multi-tool workflows
            if executed_tools:
                try:
                    asyncio.create_task(
                        auto_crystallize_turn(
                            sender_name=sender_name,
                            user_message=message_text,
                            executed_tools=executed_tools,
                            final_response=cleaned,
                        )
                    )
                except Exception as ex:
                    log.debug("Could not spawn background auto-crystallization: %s", ex)

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
