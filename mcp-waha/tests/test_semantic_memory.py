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
