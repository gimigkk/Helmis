"""
history.py — Backwards-compatible proxy forwarding to src.whatsapp.history.
"""

import sys

from .whatsapp import history as _history_mod
from .whatsapp.history import *  # noqa: F401, F403

sys.modules[__name__] = _history_mod
