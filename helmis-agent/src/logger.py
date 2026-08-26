"""
logger.py — Backwards-compatible proxy forwarding to src.agent.tracer.
"""

import sys

from .agent import tracer as _tracer_mod
from .agent.tracer import *  # noqa: F401, F403

sys.modules[__name__] = _tracer_mod
