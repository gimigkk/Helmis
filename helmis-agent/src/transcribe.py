"""
transcribe.py — Backwards-compatible proxy forwarding to src.whatsapp.transcribe.
"""

import sys

from .whatsapp import transcribe as _transcribe_mod
from .whatsapp.transcribe import *  # noqa: F401, F403

sys.modules[__name__] = _transcribe_mod
