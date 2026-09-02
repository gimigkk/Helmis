"""
guardrails.py — State Fidelity Guardrails and Tool Footnote Formatting for Helmis.
"""

import logging
import re
from typing import Any

from .intent import (
    build_turn_plan,
    classify_intent,
)

log = logging.getLogger("helmis-guardrails")


def classify_turn_intent(text: str) -> str:
    """Delegate to typed intent planner for backward-compatible classification."""
    return classify_intent(build_turn_plan(text))


def is_no_fluff_request(text: str) -> bool:
    """Detect copy-only / no-fluff turns where output must remain exact."""
    if not text:
        return False
    clean = text.strip().lower()
    return (
        "no fluff" in clean
        or "gausah tool call" in clean
        or "tanpa basa-basi" in clean
        or "biar bisa di copy" in clean
        or "biar gampang di copy" in clean
    )


SUPERSCRIPTS = {
    "0": "⁰", "1": "¹", "2": "²", "3": "³", "4": "⁴", "5": "⁵", "6": "⁶", "7": "⁷", "8": "⁸", "9": "⁹",
    "n": "ⁿ", "k": "ᵏ", "x": "ˣ", "+": "⁺", "-": "⁻", "=": "⁼", "(": "⁽", ")": "⁾"
}
SUBSCRIPTS = {
    "0": "₀", "1": "₁", "2": "₂", "3": "₃", "4": "₄", "5": "₅", "6": "₆", "7": "₇", "8": "₈", "9": "₉",
    "a": "ₐ", "e": "ₑ", "i": "ᵢ", "j": "ⱼ", "k": "ₖ", "m": "ₘ", "n": "ₙ", "o": "ₒ", "p": "ₚ", "r": "ᵣ",
    "s": "ₛ", "t": "ₜ", "u": "ᵤ", "v": "ᵥ", "x": "ₓ"
}


def sanitize_latex_for_whatsapp(text: str) -> str:
    """Convert raw LaTeX math expressions ($...$, $$...$$) into clean WhatsApp-compatible Unicode math."""
    if not text or "$" not in text:
        return text

    def replace_math(match: re.Match) -> str:
        expr = match.group(1).strip()
        expr = expr.replace(r"\log_2", "log₂").replace(r"\log", "log").replace(r"\ln", "ln")
        expr = expr.replace(r"\cdot", "·").replace(r"\times", "×").replace(r"\approx", "≈")
        expr = expr.replace(r"\leq", "≤").replace(r"\geq", "≥").replace(r"\neq", "≠")
        expr = expr.replace(r"\sqrt", "√").replace(r"\pm", "±").replace(r"\infty", "∞")
        expr = expr.replace(r"\sum", "Σ").replace(r"\prod", "Π").replace(r"\int", "∫")
        expr = expr.replace(r"\theta", "θ").replace(r"\lambda", "λ").replace(r"\pi", "π")
        expr = expr.replace(r"\alpha", "α").replace(r"\beta", "β").replace(r"\gamma", "γ")
        expr = expr.replace(r"\Omega", "Ω").replace(r"\Theta", "Θ").replace(r"\mathcal{O}", "O")

        # Replace superscripts like ^{3} or ^3 or ^n
        def sub_sup(m_sup: re.Match) -> str:
            val = m_sup.group(1) or m_sup.group(2)
            return "".join(SUPERSCRIPTS.get(c, c) for c in val)

        expr = re.sub(r"\^\{([^}]+)\}|\^([0-9a-zA-Z\+\-]+)", sub_sup, expr)

        # Replace subscripts like _{2} or _2
        def sub_sub(m_sub: re.Match) -> str:
            val = m_sub.group(1) or m_sub.group(2)
            return "".join(SUBSCRIPTS.get(c, c) for c in val)

        expr = re.sub(r"_\{([^}]+)\}|_([0-9a-zA-Z])", sub_sub, expr)

        # Remove remaining lone braces or backslashes
        expr = expr.replace("{", "").replace("}", "").replace("\\", "")
        return expr

    text = re.sub(r"\$\$([^\$]+)\$\$", replace_math, text)
    text = re.sub(r"\$([^\$]+)\$", replace_math, text)
    return text


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
    Format executed tool names into a sleek, inline monospace chips footnote with extraction engine badges.
    Example: ↳ `read_google_sheet:pubhtml_parser`, `read_vault_file:vision_ocr`
    """
    if not executed_tools:
        return None

    chips_list: list[str] = []
    for t in executed_tools:
        name = t.get("name")
        if not name:
            continue
        res = t.get("result") or {}
        ext_mode = res.get("extraction_mode") if isinstance(res, dict) else None

        if name in ("read_url", "read_web_page", "read_google_sheet", "read_google_doc", "read_google_slides"):
            src_type = res.get("source_type") if isinstance(res, dict) else None
            src_str = str(src_type).strip() if src_type else ""
            base_map = {
                "google_sheets": "read_google_sheet",
                "google_docs": "read_google_doc",
                "google_slides": "read_google_slides",
                "google_drive": "read_google_drive",
                "google_forms": "read_google_form",
                "generic_web": "read_web_page",
            }
            base_name = base_map.get(src_str, name)
            if ext_mode:
                chips_list.append(f"{base_name}:{ext_mode}")
            else:
                chips_list.append(base_name)
        elif name == "read_vault_file":
            if ext_mode:
                chips_list.append(f"read_vault_file:{ext_mode}")
            else:
                chips_list.append("read_vault_file")
        else:
            chips_list.append(name)

    if not chips_list:
        return None

    # Deduplicate while preserving order of execution
    unique_tools = list(dict.fromkeys(chips_list))
    chips = ", ".join(f"`{name}`" for name in unique_tools)
    return f"↳ {chips}"


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
        "promissory_reschedule",
        re.compile(
            r"(?:nanti|entar|ntar)\s+(?:gw|aku|ak|helmis)\s+(?:geser|pindah|ubah|ganti|inget|ingetin|kirim|set|atur)"
            r"|(?:akan|bakal|mau)\s+(?:gw|aku|ak|helmis)\s+(?:geser|pindah|ubah|ganti|inget|ingetin|kirim|atur)"
            r"|(?:gw|aku|ak|helmis)\s+(?:geser|pindah|ubah|ganti|inget|ingetin)\s+(?:nanti|lagi|ntar|entar)"
            r"|(?:nanti|entar)\s+(?:di(?:geser|pindah|ubah|ganti|ingetin|kirim(?:in)?))"
            r"|reminder-?nya\s+(?:gw|aku)\s+(?:geser|pindah|ubah)"
            r"|(?:gw|aku)\s+(?:atur|set)\s+ulang\s+(?:nanti|lagi)",
            re.IGNORECASE,
        ),
        {"update_task", "add_task"},
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


# Tool result statuses that prove a durable state mutation actually happened.
# A bare "success" on a read-only tool (or a mutation that matched zero rows)
# must never authorize a success claim in the final text.
MUTATION_AUTHORIZING_TOOLS = {
    "delete_memory", "delete_note", "delete_task", "complete_task", "update_task",
    "send_whatsapp_message", "send_whatsapp_media", "send_vault_file",
    "save_vault_file", "move_vault_files", "delete_vault_files",
    "create_vault_directory", "delete_vault_directory", "create_schedule",
    "append_to_note", "save_note", "remember_fact",
}


def mutation_was_effective(tool_record: dict[str, Any]) -> bool:
    """Return True only when a mutation tool result proves a durable commit.

    success with deleted_count/count 0, ambiguous, conflict, not_found and
    failed outcomes do not authorize any success language.
    """
    name = tool_record.get("name")
    result = tool_record.get("result") or {}
    status = result.get("status")
    if status != "success":
        return False
    if name in MUTATION_AUTHORIZING_TOOLS:
        for count_key in ("deleted_count", "affected_count"):
            if result.get(count_key) == 0:
                return False
        if result.get("outcome") in ("ambiguous", "conflict", "failed", "not_found"):
            return False
    return True


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
        if t.get("name") and mutation_was_effective(t)
    }

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


def verify_action_fidelity(
    text: str,
    executed_tools: list[dict[str, Any]],
    *,
    no_fluff: bool = False,
) -> str:
    """
    Structural State Fidelity Guardrail:
    Ensures that when tools are executed in a turn, the finalized response is strictly consistent
    with the actual ground-truth outcome of the database and vault operations without brittle keyword matching.
    Also appends a sleek footnote signature (↳ `tool_name`) for complete execution transparency, while stripping
    any fake or hallucinated tool footnotes emitted by the LLM itself.
    """
    if not text or text.strip() in ("[NO_REPLY]", "NO_REPLY", "None"):
        return text

    # Strip any synthetic/hallucinated tool chips emitted by the model & sanitize raw LaTeX to clean WhatsApp Unicode math
    cleaned_text = sanitize_latex_for_whatsapp(strip_hallucinated_tool_chips(text))

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

    # No-fluff / copy-only turns: output must stay exact. No chips, no rewrites.
    if no_fluff:
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
            msg = last_res.get("message") or last_res.get("error")
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
