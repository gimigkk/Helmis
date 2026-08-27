"""
test_cascade.py — Comprehensive test suite for Gemini cascade, key rotation, and prompt/skill loaders.
"""

import os
import tempfile
from unittest.mock import MagicMock

import pytest

import src.agent.cascade as cascade


def test_fallback_models_include_new_generations(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify fallback models list contains new generations (3.7-flash, 3.5-flash-lite) and sorted properly."""
    # Force network failure to trigger fallback branch
    monkeypatch.setattr(cascade, "GEMINI_KEYS", ["invalid_key"])
    monkeypatch.setattr("httpx.get", MagicMock(side_effect=Exception("Offline")))

    models = cascade.fetch_available_gemini_models()
    assert "gemini-3.7-flash" in models
    assert "gemini-3.5-flash-lite" in models
    assert "gemini-flash-lite-latest" in models
    assert "gemini-2.5-pro" in models


def test_dynamic_api_discovery_filtering_and_sorting(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify dynamic discovery filters out non-text models and sorts Flash-Lite first."""
    mock_payload = {
        "models": [
            {
                "name": "models/gemini-2.5-pro",
                "supportedGenerationMethods": ["generateContent"],
            },
            {
                "name": "models/gemini-tts-1",
                "supportedGenerationMethods": ["generateContent"],
            },
            {
                "name": "models/gemini-image-gen",
                "supportedGenerationMethods": ["generateContent"],
            },
            {
                "name": "models/gemini-robotics-001",
                "supportedGenerationMethods": ["generateContent"],
            },
            {
                "name": "models/gemini-3.5-flash-lite",
                "supportedGenerationMethods": ["generateContent"],
            },
            {
                "name": "models/gemini-3.7-flash",
                "supportedGenerationMethods": ["generateContent"],
            },
            {
                "name": "models/gemma-3-27b-it",
                "supportedGenerationMethods": ["generateContent"],
            },
            {
                "name": "models/embedding-001",
                "supportedGenerationMethods": ["embedContent"],
            },
        ]
    }

    mock_resp = MagicMock(status_code=200, json=lambda: mock_payload)
    monkeypatch.setattr(cascade, "GEMINI_KEYS", ["test_key_123"])
    monkeypatch.setattr("httpx.get", MagicMock(return_value=mock_resp))

    models = cascade.fetch_available_gemini_models()

    # Filtered out
    assert "gemini-tts-1" not in models
    assert "gemini-image-gen" not in models
    assert "gemini-robotics-001" not in models
    assert "embedding-001" not in models

    # Included and sorted: Flash-Lite first, then Flash, Gemma, Pro
    assert "gemini-3.5-flash-lite" in models
    assert "gemini-3.7-flash" in models
    assert "gemma-3-27b-it" in models
    assert "gemini-2.5-pro" in models

    # Flash-Lite should appear before Flash, which appears before Gemma and Pro
    idx_lite = models.index("gemini-3.5-flash-lite")
    idx_flash = models.index("gemini-3.7-flash")
    idx_gemma = models.index("gemma-3-27b-it")
    idx_pro = models.index("gemini-2.5-pro")

    assert idx_lite < idx_flash
    assert idx_flash < idx_gemma
    assert idx_gemma < idx_pro


def test_get_cascade_models_modality_filtering(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify video turns exclude flash-lite models while standard turns keep them."""
    test_models = [
        "gemini-flash-lite-latest",
        "gemini-3.5-flash-lite",
        "gemini-3.7-flash",
        "gemini-2.5-pro",
    ]
    monkeypatch.setattr(cascade, "GEMINI_MODELS", test_models)

    # Standard modality
    standard_models = cascade.get_cascade_models(is_video=False)
    assert standard_models == test_models

    # Video modality
    video_models = cascade.get_cascade_models(is_video=True)
    assert "gemini-flash-lite-latest" not in video_models
    assert "gemini-3.5-flash-lite" not in video_models
    assert "gemini-3.7-flash" in video_models
    assert "gemini-2.5-pro" in video_models


def test_key_rotation_round_robin(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify round-robin rotation across multiple Gemini API keys."""
    test_keys = ["AIzaSyKey1", "AIzaSyKey2", "AIzaSyKey3"]
    monkeypatch.setattr(cascade, "GEMINI_KEYS", test_keys)
    cascade._key_index = 0

    k1 = cascade.get_next_gemini_key()
    k2 = cascade.get_next_gemini_key()
    k3 = cascade.get_next_gemini_key()
    k4 = cascade.get_next_gemini_key()

    assert k1 == "AIzaSyKey1"
    assert k2 == "AIzaSyKey2"
    assert k3 == "AIzaSyKey3"
    assert k4 == "AIzaSyKey1"


def test_key_rotation_raises_when_no_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify ValueError is raised if no keys exist anywhere."""
    monkeypatch.setattr(cascade, "GEMINI_KEYS", [])
    # Clear any GEMINI_KEY env vars
    for k in list(os.environ.keys()):
        if k.startswith("GEMINI_KEY"):
            monkeypatch.delenv(k, raising=False)

    with pytest.raises(ValueError, match="No GEMINI_KEY configured"):
        cascade.get_next_gemini_key()


def test_load_system_prompt_custom_path_and_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify system prompt loader respects custom paths and fallbacks gracefully."""
    with tempfile.TemporaryDirectory() as tmpdir:
        prompt_file = os.path.join(tmpdir, "custom-prompt.md")
        with open(prompt_file, "w", encoding="utf-8") as f:
            f.write("Custom Prompt for Helmis")

        monkeypatch.setenv("SYSTEM_PROMPT_PATH", prompt_file)
        loaded = cascade.load_system_prompt()
        assert loaded == "Custom Prompt for Helmis"

    # Test fallback when path does not exist
    monkeypatch.setenv("SYSTEM_PROMPT_PATH", "/non/existent/path/prompt.md")
    # Point candidate paths to non-existent
    monkeypatch.setattr("os.path.exists", lambda p: False)
    fallback = cascade.load_system_prompt()
    assert "You are Helmis" in fallback


def test_load_all_skills(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify skill loader recursively discovers all markdown playbooks under the skills folder."""
    with tempfile.TemporaryDirectory() as tmpdir:
        skill_dir1 = os.path.join(tmpdir, "task-manager")
        os.makedirs(skill_dir1, exist_ok=True)
        with open(os.path.join(skill_dir1, "SKILL.md"), "w", encoding="utf-8") as f:
            f.write("Task management guidelines and rules.")

        skill_dir2 = os.path.join(tmpdir, "vault-manager")
        os.makedirs(skill_dir2, exist_ok=True)
        with open(os.path.join(skill_dir2, "SKILL.md"), "w", encoding="utf-8") as f:
            f.write("Vault document preservation rules.")

        monkeypatch.setenv("SKILLS_DIR", tmpdir)
        skills_text = cascade.load_all_skills()

        assert "## ACTIVE SKILLS & BEHAVIORAL PLAYBOOKS:" in skills_text
        assert "### SKILL: task-manager" in skills_text
        assert "Task management guidelines and rules." in skills_text
        assert "### SKILL: vault-manager" in skills_text
        assert "Vault document preservation rules." in skills_text
