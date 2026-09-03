"""
cascade.py — Dynamic Gemini Model Cascade, Quota Rotation, and Prompt/Skill Loaders.
"""

import logging
import os
import threading
import time
from typing import Any

import httpx

log = logging.getLogger("helmis-cascade")

# Dynamically collect all configured Gemini API keys. Both key formats are
# valid: "AIza..." (AI Studio) and "AQ...." (v2 keys). Filtering to one format
# silently drops working keys — only obvious placeholders are excluded.
def _looks_like_gemini_key(value: str) -> bool:
    return bool(value) and not value.lower().startswith(("your", "changeme", "xxx", "placeholder"))

GEMINI_KEYS: list[str] = [
    v.strip()
    for k, v in sorted(os.environ.items())
    if k.startswith("GEMINI_KEY") and _looks_like_gemini_key(v.strip())
]


def fetch_available_gemini_models() -> list[str]:
    """Dynamically query Google API for all available models supporting generateContent."""
    discovered: list[str] = []
    for key in GEMINI_KEYS:
        try:
            resp = httpx.get(
                f"https://generativelanguage.googleapis.com/v1beta/models?key={key}", timeout=5.0
            )
            if resp.status_code == 200:
                raw_models: list[dict[str, Any]] = resp.json().get("models", [])
                for m in raw_models:
                    name = str(m.get("name", "")).replace("models/", "")
                    methods = m.get("supportedGenerationMethods", [])
                    if "generateContent" in methods and not any(
                        skip in name
                        for skip in [
                            "tts",
                            "image",
                            "banana",
                            "robotics",
                            "computer-use",
                            "research",
                            "clip",
                        ]
                    ):
                        if name not in discovered:
                            discovered.append(name)
                if discovered:
                    break
        except Exception as e:
            log.warning("Could not fetch models dynamically with key: %s", e)

    if not discovered:
        # Fallback list if offline or API unreachable.
        # Newest flash tiers with confirmed quota first; dead aliases last.
        return [
            "gemini-3.8-flash",
            "gemini-3.7-flash",
            "gemini-3.6-flash",
            "gemini-3.5-flash",
            "gemini-2.5-flash-lite",
            "gemini-3.1-flash-lite",
            "gemini-flash-latest",
            "gemini-2.5-flash",
            "gemini-pro-latest",
            "gemini-flash-lite-latest",
        ]

    # Sort: newest flash tiers with confirmed quota first (3.8 > 3.7 > 3.6 >
    # 3.5 > flash-lite), then older Flash, Gemma, Pro. Known-dead aliases sink
    # to the very end so the first cascade window (loop tries the first 4)
    # never wastes wall-clock on them.
    _PREFERRED = [
        ("gemini-3.8-flash", 0),
        ("gemini-3.7-flash", 1),
        ("gemini-3.6-flash", 2),
        ("gemini-3.5-flash", 3),
        ("gemini-2.5-flash-lite", 4),
        ("gemini-3.1-flash-lite", 5),
    ]

    def score_model(m: str) -> int:
        m_lower = m.lower()
        for name, score in _PREFERRED:
            if m_lower == name:
                return score
        if m_lower == "gemini-flash-lite-latest":
            # Dead alias on current keys (repeat timeouts); last resort only.
            return 90
        elif "flash-lite" in m_lower or "flash_lite" in m_lower:
            return 6
        elif "flash" in m_lower:
            return 7
        elif "gemma" in m_lower:
            return 8
        elif "pro" in m_lower:
            return 9
        return 10

    discovered.sort(key=score_model)
    return discovered


# Dynamically Discovered Model Cascade
GEMINI_MODELS: list[str] = fetch_available_gemini_models()
log.info(
    "Initialized dynamic Gemini model cascade with %d models: %s",
    len(GEMINI_MODELS),
    GEMINI_MODELS,
)


def get_cascade_models(is_video: bool = False) -> list[str]:
    """Return model cascade tailored for the turn modality."""
    if is_video:
        video_models = [
            m
            for m in GEMINI_MODELS
            if "flash-lite" not in m.lower() and "flash_lite" not in m.lower()
        ]
        return video_models or GEMINI_MODELS
    return GEMINI_MODELS


_key_index = 0

# Model-level cooldown: a model that just returned 503/timeout/404 is dead
# weight for a short window — re-probing it every ReAct step burns 8 key
# attempts × ~1-3s each before falling through. Track per-model penalties
# in process memory (best-effort; container restart clears them).
_MODEL_COOLDOWN_SECONDS = 120.0
_model_cooldowns: dict[str, float] = {}
_cooldown_lock = threading.Lock()


def mark_model_unavailable(model: str, *, seconds: float = _MODEL_COOLDOWN_SECONDS) -> None:
    """Put a model on cooldown after 503/timeout/404 so later steps skip it."""
    with _cooldown_lock:
        _model_cooldowns[model] = time.monotonic() + seconds


def get_cascade_models_with_cooldown(is_video: bool = False) -> list[str]:
    """Cascade order with recently-failed models deprioritized to the end.

    Failed models are not dropped (they may recover mid-turn); they are
    demoted so the healthy tail of the cascade is tried first.
    """
    models = get_cascade_models(is_video=is_video)
    now = time.monotonic()
    with _cooldown_lock:
        healthy = [m for m in models if _model_cooldowns.get(m, 0.0) <= now]
        cooling = [m for m in models if _model_cooldowns.get(m, 0.0) > now]
    return healthy + cooling


def get_next_gemini_key() -> str:
    """Round-robin rotation across available Gemini keys."""
    global _key_index
    keys = GEMINI_KEYS
    if not keys:
        try:
            import sys

            if "src.agent" in sys.modules:
                keys = getattr(sys.modules["src.agent"], "GEMINI_KEYS", [])
            elif "src.agent.cascade" in sys.modules:
                keys = getattr(sys.modules["src.agent.cascade"], "GEMINI_KEYS", [])
        except Exception:
            pass
    if not keys:
        keys = [
            v.strip()
            for k, v in sorted(os.environ.items())
            if k.startswith("GEMINI_KEY") and v.strip()
        ]
    if not keys:
        raise ValueError("No GEMINI_KEY configured in environment")
    key = keys[_key_index % len(keys)]
    _key_index += 1
    return key


def load_system_prompt() -> str:
    """Load system prompt from config, supporting local overrides (e.g. system-prompt.local.md)."""
    prompt_path = os.environ.get("SYSTEM_PROMPT_PATH", "")
    candidates = [
        prompt_path,
        "/app/config/system-prompt.local.md",
        "config/system-prompt.local.md",
        "../config/system-prompt.local.md",
        "/app/config/system-prompt.md",
        "/hermes-config/system-prompt.md",
        "config/system-prompt.md",
        "../config/system-prompt.md",
    ]
    for p in candidates:
        if p and os.path.exists(p):
            try:
                with open(p, encoding="utf-8") as f:
                    return f.read()
            except Exception as e:
                log.warning("Could not read system prompt file (%s): %s", p, e)
    return "You are Helmis, personal AI secretary for Gilang and Bunga. Address them by name and be proactive and concise."


def load_all_skills() -> str:
    """Load all markdown skills defined under config/skills."""
    skills_dir = os.environ.get("SKILLS_DIR", "")
    candidates = [
        skills_dir,
        "/app/config/skills",
        "/hermes-config/skills",
        "config/skills",
        "../config/skills",
    ]
    target_dir = ""
    for d in candidates:
        if d and os.path.exists(d):
            target_dir = d
            break
    if not target_dir:
        return ""

    skill_texts = []
    on_demand_skills = []

    for root, _, files in sorted(os.walk(target_dir)):
        for file in sorted(files):
            if file.endswith(".md"):
                full_path = os.path.join(root, file)
                try:
                    with open(full_path, encoding="utf-8") as f:
                        content = f.read()
                        skill_name = os.path.basename(os.path.dirname(full_path))

                        # Check if skill is on-demand toolkit
                        if skill_name.endswith("-toolkit") or "on-demand" in content.lower():
                            import re
                            m = re.search(r"description:\s*(.+)", content, re.IGNORECASE)
                            desc = m.group(1).strip() if m else "Specialized domain operations."
                            on_demand_skills.append(f"- `{skill_name}`: {desc} (Invoke `load_skill(name='{skill_name}')` when needed)")
                        else:
                            skill_texts.append(f"### SKILL: {skill_name}\n{content}")
                except Exception as ex:
                    log.warning("Could not load skill %s: %s", full_path, ex)

    output_sections = []
    if skill_texts:
        output_sections.append("## ACTIVE SKILLS & BEHAVIORAL PLAYBOOKS:\n" + "\n\n---\n\n".join(skill_texts))
    if on_demand_skills:
        output_sections.append("## ON-DEMAND DOMAIN SKILLS (Load via `load_skill` when needed):\n" + "\n".join(on_demand_skills))

    if not output_sections:
        return ""
    return "\n\n".join(output_sections)
