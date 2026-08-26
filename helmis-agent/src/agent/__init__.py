"""
src.agent — The Brain & LLM Orchestration Package.
"""

from ..tools import GEMINI_TOOLS, execute_tool_call
from ..whatsapp.transcribe import transcribe_audio_base64
from .cascade import (
    GEMINI_KEYS,
    GEMINI_MODELS,
    fetch_available_gemini_models,
    get_cascade_models,
    get_next_gemini_key,
    load_all_skills,
    load_system_prompt,
)
from .guardrails import format_tool_chips, inject_tool_directive, verify_action_fidelity
from .loop import drain_and_inject_mid_turn_mailbox, run_agentic_react_loop
from .proactive import handle_proactive_scheduler_tick
from .tracer import AgentTurnTracer

__all__ = [
    "AgentTurnTracer",
    "GEMINI_KEYS",
    "GEMINI_MODELS",
    "GEMINI_TOOLS",
    "drain_and_inject_mid_turn_mailbox",
    "execute_tool_call",
    "fetch_available_gemini_models",
    "format_tool_chips",
    "get_cascade_models",
    "get_next_gemini_key",
    "handle_proactive_scheduler_tick",
    "inject_tool_directive",
    "load_all_skills",
    "load_system_prompt",
    "run_agentic_react_loop",
    "transcribe_audio_base64",
    "verify_action_fidelity",
]
