"""
guardrails.py — State Fidelity Guardrails and Tool Footnote Formatting for Helmis.
"""

import logging
from typing import Any

log = logging.getLogger("helmis-guardrails")


def inject_tool_directive(result: dict[str, Any], func_name: str) -> dict[str, Any]:
    """Inject unambiguous strict honesty directives into tool outputs returned to Gemini."""
    status = result.get("status")
    if status == "not_found":
        result["_model_directive"] = (
            f"CRITICAL HONESTY: Item for '{func_name}' was NOT found. You MUST explicitly tell the user that the data/memory does not exist or was never stored in the database. DO NOT pretend or claim that you found, deleted, or updated it!"
        )
    elif status == "error":
        err_detail = result.get("error", "Failed")
        result["_model_directive"] = (
            f"CRITICAL HONESTY: Tool '{func_name}' reported an error: {err_detail}. State this outcome honestly to the user and do NOT claim success or fabricate imaginary file contents!"
        )
    elif status == "success":
        deleted_count = result.get("deleted_count")
        if deleted_count == 0:
            result["_model_directive"] = (
                "CRITICAL HONESTY: 0 items were deleted or matched. Inform the user clearly that no matching items were found."
            )
        else:
            result["_model_directive"] = "Action confirmed successful. State the verified outcome directly."
    return result


def format_tool_chips(executed_tools: list[dict[str, Any]]) -> str | None:
    """
    Format executed tool names into a sleek, inline monospace chips footnote.
    Resolves generic read_url into precise contextual chips like `read_google_sheet`, `read_google_doc`, `read_google_slides`.
    Example: ↳ `read_google_sheet`, `read_vault_file`
    """
    if not executed_tools:
        return None

    chips_list: list[str] = []
    for t in executed_tools:
        name = t.get("name")
        if not name:
            continue
        res = t.get("result") or {}
        if name in ("read_url", "read_web_page"):
            src_type = res.get("source_type") if isinstance(res, dict) else None
            if src_type == "google_sheets":
                chips_list.append("read_google_sheet")
            elif src_type == "google_docs":
                chips_list.append("read_google_doc")
            elif src_type == "google_slides":
                chips_list.append("read_google_slides")
            elif src_type == "google_drive":
                chips_list.append("read_google_drive")
            elif src_type == "google_forms":
                chips_list.append("read_google_form")
            elif src_type == "generic_web":
                chips_list.append("read_web_page")
            else:
                chips_list.append(name)
        else:
            chips_list.append(name)

    if not chips_list:
        return None

    # Deduplicate while preserving order of execution
    unique_tools = list(dict.fromkeys(chips_list))
    chips = ", ".join(f"`{name}`" for name in unique_tools)
    return f"↳ {chips}"


import re

MUTATION_CLAIM_PATTERNS = [
    (
        "complete_task",
        re.compile(
            r"(?:sudah|telah|berhasil)\s+(?:helmis\s+)?(?:tandai|ditandai|selesaikan|diselesaikan)\s+selesai|"
            r"(?:tugas|reminder)\s+.*?\s+(?:sudah|telah|berhasil)\s+(?:ditandai\s+selesai|helmis\s+tandai|helmis\s+selesaikan)|"
            r"(?:tandai|menandai)\s+tugas\s+.*?\s+sebagai\s+selesai|"
            r"marked\s+(?:it\s+)?(?:as\s+)?completed",
            re.IGNORECASE,
        ),
        {"complete_task"},
    ),
    (
        "delete_action",
        re.compile(
            r"(?:sudah|telah|berhasil)\s+(?:helmis\s+)?(?:dihapus|hapus|dihilangkan|menghapus)|"
            r"(?:catatan|tugas|memori|ingatan|file|dokumen)\s+.*?\s+(?:sudah|telah|berhasil)\s+(?:dihapus|dihilangkan)|"
            r"berhasil\s+(?:helmis\s+)?menghapus",
            re.IGNORECASE,
        ),
        {"delete_task", "delete_note", "delete_memory", "delete_vault_files", "delete_vault_directory"},
    ),
    (
        "add_task",
        re.compile(
            r"(?:sudah|telah|berhasil)\s+(?:helmis\s+)?(?:catat|dicatat|jadwalkan|dijadwalkan|buatkan\s+pengingat|buatkan\s+jadwal)|"
            r"(?:pengingat|reminder|tugas)\s+.*?\s+(?:sudah|telah|berhasil)\s+(?:dicatat|dibuat|disimpan\s+ke\s+daftar|dijadwalkan)",
            re.IGNORECASE,
        ),
        {"add_task"},
    ),
    (
        "save_vault_file",
        re.compile(
            r"(?:sudah|telah|berhasil)\s+(?:helmis\s+)?(?:disimpan|simpan)\s+ke\s+brankas|"
            r"tersimpan\s+(?:rapi\s+)?di\s+brankas",
            re.IGNORECASE,
        ),
        {"save_vault_file"},
    ),
    (
        "send_action",
        re.compile(
            r"(?:sudah|telah|berhasil)\s+(?:helmis\s+)?(?:dikirimkan|kirimkan|mengirimkan)\s+(?:file|pesan|dokumen)\s+ke|"
            r"(?:file|dokumen|pesan)\s+.*?\s+(?:sudah|telah|berhasil)\s+(?:dikirim|dikirimkan)",
            re.IGNORECASE,
        ),
        {"send_vault_file", "send_whatsapp_message", "send_whatsapp_media"},
    ),
]


def detect_unexecuted_mutation_claims(text: str, executed_tools: list[dict[str, Any]]) -> str | None:
    """
    Detect whether the model's generated text claims an action was executed (e.g. task completed,
    note deleted, file saved) without any corresponding tool having been successfully executed.
    Returns the category name of the missing tool, or None if compliant.
    """
    if not text or text.strip() in ("[NO_REPLY]", "NO_REPLY", "None"):
        return None

    success_tools = {
        t.get("name")
        for t in executed_tools
        if t.get("name") and t.get("result", {}).get("status") == "success"
    }

    # If list_tasks was called, general references to completed tasks are allowed queries
    if "list_tasks" in success_tools:
        return None

    for category_name, pattern, required_tools in MUTATION_CLAIM_PATTERNS:
        if pattern.search(text):
            if not required_tools.intersection(success_tools):
                log.warning(
                    "Detected unexecuted mutation claim '%s' in model text without required tools %s",
                    category_name,
                    required_tools,
                )
                return category_name

    return None


def strip_hallucinated_tool_chips(text: str) -> str:
    """Strip any hallucinated or LLM-mimicked tool chips footnote lines."""
    if not text:
        return ""
    # Matches lines starting with ↳, _↳, *↳, `↳, etc. and tool lists
    cleaned = re.sub(r"\n*\s*[_*~`]*↳\s*[`\w\s,_]+[_*~`]*\s*$", "", text.strip())
    return cleaned.strip()


def verify_action_fidelity(text: str, executed_tools: list[dict[str, Any]]) -> str:
    """
    Structural State Fidelity Guardrail:
    Ensures that when tools are executed in a turn, the finalized response is strictly consistent
    with the actual ground-truth outcome of the database and vault operations without brittle keyword matching.
    Also appends a sleek footnote signature (↳ `tool_name`) for complete execution transparency, while stripping
    any fake or hallucinated tool footnotes emitted by the LLM itself.
    """
    if not text or text.strip() in ("[NO_REPLY]", "NO_REPLY", "None"):
        return text

    # Strip any synthetic/hallucinated tool chips emitted by the model
    cleaned_text = strip_hallucinated_tool_chips(text)

    # If an unexecuted mutation claim was made without running the tool, block the fake confirmation
    unexecuted_claim = detect_unexecuted_mutation_claims(cleaned_text, executed_tools)
    if unexecuted_claim:
        log.error(
            "Blocking hallucinated response claiming '%s' because required tool was not executed!",
            unexecuted_claim,
        )
        return (
            "Mohon maaf, tindakan tersebut belum berhasil diproses di sistem database. "
            "Silakan ulangi perintah secara spesifik agar Helmis dapat memprosesnya."
        )

    # If no tools were executed, return cleaned text (guaranteed no fake tool chips)
    if not executed_tools:
        return cleaned_text

    # Check state mutation and vault retrieval tools
    mutation_tools = [
        t
        for t in executed_tools
        if t.get("name")
        in (
            "delete_memory",
            "delete_note",
            "delete_task",
            "complete_task",
            "update_task",
            "send_whatsapp_message",
            "send_whatsapp_media",
            "save_vault_file",
            "read_vault_file",
            "send_vault_file",
            "move_vault_files",
            "delete_vault_files",
            "create_vault_directory",
            "delete_vault_directory",
        )
    ]

    final_text = cleaned_text
    if mutation_tools:
        # If all mutation tools returned 'not_found', enforce the verified database message
        all_not_found = all(
            t.get("result", {}).get("status") == "not_found" for t in mutation_tools
        )
        if all_not_found:
            last_res = mutation_tools[-1].get("result", {})
            msg = last_res.get("message")
            if msg and isinstance(msg, str):
                final_text = msg

        # If all mutation tools returned 'error', enforce a clean, verified message
        all_errors = all(t.get("result", {}).get("status") == "error" for t in mutation_tools)
        if all_errors:
            last_res = mutation_tools[-1].get("result", {})
            err = last_res.get("error") or last_res.get("message")
            if err and isinstance(err, str):
                # If err is a raw HTTP/API error or stacktrace, let the LLM's natural explanation stand!
                if any(x in err for x in ("WAHA API error", "422", "Traceback", "statusCode", "Unprocessable")):
                    final_text = cleaned_text if cleaned_text and not any(x in cleaned_text for x in ("WAHA API error", "statusCode", "Unprocessable")) else "Mohon maaf, terjadi kendala teknis saat memproses pengiriman file."
                else:
                    final_text = err

    # Append sleek bottom footnote for clean transparency based solely on executed tools
    chips = format_tool_chips(executed_tools)
    if chips and chips not in final_text:
        final_text = f"{final_text}\n\n{chips}"

    return final_text
