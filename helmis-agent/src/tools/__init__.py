"""
tools package — Modular Tool Registration, Declarations, and Domain Handlers.
"""

from . import contacts, files, memory, notes, tasks, web, whatsapp
from .mcp_export import register_all_tools
from .registry import TOOL_REGISTRY, execute_tool_call, register_tool
from .schema import GEMINI_TOOLS

__all__ = [
    "GEMINI_TOOLS",
    "TOOL_REGISTRY",
    "contacts",
    "execute_tool_call",
    "files",
    "memory",
    "notes",
    "register_all_tools",
    "register_tool",
    "tasks",
    "web",
    "whatsapp",
]
