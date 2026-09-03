"""
tools package — Modular Tool Registration, Declarations, and Domain Handlers.
"""

from . import (
    code_exec,
    contacts,
    files,
    memory,
    notes,
    pdf_ops,
    schedules,
    search,
    skills,
    tasks,
    web,
    whatsapp,
)
from .mcp_export import register_all_tools
from .registry import TOOL_REGISTRY, execute_tool_call, register_tool
from .schema import GEMINI_TOOLS
from .search import search_web

__all__ = [
    "GEMINI_TOOLS",
    "TOOL_REGISTRY",
    "code_exec",
    "contacts",
    "execute_tool_call",
    "files",
    "memory",
    "notes",
    "pdf_ops",
    "register_all_tools",
    "register_tool",
    "schedules",
    "search",
    "search_web",
    "skills",
    "tasks",
    "web",
    "whatsapp",
]
