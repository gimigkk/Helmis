"""
client.py — Backwards-compatible proxy forwarding to src.whatsapp.client.
"""

import sys

from .whatsapp import client as _client_mod
from .whatsapp.client import *  # noqa: F401, F403

sys.modules[__name__] = _client_mod
