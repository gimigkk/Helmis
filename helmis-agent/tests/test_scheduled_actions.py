"""
test_scheduled_actions.py — Unit Tests for Polymorphic Scheduled Bot Actions,
ToolJobExecutor, AgentLoopJobExecutor, Expiration, and Human Reminder Isolation.
"""

from collections.abc import Generator
from datetime import datetime
from typing import Any
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

import pytest

from src.agent.proactive import handle_proactive_scheduler_tick
from src.memory.store import add_task, list_tasks, load_memory, save_memory, update_task
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
async def test_scheduled_action_tool_job_message_dispatch() -> None:
    """Verify that a scheduled message with ToolJobExecutor dispatches directly at due time and auto-completes."""
    mock_client = AsyncMock(spec=WahaClient)

    # Add scheduled bot action
    add_task(
        title="Kirim pesan test",
        due="2026-08-27 15:20 WIB",
        assignee="Helmis",
        task_type="scheduled_action",
        job={
            "kind": "tool",
            "tool_name": "send_whatsapp_message",
            "tool_args": {
                "recipient": "Gilang",
                "text": "palpale palpale, ini test chat",
            },
        },
    )

    # 1. Before due time (15:10 WIB) -> should NOT dispatch
    mock_dt_early = datetime(2026, 8, 27, 15, 10, 0, tzinfo=TZ)
    with patch("src.agent.proactive.datetime") as mock_datetime:
        mock_datetime.now.return_value = mock_dt_early
        await handle_proactive_scheduler_tick(mock_client)

    assert not mock_client.send_message.called
    mem = load_memory()
    assert mem["tasks"][0]["status"] == "pending"

    # 2. At due time (15:20 WIB) -> should execute tool and mark completed
    mock_dt_due = datetime(2026, 8, 27, 15, 20, 0, tzinfo=TZ)
    with patch("src.agent.proactive.datetime") as mock_datetime:
        mock_datetime.now.return_value = mock_dt_due
        await handle_proactive_scheduler_tick(mock_client)

    assert mock_client.send_message.called
    call_args = mock_client.send_message.call_args[1]
    assert "palpale palpale, ini test chat" in call_args["text"]

    mem = load_memory()
    task = mem["tasks"][0]
    assert task["status"] == "completed"
    assert task["execution_status"] == "dispatched"
    assert task.get("completed_at") is not None


@pytest.mark.asyncio
async def test_scheduled_action_fallback_extractor() -> None:
    """Verify that a task with title 'Kirim chat: ...' and assignee Helmis executes fallback message dispatch."""
    mock_client = AsyncMock(spec=WahaClient)

    add_task(
        title='Kirim chat: "Selamat sore sayang"',
        due="2026-08-27 16:00 WIB",
        assignee="Helmis",
        task_type="scheduled_action",
    )

    mock_dt = datetime(2026, 8, 27, 16, 0, 0, tzinfo=TZ)
    with patch("src.agent.proactive.datetime") as mock_datetime:
        mock_datetime.now.return_value = mock_dt
        await handle_proactive_scheduler_tick(mock_client)

    assert mock_client.send_message.called
    call_args = mock_client.send_message.call_args[1]
    assert "Selamat sore sayang" in call_args["text"]

    mem = load_memory()
    assert mem["tasks"][0]["status"] == "completed"


@pytest.mark.asyncio
async def test_scheduled_action_overdue_expiration() -> None:
    """Verify that scheduled actions overdue by > 2 hours are marked expired and NOT dispatched."""
    mock_client = AsyncMock(spec=WahaClient)

    # Task was due at 10:00 WIB
    add_task(
        title="Kirim reminder lama",
        due="2026-08-27 10:00 WIB",
        assignee="Helmis",
        task_type="scheduled_action",
        job={
            "kind": "tool",
            "tool_name": "send_whatsapp_message",
            "tool_args": {"recipient": "Gilang", "text": "stale message"},
        },
    )

    # Current time is 15:00 WIB (>2 hours overdue)
    mock_dt = datetime(2026, 8, 27, 15, 0, 0, tzinfo=TZ)
    with patch("src.agent.proactive.datetime") as mock_datetime:
        mock_datetime.now.return_value = mock_dt
        await handle_proactive_scheduler_tick(mock_client)

    assert not mock_client.send_message.called
    mem = load_memory()
    task = mem["tasks"][0]
    assert task["status"] == "expired"
    assert task["execution_status"] == "expired"


@pytest.mark.asyncio
async def test_human_reminder_still_triggers_lead_and_due_reminders() -> None:
    """Verify that human tasks (assignee=Gilang) still trigger Stage 1 lead buffer and Stage 2 deadline alerts."""
    mock_client = AsyncMock(spec=WahaClient)

    # Human task due at 18:00 with 60m lead time
    add_task(
        title="Kerjakan Tugas AI",
        due="2026-08-27 18:00 WIB",
        assignee="Gilang",
        priority="normal",
        lead_time_minutes=60,
        task_type="reminder",
    )

    # 1. At 17:05 (inside 60m kickoff buffer) -> should send preparation ping
    mock_dt_lead = datetime(2026, 8, 27, 17, 5, 0, tzinfo=TZ)
    with patch("src.agent.proactive.datetime") as mock_datetime:
        mock_datetime.now.return_value = mock_dt_lead
        await handle_proactive_scheduler_tick(mock_client)

    assert mock_client.send_message.called
    call_args = mock_client.send_message.call_args[1]
    assert "pengingat persiapan: deadline *Kerjakan Tugas AI*" in call_args["text"]

    mem = load_memory()
    task = mem["tasks"][0]
    assert task["status"] == "pending"
    assert task["kickoff_reminded"] is True
    assert task["due_reminded"] is False

    mock_client.send_message.reset_mock()

    # 2. At 18:00 (due time) -> should send final deadline reminder
    mock_dt_due = datetime(2026, 8, 27, 18, 0, 0, tzinfo=TZ)
    with patch("src.agent.proactive.datetime") as mock_datetime:
        mock_datetime.now.return_value = mock_dt_due
        await handle_proactive_scheduler_tick(mock_client)

    assert mock_client.send_message.called
    call_args = mock_client.send_message.call_args[1]
    assert "pengingat deadline: *Kerjakan Tugas AI*" in call_args["text"]

    mem = load_memory()
    task = mem["tasks"][0]
    assert task["status"] == "pending"
    assert task["due_reminded"] is True


@pytest.mark.asyncio
async def test_list_tasks_task_type_filtering() -> None:
    """Verify that list_tasks allows filtering by task_type."""
    add_task(title="Beli Kopi", due="2026-08-27 10:00 WIB", assignee="Gilang", task_type="reminder")
    add_task(title="Kirim File", due="2026-08-27 11:00 WIB", assignee="Helmis", task_type="scheduled_action")

    reminders = list_tasks(task_type="reminder")
    assert len(reminders) == 1
    assert reminders[0]["title"] == "Beli Kopi"

    actions = list_tasks(task_type="scheduled_action")
    assert len(actions) == 1
    assert actions[0]["title"] == "Kirim File"

    all_items = list_tasks(task_type="all")
    assert len(all_items) == 2


@pytest.mark.asyncio
async def test_near_horizon_timer_direct_execution() -> None:
    """Verify that _delayed_action_runner executes and marks task completed when timer fires."""
    mock_client = AsyncMock(spec=WahaClient)

    add_task(
        title="Kirim cepat",
        due="2026-08-27 15:01 WIB",
        assignee="Helmis",
        task_type="scheduled_action",
        job={
            "kind": "tool",
            "tool_name": "send_whatsapp_message",
            "tool_args": {"recipient": "Gilang", "text": "pesan cepat"},
        },
    )

    from src.agent.proactive import _delayed_action_runner
    with patch("asyncio.sleep", AsyncMock()):
        await _delayed_action_runner("Kirim cepat", 0.01, mock_client)

    assert mock_client.send_message.called
    mem = load_memory()
    assert mem["tasks"][0]["status"] == "completed"
    assert mem["tasks"][0]["execution_status"] == "dispatched"
