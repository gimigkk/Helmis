"""
agent_tools.py — Backward-compatible facade for src.tools package.
"""

from .tools import GEMINI_TOOLS, TOOL_REGISTRY, execute_tool_call, register_tool

__all__ = [
    "GEMINI_TOOLS",
    "TOOL_REGISTRY",
    "execute_tool_call",
    "register_tool",
]
