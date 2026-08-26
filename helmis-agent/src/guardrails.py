"""
guardrails.py — Backwards-compatible proxy forwarding to src.agent.guardrails.
"""

import sys

from .agent import guardrails as _guardrails_mod
from .agent.guardrails import *  # noqa: F401, F403

sys.modules[__name__] = _guardrails_mod
