"""
webhook.py — Backwards-compatible proxy forwarding to src.whatsapp.webhook, processor, and parser.
"""

from .whatsapp.parser import *  # noqa: F401, F403
from .whatsapp.processor import *  # noqa: F401, F403
from .whatsapp.webhook import *  # noqa: F401, F403
