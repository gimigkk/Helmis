"""
cascade.py — Dynamic Gemini Model Cascade, Quota Rotation, and Prompt/Skill Loaders.
"""

import logging
import os
from typing import Any

import httpx

log = logging.getLogger("helmis-cascade")

# Dynamically collect all configured Gemini API keys (filter to AI Studio keys)
GEMINI_KEYS: list[str] = [
    v.strip()
    for k, v in sorted(os.environ.items())
    if k.startswith("GEMINI_KEY") and v.strip() and v.strip().startswith("AIza")
]
if not GEMINI_KEYS:
    GEMINI_KEYS = [
        v.strip() for k, v in sorted(os.environ.items()) if k.startswith("GEMINI_KEY") and v.strip()
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
        # Fallback list if offline or API unreachable
        return [
            "gemini-flash-lite-latest",
            "gemini-2.5-flash-lite",
            "gemini-3.1-flash-lite-preview",
            "gemini-3.1-flash-lite",
            "gemini-flash-latest",
            "gemini-3.7-flash",
            "gemini-2.5-flash",
            "gemini-3.5-flash",
            "gemini-3.5-flash-lite",
            "gemini-2.5-pro",
            "gemini-pro-latest",
        ]

    # Sort: Flash-Lite first (sub-second speed), then Flash, then Gemma, then Pro
    def score_model(m: str) -> int:
        m_lower = m.lower()
        if m_lower == "gemini-flash-lite-latest":
            return 1
        elif "flash-lite" in m_lower or "flash_lite" in m_lower:
            return 2
        elif m_lower == "gemini-flash-latest":
            return 3
        elif "flash" in m_lower:
            return 4
        elif "gemma" in m_lower:
            return 5
        elif "pro" in m_lower:
            return 6
        return 7

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
    """Load system prompt from config."""
    prompt_path = os.environ.get("SYSTEM_PROMPT_PATH", "")
    candidates = [
        prompt_path,
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
    for root, _, files in os.walk(target_dir):
        for file in files:
            if file.endswith(".md"):
                full_path = os.path.join(root, file)
                try:
                    with open(full_path, encoding="utf-8") as f:
                        skill_name = os.path.basename(os.path.dirname(full_path))
                        skill_texts.append(f"### SKILL: {skill_name}\n{f.read()}")
                except Exception as ex:
                    log.warning("Could not load skill %s: %s", full_path, ex)

    if not skill_texts:
        return ""
    return "\n\n## ACTIVE SKILLS & BEHAVIORAL PLAYBOOKS:\n" + "\n\n---\n\n".join(skill_texts)
