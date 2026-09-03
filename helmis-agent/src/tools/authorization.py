"""Central authorization and scope checks for tool dispatch."""

import os
from typing import Any

_INTERNAL_PREFIXES = ("helmis", "system", "scheduler", "mcp")


def _names_from_env() -> set[str]:
    configured = os.environ.get("HELMIS_AUTHORIZED_SENDERS", "")
    if configured.strip():
        names = configured.split(",")
    else:
        names = [
            os.environ.get("OWNER_NAME", "Gilang"),
            os.environ.get("PARTNER_NAME", "Bunga"),
        ]
    return {name.strip().casefold() for name in names if name.strip()}


def _chat_scope() -> set[str]:
    configured = os.environ.get("HELMIS_AUTHORIZED_CHATS", "")
    return {chat.strip() for chat in configured.split(",") if chat.strip()}


def authorize_tool_call(
    func_name: str,
    args: dict[str, Any],
    *,
    default_sender: str,
    chat_id: str | None = None,
) -> dict[str, Any] | None:
    """Return an error result or ``None`` when the call is authorized.

    Sender and chat checks are evaluated at call time so deployments and
    tests can change policy without stale module-level configuration.
    """
    principal = str(default_sender or "").strip()
    principal_key = principal.casefold()
    if not principal:
        return {
            "status": "error",
            "outcome": "unauthorized",
            "error": "Caller identity is required before using tools.",
        }

    if not any(principal_key.startswith(prefix) for prefix in _INTERNAL_PREFIXES):
        if principal_key not in _names_from_env():
            return {
                "status": "error",
                "outcome": "unauthorized",
                "error": "Caller is not authorized to use Helmis tools.",
            }

    allowed_chats = _chat_scope()
    if chat_id and allowed_chats and chat_id not in allowed_chats:
        return {
            "status": "error",
            "outcome": "unauthorized",
            "error": "This chat is outside the configured authorization scope.",
        }

    requested_user = str(args.get("user_id") or "").strip()
    if requested_user and requested_user.casefold() != principal_key:
        return {
            "status": "error",
            "outcome": "unauthorized",
            "error": "A caller may not access another user's private memory scope.",
        }
    return None
