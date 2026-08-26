"""
vault.py — Backwards-compatible proxy forwarding to src.memory.vault.
"""

import sys

from .memory import vault as _vault_mod
from .memory.vault import *  # noqa: F401, F403

sys.modules[__name__] = _vault_mod
