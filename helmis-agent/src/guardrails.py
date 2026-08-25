"""
guardrails.py — State Fidelity Guardrails and Strict Tool Directives.
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


def verify_action_fidelity(text: str, executed_tools: list[dict[str, Any]]) -> str:
    """
    Structural State Fidelity Guardrail:
    Ensures that when tools are executed in a turn, the finalized response is strictly consistent
    with the actual ground-truth outcome of the database and vault operations without brittle keyword matching.
    """
    if not executed_tools:
        return text

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

    if mutation_tools:
        # If all mutation tools returned 'not_found', enforce the verified database message
        all_not_found = all(
            t.get("result", {}).get("status") == "not_found" for t in mutation_tools
        )
        if all_not_found:
            last_res = mutation_tools[-1].get("result", {})
            msg = last_res.get("message")
            if msg and isinstance(msg, str):
                return msg

        # If all mutation tools returned 'error', enforce the verified error message
        all_errors = all(t.get("result", {}).get("status") == "error" for t in mutation_tools)
        if all_errors:
            last_res = mutation_tools[-1].get("result", {})
            err = last_res.get("error") or last_res.get("message")
            if err and isinstance(err, str):
                return err

    return text
