"""
test_proactive_engine.py — Unit Tests for 2-Stage Lead Buffer, Urgent Nag Escalation, and Snooze Resets.
"""

from collections.abc import Generator
from datetime import datetime
from typing import Any
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

import pytest

from src.memory.store import add_task, complete_task, load_memory, save_memory, update_task
from src.proactive import handle_proactive_scheduler_tick
from src.whatsapp.client import WahaClient

TZ = ZoneInfo("Asia/Jakarta")


@pytest.fixture(autouse=True)
def clean_memory_fixture() -> Generator[None, None, None]:
    """Ensure clean memory for each test run."""
    empty_mem: dict[str, Any] = {
        "tasks": [],
        "activity_log": [],
        "notes": [],
        "people": {},
    }
    save_memory(empty_mem)
    yield
    save_memory(empty_mem)


@pytest.mark.asyncio
async def test_proactive_stage1_kickoff_reminder() -> None:
    """Verify that Stage 1 kickoff preparation reminder fires when within the lead buffer window."""
    mock_client = AsyncMock(spec=WahaClient)

    # Task due at 15:00 with 120 minutes lead time (kickoff window starts at 13:00)
    add_task(
        title="Submit Laporan Praktikum",
        due="2026-08-26 15:00 WIB",
        assignee="Gilang",
        priority="normal",
        lead_time_minutes=120,
    )

    # Mock time to 13:05 WIB (inside lead buffer window)
    mock_dt = datetime(2026, 8, 26, 13, 5, 0, tzinfo=TZ)
    with patch("src.proactive.datetime") as mock_datetime:
        mock_datetime.now.return_value = mock_dt
        await handle_proactive_scheduler_tick(mock_client)

    assert mock_client.send_message.called
    call_args = mock_client.send_message.call_args[1]
    assert "pengingat persiapan: deadline *Submit Laporan Praktikum*" in call_args["text"]
    assert "sisa 1 jam 55 menit lagi" in call_args["text"]

    mem = load_memory()
    task = mem["tasks"][0]
    assert task["kickoff_reminded"] is True
    assert task.get("due_reminded") is False


@pytest.mark.asyncio
async def test_proactive_stage2_due_reminder() -> None:
    """Verify that Stage 2 final deadline alert fires at due time."""
    mock_client = AsyncMock(spec=WahaClient)

    add_task(
        title="Bayar Listrik PLN",
        due="2026-08-26 15:00 WIB",
        assignee="Gilang",
        priority="normal",
        lead_time_minutes=0,
    )

    # Mock time to 15:00 WIB (due time)
    mock_dt = datetime(2026, 8, 26, 15, 0, 0, tzinfo=TZ)
    with patch("src.proactive.datetime") as mock_datetime:
        mock_datetime.now.return_value = mock_dt
        await handle_proactive_scheduler_tick(mock_client)

    assert mock_client.send_message.called
    call_args = mock_client.send_message.call_args[1]
    assert "pengingat deadline: *Bayar Listrik PLN*" in call_args["text"]

    mem = load_memory()
    task = mem["tasks"][0]
    assert task["due_reminded"] is True
    assert task["nudge_count"] == 1


@pytest.mark.asyncio
async def test_proactive_urgent_nag_loop_and_partner_escalation() -> None:
    """Verify that urgent tasks trigger 10-minute follow-ups, partner cross-alerts at 30m, and stand down at 60m."""
    mock_client = AsyncMock(spec=WahaClient)

    add_task(
        title="Minum Obat Antibiotik",
        due="2026-08-26 15:00 WIB",
        assignee="Gilang",
        priority="urgent",
        lead_time_minutes=0,
    )

    # 1. Initial due at 15:00
    mock_dt_1500 = datetime(2026, 8, 26, 15, 0, 0, tzinfo=TZ)
    with patch("src.proactive.datetime") as mock_datetime:
        mock_datetime.now.return_value = mock_dt_1500
        await handle_proactive_scheduler_tick(mock_client)

    mem = load_memory()
    assert mem["tasks"][0]["nudge_count"] == 1
    mock_client.send_message.reset_mock()

    # 2. 10 minutes later (15:10) -> Nudge #2
    mock_dt_1510 = datetime(2026, 8, 26, 15, 10, 0, tzinfo=TZ)
    with patch("src.proactive.datetime") as mock_datetime:
        mock_datetime.now.return_value = mock_dt_1510
        await handle_proactive_scheduler_tick(mock_client)

    assert mock_client.send_message.called
    call_text = mock_client.send_message.call_args[1]["text"]
    assert "belum ada konfirmasi (10 menit lalu)" in call_text
    mem = load_memory()
    assert mem["tasks"][0]["nudge_count"] == 2
    mock_client.send_message.reset_mock()

    # 3. Fast forward to 30 minutes later (15:30) with nudge_count=3 -> Nudge #4 + Cross-alert
    mem["tasks"][0]["nudge_count"] = 3
    mem["tasks"][0]["last_nudged_at"] = mock_dt_1510.timestamp()
    save_memory(mem)

    mock_dt_1530 = datetime(2026, 8, 26, 15, 30, 0, tzinfo=TZ)
    with patch("src.proactive.datetime") as mock_datetime:
        mock_datetime.now.return_value = mock_dt_1530
        await handle_proactive_scheduler_tick(mock_client)

    # Dispatches to Gilang AND cross-alerts Bunga
    assert mock_client.send_message.call_count >= 2
    mem = load_memory()
    assert mem["tasks"][0]["nudge_count"] == 4
    mock_client.send_message.reset_mock()

    # 4. Stand down at 60 minutes (nudge_count=6)
    mem["tasks"][0]["nudge_count"] = 6
    mem["tasks"][0]["last_nudged_at"] = mock_dt_1530.timestamp()
    save_memory(mem)

    mock_dt_1600 = datetime(2026, 8, 26, 16, 0, 0, tzinfo=TZ)
    with patch("src.proactive.datetime") as mock_datetime:
        mock_datetime.now.return_value = mock_dt_1600
        await handle_proactive_scheduler_tick(mock_client)

    assert mock_client.send_message.called
    call_text = mock_client.send_message.call_args[1]["text"]
    assert "menghentikan pengingat otomatis" in call_text
    assert "sudah 60 menit tanpa respon" in call_text
    mem = load_memory()
    assert mem["tasks"][0]["nudge_stopped"] is True


def test_task_snooze_resets_reminder_flags() -> None:
    """Verify that updating task due time resets all reminder lifecycle flags."""
    add_task(
        title="Review PR Backend",
        due="2026-08-26 15:00 WIB",
        assignee="Gilang",
        priority="urgent",
        lead_time_minutes=30,
    )
    mem = load_memory()
    t = mem["tasks"][0]
    t["kickoff_reminded"] = True
    t["due_reminded"] = True
    t["reminded"] = True
    t["nudge_count"] = 4
    t["nudge_stopped"] = True
    save_memory(mem)

    # User snoozes task: update due to 18:00 WIB
    updated = update_task("Review PR Backend", new_due="2026-08-26 18:00 WIB")
    assert updated is not None
    assert updated["due"] == "2026-08-26 18:00 WIB"
    assert updated["kickoff_reminded"] is False
    assert updated["due_reminded"] is False
    assert updated["reminded"] is False
    assert updated["nudge_count"] == 0
    assert updated["nudge_stopped"] is False


@pytest.mark.asyncio
async def test_completed_task_skips_all_reminders() -> None:
    """Verify that completed tasks never trigger reminders."""
    mock_client = AsyncMock(spec=WahaClient)

    add_task(
        title="Beli Susu Oat",
        due="2026-08-26 15:00 WIB",
        assignee="Gilang",
    )
    complete_task("Beli Susu Oat")

    mock_dt = datetime(2026, 8, 26, 15, 0, 0, tzinfo=TZ)
    with patch("src.proactive.datetime") as mock_datetime:
        mock_datetime.now.return_value = mock_dt
        await handle_proactive_scheduler_tick(mock_client)

    assert not mock_client.send_message.called


@pytest.mark.asyncio
async def test_proactive_ancient_overdue_task_silently_marked() -> None:
    """Verify that a task that was already >2 hours overdue when first loaded is silently marked reminded."""
    mock_client = AsyncMock(spec=WahaClient)

    # Task due 3 days ago (2026-08-20)
    add_task(
        title="Tugas Lama",
        due="2026-08-20 10:00 WIB",
        assignee="Gilang",
    )

    mock_dt = datetime(2026, 8, 26, 12, 0, 0, tzinfo=TZ)
    with patch("src.proactive.datetime") as mock_datetime:
        mock_datetime.now.return_value = mock_dt
        await handle_proactive_scheduler_tick(mock_client)

    # Must NOT spam live message for task from days ago
    assert not mock_client.send_message.called

    mem = load_memory()
    t = mem["tasks"][0]
    assert t["due_reminded"] is True
    assert t["nudge_stopped"] is True
