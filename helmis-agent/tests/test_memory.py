"""
test_memory.py — Tests for persistent memory operations and time awareness.
"""

import os
import tempfile
from collections.abc import Generator

import pytest

import src.memory as memory


@pytest.fixture(autouse=True)
def temp_memory_file(monkeypatch: pytest.MonkeyPatch) -> Generator[str, None, None]:
    """Use temporary file for memory testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_file = os.path.join(tmpdir, "test_memory.json")
        monkeypatch.setattr(memory, "MEMORY_FILE", tmp_file)
        monkeypatch.setattr(memory, "DATA_DIR", tmpdir)
        yield tmp_file


def test_time_of_day_info() -> None:
    time_str, period_info = memory.get_time_of_day_info()
    assert "WIB" in time_str
    assert any(p in period_info for p in ["Pagi", "Siang", "Sore", "Malam"])


def test_task_lifecycle() -> None:
    task = memory.add_task(
        title="Meeting with client", due="2026-08-26 10:00 WIB", assignee="Gilang"
    )
    assert task["title"] == "Meeting with client"
    assert task["status"] == "pending"

    pending_tasks = memory.list_tasks(status="pending")
    assert len(pending_tasks) == 1

    completed = memory.complete_task("Meeting")
    assert completed is not None
    assert completed["status"] == "completed"
    assert "completed_at" in completed

    # Pending should now be 0, completed should be 1
    assert len(memory.list_tasks(status="pending")) == 0
    assert len(memory.list_tasks(status="completed")) == 1

    deleted = memory.delete_task("Meeting")
    assert deleted is True
    assert len(memory.list_tasks(status="all")) == 0


def test_person_directory() -> None:
    person = memory.add_person(
        name="Dr. Sarah", phone="+628111222333", role="Dentist", notes="Appointment every 6 months"
    )
    assert person["name"] == "Dr. Sarah"

    found = memory.get_person("sarah")
    assert found is not None
    assert found["role"] == "Dentist"

    not_found = memory.get_person("Unknown Person")
    assert not_found is None


def test_save_note_and_search() -> None:
    memory.save_note(title="WiFi Password", content="HelmisSecret2026")
    results = memory.search_memory("secret")
    assert len(results["notes"]) == 1
    assert results["notes"][0]["title"] == "WiFi Password"
