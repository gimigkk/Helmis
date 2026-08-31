"""
registry.py — Clean Tool Registration and Dispatch Engine.
"""

from __future__ import annotations

import inspect
import logging
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any, TypeVar

from ..agent.guardrails import inject_tool_directive

if TYPE_CHECKING:
    from ..whatsapp.client import WahaClient

log = logging.getLogger("helmis-tools")

ToolHandler = Callable[..., Awaitable[dict[str, Any]] | dict[str, Any]]
TOOL_REGISTRY: dict[str, ToolHandler] = {}
F = TypeVar("F", bound=Callable[..., Any])


def register_tool(name: str) -> Callable[[F], F]:
    """Decorator to register a function as a named tool handler."""

    def decorator(func: F) -> F:
        TOOL_REGISTRY[name] = func
        return func

    return decorator


async def execute_tool_call(
    func_name: str,
    args: dict[str, Any],
    default_sender: str,
    client: Any = None,
    media_data: dict[str, Any] | None = None,
    chat_id: str | None = None,
) -> dict[str, Any]:

    """Execute a registered tool and apply state fidelity / honesty directives."""
    log.debug("Agent executing tool: %s with args: %s", func_name, args)
    handler = TOOL_REGISTRY.get(func_name)
    if not handler:
        log.error("Tool '%s' is not registered in TOOL_REGISTRY", func_name)
        res = {"status": "error", "error": f"Tool '{func_name}' tidak dikenal."}
        return inject_tool_directive(res, func_name)

    try:
        sig = inspect.signature(handler)
        kwargs: dict[str, Any] = {"args": args}
        if "default_sender" in sig.parameters:
            kwargs["default_sender"] = default_sender
        if "client" in sig.parameters:
            kwargs["client"] = client
        if "media_data" in sig.parameters:
            kwargs["media_data"] = media_data
        if "chat_id" in sig.parameters:
            kwargs["chat_id"] = chat_id

        res_dict: dict[str, Any]
        if inspect.iscoroutinefunction(handler):
            res_obj = await handler(**kwargs)
            res_dict = dict(res_obj) if isinstance(res_obj, dict) else {"result": res_obj}
        else:
            res_obj = handler(**kwargs)
            res_dict = dict(res_obj) if isinstance(res_obj, dict) else {"result": res_obj}

        return inject_tool_directive(res_dict, func_name)

    except Exception as e:
        log.error("Tool execution failed for %s: %s", func_name, e)
        res = {
            "status": "error",
            "error": str(e),
            "help_needed": "Ada kendala teknis saat menjalankan tool. Beritahu user apa kendalanya dan minta konfirmasi ulang.",
        }
        return inject_tool_directive(res, func_name)
