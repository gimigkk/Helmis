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


def test_list_tasks_urgency_sorting() -> None:
    memory.add_task(title="Beli tiket pesawat", due="No deadline", assignee="Gilang")
    memory.add_task(title="Jemput adik di stasiun", due="Lusa jam 14:00 WIB", assignee="Gilang")
    memory.add_task(title="Bayar tagihan listrik", due="Hari ini, 15:00 WIB", assignee="Both")
    memory.add_task(title="Meeting dokter gigi", due="Besok, 09:00 WIB", assignee="Bunga")

    # Default urgency sort
    tasks_urgency = memory.list_tasks(status="pending")
    assert len(tasks_urgency) == 4
    assert tasks_urgency[0]["title"] == "Bayar tagihan listrik"  # Today
    assert tasks_urgency[1]["title"] == "Meeting dokter gigi"    # Tomorrow
    assert tasks_urgency[2]["title"] == "Jemput adik di stasiun" # Day after tomorrow
    assert tasks_urgency[3]["title"] == "Beli tiket pesawat"     # No deadline

    # Alphabetical sort
    tasks_alpha = memory.list_tasks(status="pending", sort_by="alphabetical")
    assert tasks_alpha[0]["title"] == "Bayar tagihan listrik"
    assert tasks_alpha[1]["title"] == "Beli tiket pesawat"
    assert tasks_alpha[2]["title"] == "Jemput adik di stasiun"
    assert tasks_alpha[3]["title"] == "Meeting dokter gigi"

    # Clean up
    memory.delete_task("Beli tiket")
    memory.delete_task("Jemput adik")
    memory.delete_task("Bayar tagihan")
    memory.delete_task("Meeting dokter")


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


def test_parse_due_timestamp_day_of_week() -> None:
    ts_jumat = memory.parse_due_timestamp("Jumat, 14:00 WIB")
    assert ts_jumat != float("inf")
    ts_minggu = memory.parse_due_timestamp("Minggu jam 10:00")
    assert ts_minggu != float("inf")
    ts_senin = memory.parse_due_timestamp("Senin 09:00 WIB")
    assert ts_senin != float("inf")


def test_delete_task_exact_match_does_not_wipe_substrings() -> None:
    memory.add_task("tugas", "Tomorrow 10:00 WIB")
    memory.add_task("tugas ekonomi syariah", "Tomorrow 12:00 WIB")
    memory.add_task("tugas statistik", "Tomorrow 14:00 WIB")

    deleted = memory.delete_task("tugas")
    assert deleted is True

    pending = memory.list_tasks(status="pending")
    titles = [t["title"] for t in pending]
    assert "tugas" not in titles
    assert "tugas ekonomi syariah" in titles
    assert "tugas statistik" in titles
    assert len(pending) == 2
