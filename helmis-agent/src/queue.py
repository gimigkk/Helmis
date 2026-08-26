"""
queue.py — Backwards-compatible proxy forwarding to src.whatsapp.queue.
"""

import sys

from .whatsapp import queue as _queue_mod
from .whatsapp.queue import *  # noqa: F401, F403

sys.modules[__name__] = _queue_mod
