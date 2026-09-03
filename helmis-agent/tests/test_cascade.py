"""
test_cascade.py — Comprehensive test suite for Gemini cascade, key rotation, and prompt/skill loaders.
"""

import asyncio
import os
import tempfile
from typing import Any
from unittest.mock import MagicMock

import pytest

import src.agent.cascade as cascade


def test_fallback_models_include_new_generations(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fallback list: newest flash tiers first, dead aliases last."""
    # Force network failure to trigger fallback branch
    monkeypatch.setattr(cascade, "GEMINI_KEYS", ["invalid_key"])
    monkeypatch.setattr("httpx.get", MagicMock(side_effect=Exception("Offline")))

    models = cascade.fetch_available_gemini_models()
    assert "gemini-3.7-flash" in models
    assert "gemini-3.5-flash" in models
    assert "gemini-flash-lite-latest" in models
    assert "gemini-pro-latest" in models
    # Working models lead; dead alias sinks to the end.
    assert models[0] == "gemini-3.8-flash"
    assert models[-1] == "gemini-flash-lite-latest"


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

    # Included and sorted: newest Flash first, then Flash-Lite, Gemma, Pro
    assert "gemini-3.5-flash-lite" in models
    assert "gemini-3.7-flash" in models
    assert "gemma-3-27b-it" in models
    assert "gemini-2.5-pro" in models

    # Newest flash tiers lead; Flash-Lite before Gemma and Pro; Pro last
    idx_flash = models.index("gemini-3.7-flash")
    idx_lite = models.index("gemini-3.5-flash-lite")
    idx_gemma = models.index("gemma-3-27b-it")
    idx_pro = models.index("gemini-2.5-pro")

    assert idx_flash < idx_lite
    assert idx_lite < idx_gemma
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


def test_model_cooldown_demotes_failed_models(monkeypatch: pytest.MonkeyPatch) -> None:
    """A model marked unavailable is demoted (not dropped) in cascade ordering."""
    monkeypatch.setattr(cascade, "GEMINI_MODELS", ["gemini-a", "gemini-b", "gemini-c"])

    cascade.mark_model_unavailable("gemini-a", seconds=60)
    ordered = cascade.get_cascade_models_with_cooldown(is_video=False)
    assert ordered == ["gemini-b", "gemini-c", "gemini-a"]


def test_model_cooldown_expires(monkeypatch: pytest.MonkeyPatch) -> None:
    """Cooldown is transient — the model returns to front position once expired."""
    monkeypatch.setattr(cascade, "GEMINI_MODELS", ["gemini-a", "gemini-b"])

    cascade.mark_model_unavailable("gemini-a", seconds=-1)
    ordered = cascade.get_cascade_models_with_cooldown(is_video=False)
    assert ordered == ["gemini-a", "gemini-b"]


@pytest.mark.asyncio
async def test_hedged_race_slow_head_fast_second(monkeypatch: pytest.MonkeyPatch) -> None:
    """A hung head model must not tax the turn: hedge fires and wins."""
    from src.agent import loop as agent_loop

    async def slow_head(*_args: Any, **_kwargs: Any) -> Any:
        await asyncio.sleep(5.0)
        return None

    async def fast_second(model: str, *_args: Any, **_kwargs: Any) -> Any:
        if model == "gemini-slow":
            return None
        return (model, {"candidates": [{"content": {"parts": [{"text": "ok"}]}}]})

    monkeypatch.setattr(agent_loop, "_attempt_model", fast_second)

    # Patch asyncio.sleep so the hedge fires immediately instead of after
    # half the (real) timeout.
    class _NoSleep:
        async def __aenter__(self) -> None:
            return None

        async def __aexit__(self, *exc: Any) -> None:
            return False

    orig_wait = agent_loop.asyncio.wait

    async def fast_wait(fs: Any, timeout: float | None = None, **kw: Any) -> Any:
        return await orig_wait(fs, timeout=0.01, **kw)

    monkeypatch.setattr(agent_loop.asyncio, "wait", fast_wait)

    result = await agent_loop._hedged_cascade_call(
        ["gemini-slow", "gemini-fast", "gemini-tail"],
        {"contents": []},
        timeout_secs=2.0,
        keys_count=1,
    )
    assert result is not None
    assert result[0] == "gemini-fast"
