"""
test_semantic_memory.py — Tests for vector semantic episodic memory.
"""

import os
import tempfile
from collections.abc import Generator

import pytest

import src.semantic_memory as sem_mem


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


