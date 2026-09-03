"""
test_semantic_memory.py — Tests for vector semantic episodic memory.
"""

import os
import tempfile
from collections.abc import Generator

import pytest

import src.memory.semantic as sem_mem


@pytest.fixture(autouse=True)
def temp_semantic_memory_file(monkeypatch: pytest.MonkeyPatch) -> Generator[str, None, None]:
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_file = os.path.join(tmpdir, "test_semantic_memories.json")
        monkeypatch.setattr(sem_mem, "SEMANTIC_MEMORY_FILE", tmp_file)
        monkeypatch.setattr(sem_mem, "DATA_DIR", tmpdir)
        yield tmp_file


def test_cosine_similarity() -> None:
    v1 = [1.0, 0.0, 0.0]
    v2 = [1.0, 0.0, 0.0]
    assert sem_mem.cosine_similarity(v1, v2) == 1.0

    v3 = [0.0, 1.0, 0.0]
    assert sem_mem.cosine_similarity(v1, v3) == 0.0


@pytest.mark.asyncio
async def test_add_and_search_semantic_memories(monkeypatch: pytest.MonkeyPatch) -> None:
    # Mock get_embedding to return deterministic vectors
    async def mock_embedding(text: str) -> list[float]:
        if "kopi" in text.lower() or "coffee" in text.lower():
            return [1.0, 0.0, 0.0]
        elif "kucing" in text.lower() or "cat" in text.lower():
            return [0.0, 1.0, 0.0]
        return [0.0, 0.0, 1.0]

    monkeypatch.setattr(sem_mem, "get_embedding", mock_embedding)

    entry1 = await sem_mem.add_memory("Gilang suka kopi hitam tanpa gula", user_id="Gilang")
    assert entry1 is not None
    assert entry1["user_id"] == "Gilang"

    entry2 = await sem_mem.add_memory("Bunga punya kucing lucu", user_id="Bunga")
    assert entry2 is not None

    # Search for coffee for Gilang
    results = await sem_mem.search_memories("Gilang mau pesen kopi apa?", user_id="Gilang")
    assert len(results) >= 1
    assert "kopi" in results[0]["fact"]

    # Search for pets
    results_pet = await sem_mem.search_memories("peliharaan kucing", user_id="Bunga")
    assert len(results_pet) >= 1
    assert "kucing" in results_pet[0]["fact"]


@pytest.mark.asyncio
async def test_delete_memory(monkeypatch: pytest.MonkeyPatch) -> None:
    async def mock_embedding(text: str) -> list[float]:
        if "ayam" in text.lower():
            return [1.0, 0.0, 0.0]
        elif "salad" in text.lower():
            return [0.0, 1.0, 0.0]
        return [0.0, 0.0, 1.0]

    monkeypatch.setattr(sem_mem, "get_embedding", mock_embedding)

    await sem_mem.add_memory("Gilang suka ayam goreng", user_id="Gilang")
    await sem_mem.add_memory("Bunga suka salad", user_id="Bunga")

    res_not_found = await sem_mem.delete_memory("rendang", user_id="Gilang")
    assert res_not_found["status"] == "not_found"
    assert res_not_found["deleted_count"] == 0

    res_del = await sem_mem.delete_memory("ayam goreng", user_id="Gilang")
    assert res_del["status"] == "success"
    assert res_del["deleted_count"] == 1


@pytest.mark.asyncio
async def test_supersede_memory_prevents_rot(monkeypatch: pytest.MonkeyPatch) -> None:
    # Schedule vectors have high similarity (0.95)
    async def mock_embedding(text: str) -> list[float]:
        if "jadwal kuliah" in text.lower():
            if "semester 4" in text.lower():
                return [0.99, 0.1, 0.0]
            elif "semester 5" in text.lower():
                return [0.98, 0.12, 0.0]
            return [0.95, 0.1, 0.0]
        return [0.0, 0.0, 1.0]

    monkeypatch.setattr(sem_mem, "get_embedding", mock_embedding)

    # Add old semester schedule
    m1 = await sem_mem.add_memory("Jadwal kuliah Gilang semester 4: Senin jam 8 Kalkulus", user_id="Gilang")
    assert m1 is not None

    all_mems = sem_mem.load_semantic_memories()
    assert len(all_mems) == 1
    assert "semester 4" in all_mems[0]["fact"]

    # Add new semester schedule (similarity >= 0.88 supersedes old record)
    m2 = await sem_mem.add_memory("Jadwal kuliah Gilang semester 5: Selasa jam 13 AI", user_id="Gilang")
    assert m2 is not None

    all_mems_updated = sem_mem.load_semantic_memories()
    assert len(all_mems_updated) == 1  # Replaced in place, 0 memory rot!
    assert "semester 5" in all_mems_updated[0]["fact"]

    # Search returns the new schedule with created_at timestamp
    results = await sem_mem.search_memories("jadwal kuliah", user_id="Gilang")
    assert len(results) == 1
    assert "semester 5" in results[0]["fact"]
    assert "created_at" in results[0]


@pytest.mark.asyncio
async def test_correct_memory_supersedes_and_keeps_audit(monkeypatch: pytest.MonkeyPatch) -> None:
    async def mock_embedding(text: str) -> list[float]:
        if "kopi" in text.lower():
            return [1.0, 0.0, 0.0]
        return [0.0, 0.0, 1.0]

    monkeypatch.setattr(sem_mem, "get_embedding", mock_embedding)
    await sem_mem.add_memory("Gilang suka kopi hitam tanpa gula", user_id="Gilang")

    res = await sem_mem.correct_memory(
        query="kopi hitam tanpa gula",
        corrected_fact="Gilang suka kopi manis dengan gula",
        user_id="Gilang",
    )
    assert res["status"] == "success"
    assert res["superseded_count"] == 1

    all_mems = sem_mem.load_semantic_memories()
    assert len(all_mems) == 2  # old kept for audit, new appended
    old = next(m for m in all_mems if "hitam" in m["fact"])
    new = next(m for m in all_mems if "manis" in m["fact"])
    assert old["authoritative"] is False
    assert old["confidence"] == 0.0
    assert old["superseded_by"] == new["id"]
    assert old["superseded_at"]
    assert new["provenance"] == "explicit_user_correction"
    assert new["confidence"] == 1.0
    assert new["authoritative"] is True
    assert old["id"] in new["supersedes"]

    # Search skips superseded, returns only correction
    results = await sem_mem.search_memories("kopi", user_id="Gilang")
    assert len(results) == 1
    assert "manis" in results[0]["fact"]
    assert results[0]["provenance"] == "explicit_user_correction"


@pytest.mark.asyncio
async def test_correct_memory_not_found_is_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    async def mock_embedding(text: str) -> list[float]:
        if "hiking" in text.lower() or "gunung" in text.lower():
            return [1.0, 0.0, 0.0]
        if "makanan" in text.lower() or "sushi" in text.lower():
            return [0.0, 1.0, 0.0]
        return [0.0, 0.0, 1.0]

    monkeypatch.setattr(sem_mem, "get_embedding", mock_embedding)
    await sem_mem.add_memory("Gilang suka hiking", user_id="Gilang")
    res = await sem_mem.correct_memory(
        query="makanan favorit", corrected_fact="Gilang suka sushi", user_id="Gilang"
    )
    assert res["status"] == "not_found"
    assert res["superseded_count"] == 0
    assert len(sem_mem.load_semantic_memories()) == 1  # unchanged


@pytest.mark.asyncio
async def test_correct_memory_rejects_identical_fact(monkeypatch: pytest.MonkeyPatch) -> None:
    async def mock_embedding(text: str) -> list[float]:
        if "hiking" in text.lower():
            return [1.0, 0.0, 0.0]
        return [0.0, 0.0, 1.0]

    monkeypatch.setattr(sem_mem, "get_embedding", mock_embedding)
    await sem_mem.add_memory("Gilang suka hiking", user_id="Gilang")
    # corrected fact identical to full stored claim → rejected
    res = await sem_mem.correct_memory(
        query="hiking", corrected_fact="Gilang suka hiking", user_id="Gilang"
    )
    assert res["status"] == "error"


@pytest.mark.asyncio
async def test_correct_memory_embedding_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    """Query wording differs from stored fact; similarity >= 0.78 still finds it."""
    async def mock_embedding(text: str) -> list[float]:
        if "minum" in text.lower():  # matches both "minuman" and "minum teh"
            return [0.0, 1.0, 0.0]
        if "kopi" in text.lower():
            return [1.0, 0.0, 0.0]
        return [0.0, 0.0, 1.0]

    monkeypatch.setattr(sem_mem, "get_embedding", mock_embedding)
    await sem_mem.add_memory("Bunga minum teh hijau tiap pagi", user_id="Bunga")
    res = await sem_mem.correct_memory(
        query="minuman pagi Bunga",
        corrected_fact="Bunga minum kopi susu tiap pagi",
        user_id="Bunga",
    )
    assert res["status"] == "success"
    assert res["superseded_count"] == 1
    results = await sem_mem.search_memories("minuman", user_id="Bunga")
    assert len(results) == 1
    assert "kopi susu" in results[0]["fact"]




@pytest.mark.asyncio
async def test_candidates_not_retrievable_until_confirmed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Model-extracted candidates stay invisible to search until explicitly confirmed."""
    async def mock_embedding(text: str) -> list[float]:
        return [1.0, 0.0, 0.0]

    monkeypatch.setattr(sem_mem, "get_embedding", mock_embedding)

    await sem_mem.add_memory(
        "Gilang tidak suka kopi manis", user_id="Gilang",
        provenance="model_extracted_from_turn", confidence=0.7,
        authoritative=False, status="candidate",
    )

    # Candidate invisible in search
    results = await sem_mem.search_memories("kopi", user_id="Gilang")
    assert results == []

    candidates = sem_mem.list_memory_candidates(user_id="Gilang")
    assert len(candidates) == 1
    memory_id = str(candidates[0]["id"])

    # Resolve
    accepted = sem_mem.resolve_memory_candidate(memory_id, accept=True, user_id="Gilang")
    assert accepted["status"] == "success" and accepted["outcome"] == "accepted"

    results = await sem_mem.search_memories("kopi", user_id="Gilang")
    assert len(results) == 1 and "kopi" in results[0]["fact"]
    assert results[0]["provenance"] == "model_extracted_from_turn"


@pytest.mark.asyncio
async def test_rejected_candidate_never_retrievable(monkeypatch: pytest.MonkeyPatch) -> None:
    async def mock_embedding(text: str) -> list[float]:
        return [1.0, 0.0, 0.0]

    monkeypatch.setattr(sem_mem, "get_embedding", mock_embedding)

    saved = await sem_mem.add_memory(
        "Gilang alergi kacang", user_id="Gilang",
        provenance="model_extracted_from_turn", confidence=0.7,
        authoritative=False, status="candidate",
    )
    memory_id = str(saved["id"])
    rejected = sem_mem.resolve_memory_candidate(memory_id, accept=False, user_id="Gilang")
    assert rejected["status"] == "success" and rejected["outcome"] == "rejected"

    assert sem_mem.list_memory_candidates(user_id="Gilang") == []
    results = await sem_mem.search_memories("alergi kacang", user_id="Gilang")
    assert results == []

    # Resolving again fails: already processed
    again = sem_mem.resolve_memory_candidate(memory_id, accept=True, user_id="Gilang")
    assert again["status"] == "error" and again.get("outcome") == "not_found"


@pytest.mark.asyncio
async def test_candidate_cannot_overwrite_active_memory(monkeypatch: pytest.MonkeyPatch) -> None:
    """High-similarity candidate must not supersede an active record."""
    async def mock_embedding(text: str) -> list[float]:
        return [1.0, 0.0, 0.0]

    monkeypatch.setattr(sem_mem, "get_embedding", mock_embedding)

    active = await sem_mem.add_memory("Gilang suka kopi hitam", user_id="Gilang")
    assert active["status"] == "active"

    await sem_mem.add_memory(
        "Gilang suka kopi hitam pahit", user_id="Gilang",
        provenance="model_extracted_from_turn", confidence=0.7,
        authoritative=False, status="candidate",
    )

    memories = sem_mem.load_semantic_memories()
    active_records = [m for m in memories if m.get("status", "active") == "active"]
    assert len(active_records) == 1
    assert active_records[0]["fact"] == "Gilang suka kopi hitam"  # untouched
    assert len([m for m in memories if m.get("status") == "candidate"]) == 1


@pytest.mark.asyncio
async def test_candidate_confirmation_requires_owner(monkeypatch: pytest.MonkeyPatch) -> None:
    async def mock_embedding(text: str) -> list[float]:
        return [1.0, 0.0, 0.0]

    monkeypatch.setattr(sem_mem, "get_embedding", mock_embedding)

    saved = await sem_mem.add_memory(
        "Bunga punya kucing", user_id="Bunga",
        provenance="model_extracted_from_turn", confidence=0.7,
        authoritative=False, status="candidate",
    )
    result = sem_mem.resolve_memory_candidate(str(saved["id"]), accept=True, user_id="Gilang")
    assert result["status"] == "error" and result.get("outcome") == "unauthorized"


@pytest.mark.asyncio
async def test_candidate_tools_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tool handlers expose list/confirm/reject with authorization."""
    from src.tools.registry import execute_tool_call

    async def mock_embedding(text: str) -> list[float]:
        return [1.0, 0.0, 0.0]

    monkeypatch.setattr(sem_mem, "get_embedding", mock_embedding)

    saved = await sem_mem.add_memory(
        "Gilang sedang belajar Syariah", user_id="Gilang",
        provenance="model_extracted_from_turn", confidence=0.7,
        authoritative=False, status="candidate",
    )

    listed = await execute_tool_call("list_memory_candidates", {}, default_sender="Gilang")
    assert listed["count"] == 1

    confirmed = await execute_tool_call(
        "confirm_memory_candidate", {"memory_id": saved["id"]}, default_sender="Gilang"
    )
    assert confirmed["status"] == "success"

    listed_after = await execute_tool_call("list_memory_candidates", {}, default_sender="Gilang")
    assert listed_after["count"] == 0
