"""
semantic_memory.py — Backwards-compatible proxy forwarding to src.memory.semantic.
"""

import sys

from .memory import semantic as _semantic_mod
from .memory.semantic import *  # noqa: F401, F403

sys.modules[__name__] = _semantic_mod
