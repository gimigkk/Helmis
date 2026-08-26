"""
search.py — Backwards-compatible proxy forwarding to src.whatsapp.search.
"""

import sys

from .whatsapp import search as _search_mod
from .whatsapp.search import *  # noqa: F401, F403

sys.modules[__name__] = _search_mod
