"""
cascade.py — Backwards-compatible proxy forwarding to src.agent.cascade.
"""

import sys

from .agent import cascade as _cascade_mod
from .agent.cascade import *  # noqa: F401, F403

sys.modules[__name__] = _cascade_mod
