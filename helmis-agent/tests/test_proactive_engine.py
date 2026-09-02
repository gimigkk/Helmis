"""
test_proactive_engine.py — Unit Tests for 2-Stage Lead Buffer, Urgent Nag Escalation, and Snooze Resets.
"""

from datetime import datetime
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

import pytest

from src.agent.proactive import handle_proactive_scheduler_tick
from src.memory.store import (
    add_person,
    add_task,
    complete_task,
    get_repository,
    load_memory,
    update_task,
    update_task_fields,
)
from src.whatsapp.client import WahaClient

TZ = ZoneInfo("Asia/Jakarta")


@pytest.fixture(autouse=True)
def people_directory(monkeypatch: pytest.MonkeyPatch) -> None:
    """Recipient resolution must come from directory data, not hard-coded names."""
    monkeypatch.delenv("TRIO_GROUP_JID", raising=False)
    add_person("Gilang", phone="+628123456789")
    add_person("Bunga", phone="+628987654321")


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
    with patch("src.agent.proactive.datetime") as mock_datetime:
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
    with patch("src.agent.proactive.datetime") as mock_datetime:
        mock_datetime.now.return_value = mock_dt
        await handle_proactive_scheduler_tick(mock_client)

    assert mock_client.send_message.called
    call_args = mock_client.send_message.call_args[1]
    assert "pengingat deadline: *Bayar Listrik PLN*" in call_args["text"]

    mem = load_memory()
    task = mem["tasks"][0]
    assert task["due_reminded"] is True
    assert task["nudge_count"] == 1
    with get_repository()._connect() as connection:
        occurrence = connection.execute(
            "SELECT occurrence_id, state FROM task_occurrences WHERE task_id=?",
            (task["task_id"],),
        ).fetchone()
        outbox = connection.execute(
            "SELECT occurrence_id, idempotency_key FROM outbox WHERE idempotency_key LIKE ?",
            (f"reminder:{task['task_id']}:due:%",),
        ).fetchone()
    assert occurrence["state"] == "completed"
    assert outbox["occurrence_id"] == occurrence["occurrence_id"]


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
        nag_policy={"cross_alert_recipient": "Bunga"},
    )

    # 1. Initial due at 15:00
    mock_dt_1500 = datetime(2026, 8, 26, 15, 0, 0, tzinfo=TZ)
    with patch("src.agent.proactive.datetime") as mock_datetime:
        mock_datetime.now.return_value = mock_dt_1500
        await handle_proactive_scheduler_tick(mock_client)

    mem = load_memory()
    assert mem["tasks"][0]["nudge_count"] == 1
    mock_client.send_message.reset_mock()

    # 2. 10 minutes later (15:10) -> Nudge #2
    mock_dt_1510 = datetime(2026, 8, 26, 15, 10, 0, tzinfo=TZ)
    with patch("src.agent.proactive.datetime") as mock_datetime:
        mock_datetime.now.return_value = mock_dt_1510
        await handle_proactive_scheduler_tick(mock_client)

    assert mock_client.send_message.called
    call_text = mock_client.send_message.call_args[1]["text"]
    assert "pengingat ke-2" in call_text
    assert "(10 menit lewat)" in call_text
    mem = load_memory()
    assert mem["tasks"][0]["nudge_count"] == 2
    mock_client.send_message.reset_mock()

    # 3. Fast forward to 30 minutes later (15:30) with nudge_count=3 -> Nudge #4 + Cross-alert
    mem["tasks"][0]["nudge_count"] = 3
    mem["tasks"][0]["last_nudged_at"] = mock_dt_1510.timestamp()
    update_task_fields(
        mem["tasks"][0]["task_id"],
        {"nudge_count": 3, "last_nudged_at": mock_dt_1510.timestamp()},
    )

    mock_dt_1530 = datetime(2026, 8, 26, 15, 30, 0, tzinfo=TZ)
    with patch("src.agent.proactive.datetime") as mock_datetime:
        mock_datetime.now.return_value = mock_dt_1530
        await handle_proactive_scheduler_tick(mock_client)

    # Cross-alert fires at mid-budget (nudge 3 of 5) when policy carries a recipient
    assert mock_client.send_message.call_count >= 2
    mem = load_memory()
    assert mem["tasks"][0]["nudge_count"] == 4
    mock_client.send_message.reset_mock()

    # 4. Stand down after policy budget exhausted (nudge_count=6 > max_repeats 5)
    mem["tasks"][0]["nudge_count"] = 6
    mem["tasks"][0]["last_nudged_at"] = mock_dt_1530.timestamp()
    update_task_fields(
        mem["tasks"][0]["task_id"],
        {"nudge_count": 6, "last_nudged_at": mock_dt_1530.timestamp()},
    )

    mock_dt_1600 = datetime(2026, 8, 26, 16, 0, 0, tzinfo=TZ)
    with patch("src.agent.proactive.datetime") as mock_datetime:
        mock_datetime.now.return_value = mock_dt_1600
        await handle_proactive_scheduler_tick(mock_client)

    assert mock_client.send_message.called
    call_text = mock_client.send_message.call_args[1]["text"]
    assert "menghentikan pengingat otomatis" in call_text
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
    update_task_fields(
        mem["tasks"][0]["task_id"],
        {
            "kickoff_reminded": True,
            "due_reminded": True,
            "reminded": True,
            "nudge_count": 4,
            "nudge_stopped": True,
        },
    )

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
    with patch("src.agent.proactive.datetime") as mock_datetime:
        mock_datetime.now.return_value = mock_dt
        await handle_proactive_scheduler_tick(mock_client)

    assert not mock_client.send_message.called


@pytest.mark.asyncio
async def test_recurring_scheduled_action_uses_durable_occurrence_and_advances() -> None:
    mock_client = AsyncMock(spec=WahaClient)
    add_task(
        title="Recurring report",
        due="2026-08-26 15:00 WIB",
        assignee="Helmis",
        task_type="scheduled_action",
        recurrence={
            "type": "weekly",
            "weekdays": ["Wednesday"],
            "time": "15:00",
            "timezone": "Asia/Jakarta",
        },
    )

    mock_dt = datetime(2026, 8, 26, 15, 0, tzinfo=TZ)
    with patch("src.agent.proactive.datetime") as mock_datetime:
        mock_datetime.now.return_value = mock_dt
        await handle_proactive_scheduler_tick(mock_client)

    task = load_memory()["tasks"][0]
    assert task["status"] == "pending"
    assert task["due"] == "2026-09-02 15:00 WIB"
    with get_repository()._connect() as connection:
        occurrences = connection.execute(
            "SELECT state FROM task_occurrences WHERE task_id=? ORDER BY scheduled_for",
            (task["task_id"],),
        ).fetchall()
    assert [row["state"] for row in occurrences] == ["completed"]


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
    with patch("src.agent.proactive.datetime") as mock_datetime:
        mock_datetime.now.return_value = mock_dt
        await handle_proactive_scheduler_tick(mock_client)

    # Must NOT spam live message for task from days ago
    assert not mock_client.send_message.called

    mem = load_memory()
    t = mem["tasks"][0]
    assert t["due_reminded"] is True
    assert t["nudge_stopped"] is True


@pytest.mark.asyncio
async def test_policy_row_drives_nag_cadence_and_recipient(sqlite_db) -> None:
    """Repository reminder policy row overrides defaults: 20m interval, 1 repeat, no cross-alert."""
    mock_client = AsyncMock(spec=WahaClient)
    add_task(title="Selesaikan Laporan", due="2026-08-26 15:00 WIB", assignee="Gilang", priority="normal")
    task_id = load_memory()["tasks"][0]["task_id"]
    get_repository().create_reminder_policy(
        f"policy-{task_id}", task_id=task_id, lead_minutes=0,
        repeat_interval_minutes=20, max_repeats=1,
        acknowledgment_required=True, stand_down_after_minutes=45,
    )

    with patch("src.agent.proactive.datetime") as mock_datetime:
        mock_datetime.now.return_value = datetime(2026, 8, 26, 15, 0, 0, tzinfo=TZ)
        await handle_proactive_scheduler_tick(mock_client)
    mock_client.send_message.reset_mock()

    # 15:10 -> below 20m interval, no nag
    with patch("src.agent.proactive.datetime") as mock_datetime:
        mock_datetime.now.return_value = datetime(2026, 8, 26, 15, 10, 0, tzinfo=TZ)
        await handle_proactive_scheduler_tick(mock_client)
    assert not mock_client.send_message.called

    # 15:20 -> nag #2 (budget 1 repeat), 20 menit lewat
    with patch("src.agent.proactive.datetime") as mock_datetime:
        mock_datetime.now.return_value = datetime(2026, 8, 26, 15, 20, 0, tzinfo=TZ)
        await handle_proactive_scheduler_tick(mock_client)
    call_text = mock_client.send_message.call_args[1]["text"]
    assert "pengingat ke-2" in call_text and "(20 menit lewat)" in call_text
    mock_client.send_message.reset_mock()

    # 15:40 -> budget exhausted -> stand-down after 45m per policy
    with patch("src.agent.proactive.datetime") as mock_datetime:
        mock_datetime.now.return_value = datetime(2026, 8, 26, 15, 40, 0, tzinfo=TZ)
        await handle_proactive_scheduler_tick(mock_client)
    call_text = mock_client.send_message.call_args[1]["text"]
    assert "menghentikan pengingat otomatis" in call_text and "45 menit" in call_text
    assert load_memory()["tasks"][0]["nudge_stopped"] is True


@pytest.mark.asyncio
async def test_recurring_human_reminder_advances_after_due_reminder() -> None:
    """Weekly human reminder must survive its own due reminder (previously died after first miss)."""
    mock_client = AsyncMock(spec=WahaClient)
    add_task(
        title="Rapat Mingguan",
        due="2026-08-26 15:00 WIB",  # Wednesday
        assignee="Gilang",
        recurrence={"type": "weekly", "weekdays": ["Wednesday"], "time": "15:00", "timezone": "Asia/Jakarta"},
    )

    with patch("src.agent.proactive.datetime") as mock_datetime:
        mock_datetime.now.return_value = datetime(2026, 8, 26, 15, 0, 0, tzinfo=TZ)
        await handle_proactive_scheduler_tick(mock_client)

    assert mock_client.send_message.called  # due reminder sent
    task = load_memory()["tasks"][0]
    assert task["status"] == "pending"
    assert task["due"] == "2026-09-02 15:00 WIB"
    assert task["due_reminded"] is False and task["nudge_count"] == 0

    # Old occurrence completed, next week pending
    with get_repository()._connect() as connection:
        rows = connection.execute(
            "SELECT state FROM task_occurrences WHERE task_id=? ORDER BY scheduled_for",
            (task["task_id"],),
        ).fetchall()
    assert [r["state"] for r in rows] == ["completed"]


@pytest.mark.asyncio
async def test_downtime_skips_occurrence_but_advances_recurrence() -> None:
    """>2h overdue recurring task: occurrence skipped, series advances, no expiry."""
    mock_client = AsyncMock(spec=WahaClient)
    add_task(
        title="Laporan Rutin",
        due="2026-08-24 15:00 WIB",  # Monday, now is Wednesday 16:00 (>2h late)
        assignee="Gilang",
        recurrence={"type": "weekly", "weekdays": ["Monday"], "time": "15:00", "timezone": "Asia/Jakarta"},
    )

    with patch("src.agent.proactive.datetime") as mock_datetime:
        mock_datetime.now.return_value = datetime(2026, 8, 26, 16, 0, 0, tzinfo=TZ)
        await handle_proactive_scheduler_tick(mock_client)

    task = load_memory()["tasks"][0]
    assert not mock_client.send_message.called  # missed occurrence silently skipped
    assert task["status"] == "pending"
    assert task["due"] == "2026-08-31 15:00 WIB"  # next Monday, series alive
    assert task["due_reminded"] is False


@pytest.mark.asyncio
async def test_downtime_nonrecurring_action_still_expires() -> None:
    """One-shot scheduled action >2h overdue still expires (no recurrence to preserve)."""
    mock_client = AsyncMock(spec=WahaClient)
    add_task(
        title="Kirim lama",
        due="2026-08-26 10:00 WIB",
        assignee="Helmis",
        task_type="scheduled_action",
        job={"kind": "tool", "tool_name": "send_whatsapp_message", "tool_args": {"recipient": "Gilang", "text": "x"}},
    )

    with patch("src.agent.proactive.datetime") as mock_datetime:
        mock_datetime.now.return_value = datetime(2026, 8, 26, 16, 0, 0, tzinfo=TZ)
        await handle_proactive_scheduler_tick(mock_client)

    assert not mock_client.send_message.called
    assert load_memory()["tasks"][0]["status"] == "expired"
