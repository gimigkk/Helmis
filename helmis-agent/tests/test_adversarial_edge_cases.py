"""
test_adversarial_edge_cases.py — Adversarial stress tests and fuzzing for Helmis edge cases.
"""

import os
import tempfile
from collections.abc import Generator
from unittest.mock import AsyncMock, MagicMock

import pytest

import src.semantic_memory as sem_mem
from src import memory
from src.agent import run_agentic_react_loop
from src.client import WahaClient
from src.guardrails import verify_action_fidelity
from src.models import WahaHistoryMessage
from src.vault import save_file_to_vault


@pytest.fixture(autouse=True)
def isolated_test_env(monkeypatch: pytest.MonkeyPatch) -> Generator[str, None, None]:
    with tempfile.TemporaryDirectory() as tmpdir:
        mem_file = os.path.join(tmpdir, "helmis_memory.json")
        sem_file = os.path.join(tmpdir, "semantic_memories.json")

        monkeypatch.setattr(memory, "MEMORY_FILE", mem_file)
        monkeypatch.setattr(memory, "DATA_DIR", tmpdir)
        monkeypatch.setattr(sem_mem, "SEMANTIC_MEMORY_FILE", sem_file)
        monkeypatch.setattr(sem_mem, "DATA_DIR", tmpdir)

        os.environ["DATA_DIR"] = tmpdir
        os.environ["GILANG_PHONE"] = "6287796728527"
        os.environ["BUNGA_PHONE"] = "6285111111111"
        os.environ["BOT_PHONE"] = "6289999999999"

        yield tmpdir


# ----------------------------------------------------------------------
# 1. GROUP CHAT ADVERSARIAL EDGE CASES
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_group_chat_couples_banter_must_stay_silent(monkeypatch: pytest.MonkeyPatch) -> None:
    """Couples talking to each other without mentioning bot must return [NO_REPLY] (None)."""
    import src.agent as agent
    import src.cascade as cascade

    client = MagicMock(spec=WahaClient)
    client.is_reachable = AsyncMock(return_value=True)

    mock_resp = MagicMock(
        status_code=200,
        json=lambda: {"candidates": [{"content": {"parts": [{"text": "[NO_REPLY]"}]}}]},
    )
    mock_post = AsyncMock(return_value=mock_resp)

    monkeypatch.setattr(agent, "GEMINI_KEYS", ["test_key"])
    monkeypatch.setattr(cascade, "GEMINI_KEYS", ["test_key"])
    monkeypatch.setattr("httpx.AsyncClient.post", mock_post)

    m1 = WahaHistoryMessage(
        message_id="msg_1",
        sender_phone="6285111111111",
        sender_name="Bunga",
        text="km mau makan apa nanti siang?",
        media_url=None,
        timestamp=1000,
        from_me=False,
    )
    client.get_messages = AsyncMock(return_value=[m1])

    reply = await run_agentic_react_loop(
        client=client,
        sender_name="Gilang",
        chat_id="120363411261097957@g.us",
        message_text="bebas apa aja yang penting bareng km wkwk",
        max_steps=5,
    )
    # Helmis MUST NOT interrupt romantic banter between Gilang and Bunga
    assert reply is None


@pytest.mark.asyncio
async def test_group_chat_explicit_bot_invocation_must_reply(monkeypatch: pytest.MonkeyPatch) -> None:
    """When directly addressed ('Helmis' or 'mis'), bot MUST respond."""
    import src.agent as agent
    import src.cascade as cascade

    client = MagicMock(spec=WahaClient)
    client.is_reachable = AsyncMock(return_value=True)

    mock_resp = MagicMock(
        status_code=200,
        json=lambda: {
            "candidates": [{"content": {"parts": [{"text": "Ada warung sate enak di deket gerbang timur kampus."}]}}]
        },
    )
    mock_post = AsyncMock(return_value=mock_resp)

    monkeypatch.setattr(agent, "GEMINI_KEYS", ["test_key"])
    monkeypatch.setattr(cascade, "GEMINI_KEYS", ["test_key"])
    monkeypatch.setattr("httpx.AsyncClient.post", mock_post)

    m1 = WahaHistoryMessage(
        message_id="msg_1",
        sender_phone="6287796728527",
        sender_name="Gilang",
        text="bebas apa aja",
        media_url=None,
        timestamp=1000,
        from_me=False,
    )
    client.get_messages = AsyncMock(return_value=[m1])

    reply = await run_agentic_react_loop(
        client=client,
        sender_name="Bunga",
        chat_id="120363411261097957@g.us",
        message_text="Helmis, ada rekomendasi makanan enak di deket kampus ga?",
        max_steps=5,
    )
    assert reply is not None
    assert "warung sate" in reply


# ----------------------------------------------------------------------
# 2. INDONESIAN NATURAL TIME PARSING EDGE CASES
# ----------------------------------------------------------------------


def test_time_parsing_extreme_edge_cases() -> None:
    from datetime import datetime
    from zoneinfo import ZoneInfo

    tz = ZoneInfo("Asia/Jakarta")

    t1 = memory.parse_due_timestamp("subuh jam 4")
    assert t1 is not None
    dt1 = datetime.fromtimestamp(t1, tz=tz)
    assert dt1.hour == 4 and dt1.minute == 0

    t2 = memory.parse_due_timestamp("jam set 5 sore")
    assert t2 is not None
    dt2 = datetime.fromtimestamp(t2, tz=tz)
    assert dt2.hour == 16 and dt2.minute == 30

    t3 = memory.parse_due_timestamp("nanti malam jam set 10")
    assert t3 is not None
    dt3 = datetime.fromtimestamp(t3, tz=tz)
    assert dt3.hour == 21 and dt3.minute == 30

    t4 = memory.parse_due_timestamp("besok siang jam 12:45")
    assert t4 is not None
    dt4 = datetime.fromtimestamp(t4, tz=tz)
    assert dt4.hour == 12 and dt4.minute == 45


# ----------------------------------------------------------------------
# 3. SEMANTIC MEMORY ROT & PREFERENCE CONTRADICTION
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_semantic_memory_contradicting_preference_superseded(monkeypatch: pytest.MonkeyPatch) -> None:
    """When a user changes their mind, high-similarity memory is superseded in place."""

    async def mock_emb(text: str) -> list[float]:
        if "pedas" in text.lower() or "pedes" in text.lower():
            return [0.95, 0.1, 0.05]
        return [0.0, 1.0, 0.0]

    monkeypatch.setattr(sem_mem, "get_embedding", mock_emb)

    # Initial preference
    m1 = await sem_mem.add_memory("Gilang tidak suka makanan pedas", user_id="Gilang")
    assert m1 is not None

    all_mem = sem_mem.load_semantic_memories()
    assert len(all_mem) == 1
    assert "tidak suka" in all_mem[0]["fact"]

    # Updated preference later (e.g. Gilang now likes spicy)
    m2 = await sem_mem.add_memory("Gilang sekarang suka makanan pedas level 5", user_id="Gilang")
    assert m2 is not None

    all_mem_updated = sem_mem.load_semantic_memories()
    assert len(all_mem_updated) == 1
    assert "sekarang suka" in all_mem_updated[0]["fact"]


# ----------------------------------------------------------------------
# 4. VAULT FUZZING & EDGE CASES
# ----------------------------------------------------------------------


def test_vault_bulk_delete_and_special_character_injection() -> None:
    data = b"Hello world test content"
    res = save_file_to_vault(
        filename="nota_pembelian_\ud83c\udf63_2026.pdf",
        data=data,
        category="receipts",
        owner="Gilang",
        tags=["makan", "sushi", "\ud83d\udd25"],
    )
    assert "nota_pembelian" in res["filename"]
    assert res["category"] == "receipts"


# ----------------------------------------------------------------------
# 5. GUARDRAIL RAW ERROR LEAKAGE SUPPRESSION
# ----------------------------------------------------------------------


def test_verify_action_fidelity_sanitizes_raw_exceptions() -> None:
    executed_tools = [
        {
            "name": "send_vault_file",
            "args": {"target": "cv_gilang.pdf"},
            "result": {"status": "error", "error": "WAHA API error 422: Feature available only in Plus version"},
        }
    ]
    raw_response = "WAHA API error 422: The feature is available only in Plus version for 'GOWS' engine"
    sanitized = verify_action_fidelity(raw_response, executed_tools)
    assert "422" not in sanitized
    assert "error" not in sanitized.lower()
    assert "kendala teknis" in sanitized or "gagal" in sanitized or "maaf" in sanitized.lower()
