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
    get_cascade_models_with_cooldown,
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


async def _attempt_model(
    model: str,
    payload: dict[str, Any],
    *,
    timeout_secs: float,
    keys_count: int,
) -> tuple[str, dict[str, Any]] | None:
    """Try one model across all keys (sequential rotation).

    Returns (model, response JSON) on success, None on exhaustion; marks
    cooldowns on model-level failures (timeout, 404, 503 on every key).
    """
    overload_503_count = 0
    for _ in range(keys_count):
        api_key = get_next_gemini_key()
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
        try:
            async with httpx.AsyncClient(timeout=timeout_secs) as http_client:
                resp = await http_client.post(url, json=payload)
                if resp.status_code == 200:
                    return model, resp.json()
                elif resp.status_code == 429:
                    log.warning("Rate limit (429) on %s with key %s..., rotating", model, api_key[:8])
                    continue
                elif resp.status_code == 503:
                    log.warning("Model overloaded (503) on %s with key %s..., rotating", model, api_key[:8])
                    overload_503_count += 1
                    continue
                elif resp.status_code == 404:
                    log.warning("Model not found (404) on %s, skipping", model)
                    cascade.mark_model_unavailable(model)
                    return None
                else:
                    log.error("Gemini API error (%d) on %s: %s", resp.status_code, model, resp.text[:400])
                    continue
        except Exception as ex:
            # Timeout/connection refused is a model-level failure:
            # never re-try the same model on another key.
            log.warning("Timeout or connection error on %s: %s — next model", model, ex)
            cascade.mark_model_unavailable(model)
            return None
    if overload_503_count >= keys_count:
        # Every key says the model itself is overloaded — skip it for
        # the rest of the turn window instead of re-probing per step.
        log.info("Model %s overloaded on all %d keys — cooldown engaged", model, keys_count)
        cascade.mark_model_unavailable(model)
    return None


async def _hedged_cascade_call(
    active_candidates: list[str],
    payload: dict[str, Any],
    *,
    timeout_secs: float,
    keys_count: int,
) -> tuple[str, dict[str, Any]] | None:
    """Hedged racing over the cascade.

    A single dead head model (hung 3.8-flash) used to tax every turn its full
    timeout (12s) before the healthy tail answered. The top 2 candidates race
    with a staggered start: if the head has not answered within half the turn
    timeout, the second model fires and the first 200-response wins; the
    loser is cancelled. Remaining candidates are walked sequentially.
    Returns (winning_model, response JSON), or None.
    """
    if not active_candidates:
        return None
    head, rest = active_candidates[0], active_candidates[1:]
    head_task = asyncio.create_task(
        _attempt_model(head, payload, timeout_secs=timeout_secs, keys_count=keys_count)
    )
    if not rest:
        return await head_task

    hedge_delay = timeout_secs / 2.0
    await asyncio.sleep(0)  # let the head request go out first
    done, _pending = await asyncio.wait({head_task}, timeout=hedge_delay)
    if head_task in done:
        head_result = head_task.result()
        if head_result:
            return head_result
        # Head exhausted fast (503/timeout/404) — walk the tail directly.
        for model in rest:
            result = await _attempt_model(model, payload, timeout_secs=timeout_secs, keys_count=keys_count)
            if result:
                return result
        return None

    # Head is slow: fire the hedge (second candidate) and take whoever
    # finishes first; cancel the loser.
    second = rest[0]
    tail = rest[1:]
    second_task = asyncio.create_task(
        _attempt_model(second, payload, timeout_secs=timeout_secs, keys_count=keys_count)
    )
    done2, _ = await asyncio.wait(
        {head_task, second_task}, return_when=asyncio.FIRST_COMPLETED
    )
    winner = None
    for t in done2:
        try:
            result = t.result()
        except Exception:
            result = None
        if result:
            winner = result
    for t in {head_task, second_task} - done2:
        t.cancel()
    if winner:
        return winner
    # Both lost — walk the remaining candidates sequentially.
    for model in tail:
        result = await _attempt_model(model, payload, timeout_secs=timeout_secs, keys_count=keys_count)
        if result:
            return result
    return None


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
    from .fastpath import classify_fastpath, run_fastpath

    # --- Fast path: trivial turns skip the full agent loop entirely ---
    # "halo" / "ada tugas apa" do not need the 9k-token manual, tools,
    # semantic search, or chat history. Classify + answer with one tiny
    # call, or fall through to the full loop on any doubt.
    if not media_data and len(message_text) <= 200:
        fast_kind = classify_fastpath(message_text)
        if fast_kind:
            candidate_models = get_cascade_models(is_video=False)
            keys_count = len(getattr(cascade, "GEMINI_KEYS", [])) or 1

            async def _plain_completion(payload: dict[str, Any]) -> str | None:
                """One plain generateContent call (no tools), hedged across
                the cascade. Returns text or None."""
                small_payload = dict(payload)
                small_payload.pop("tools", None)
                won = await _hedged_cascade_call(
                    candidate_models[:4],
                    small_payload,
                    timeout_secs=8.0,
                    keys_count=keys_count,
                )
                if not won:
                    return None
                _model, data = won
                cand = data.get("candidates", [])
                if not cand:
                    return None
                parts = cand[0].get("content", {}).get("parts", []) or []
                return "".join(p.get("text", "") for p in parts if isinstance(p.get("text"), str))

            try:
                fast_reply = await run_fastpath(
                    text=message_text,
                    kind=fast_kind,
                    sender_name=sender_name,
                    chat_completion_fn=_plain_completion,
                )
            except Exception as ex:
                log.warning("Fast path failed (%s) — falling back to full agent", ex)
                fast_reply = None
            if fast_reply is not None:
                if tracer:
                    tracer.log_step(step=1, max_steps=1, model_name="fastpath", final_text=fast_reply)
                log.info("Fast path '%s' served turn for [%s]", fast_kind, sender_name)
                return fast_reply
            log.info("Fast path '%s' declined — full agent loop for [%s]", fast_kind, sender_name)

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
    timeout_secs = 25.0 if is_video else 12.0
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

        # Attempt call with Multi-Model & Multi-Key Cascade, hedged.
        # Models that failed recently (503/timeout/404) are demoted so healthy
        # tail models are tried first instead of re-probing a dead head.
        active_candidates = get_cascade_models_with_cooldown(is_video=is_video)[:4]
        keys_count = len(getattr(cascade, "GEMINI_KEYS", [])) or 1
        won = await _hedged_cascade_call(
            active_candidates,
            payload,
            timeout_secs=timeout_secs,
            keys_count=keys_count,
        )
        if won:
            active_model, response_data = won

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
            # Rotate keys/models: the synthesis call must be at least as
            # reliable as the working turn that preceded it. Same hedged
            # racing as the main turn; cooldown-aware ordering skips models
            # that failed during this same turn.
            synthesis_keys = len(getattr(cascade, "GEMINI_KEYS", [])) or 1
            won = await _hedged_cascade_call(
                get_cascade_models_with_cooldown(is_video=is_video)[:4],
                payload,
                timeout_secs=timeout_secs,
                keys_count=synthesis_keys,
            )
            if won:
                _, synth_data = won
                cand = synth_data.get("candidates", [])
                if cand:
                    txt = cand[0].get("content", {}).get("parts", [{}])[0].get("text", "")
                    if txt and txt.strip():
                        return verify_action_fidelity(txt.strip(), executed_tools)
            # Honest degraded summary — never claim mutations that were not made.
            tool_counts: dict[str, int] = {}
            for t in executed_tools:
                if t.get("result", {}).get("status") == "success":
                    tool_counts[str(t.get("name"))] = tool_counts.get(str(t.get("name")), 0) + 1
            summary = ", ".join(f"{n}×{c}" for n, c in sorted(tool_counts.items()))
            return (
                f"Helmis selesai memproses ({summary}), tapi gagal menyusun rangkuman akhir. "
                "Coba tanya lagi untuk konfirmasi detailnya."
            )

    log.debug("Agent finished execution steps silently without emitting chat message.")
    return None
