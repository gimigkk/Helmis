"""
test_schedule_routing.py — Deterministic routing for schedule/policy questions.

Phase 2 gate: schedule questions resolve from durable schedule/policy records,
and tool results carry the record shape needed for grounded answers.
"""

import pytest

from src.memory.task_repository import TaskRepository
from src.tools.registry import execute_tool_call


@pytest.fixture()
def repo(sqlite_db) -> TaskRepository:
    return TaskRepository(str(sqlite_db / "helmis.db"))


@pytest.mark.asyncio
async def test_list_schedules_returns_committed_records(repo: TaskRepository) -> None:
    repo.create_schedule("s1", starts_at=1750000000.0, timezone="Asia/Jakarta", owner="Gilang")
    repo.create_schedule("s2", starts_at=1750003600.0, timezone="Asia/Jakarta", owner="Bunga")

    run_list = await execute_tool_call("list_schedules", {}, default_sender="Gilang")
    assert run_list["status"] == "success"
    assert run_list["count"] == 2
    ids = {s["schedule_id"] for s in run_list["schedules"]}
    assert ids == {"s1", "s2"}


@pytest.mark.asyncio
async def test_list_schedules_filters_by_task(repo: TaskRepository) -> None:
    repo.create_schedule("s-link", starts_at=1.0, timezone="Asia/Jakarta", task_id="t1")
    repo.create_schedule("s-free", starts_at=2.0, timezone="Asia/Jakarta")

    res = await execute_tool_call("list_schedules", {"task_id": "t1"}, default_sender="Gilang")
    assert res["count"] == 1
    assert res["schedules"][0]["schedule_id"] == "s-link"


@pytest.mark.asyncio
async def test_create_schedule_commits_record(repo: TaskRepository) -> None:
    res = await execute_tool_call(
        "create_schedule",
        {
            "starts_at": 1750000000.0,
            "timezone": "Asia/Jakarta",
            "owner": "Gilang",
            "recurrence": {"kind": "weekly", "weekdays": ["monday"]},
        },
        default_sender="Gilang",
    )
    assert res["status"] == "success"
    assert res["outcome"] == "committed"
    stored = repo.list_schedules()
    assert len(stored) == 1
    assert stored[0]["recurrence"]["kind"] == "weekly"


@pytest.mark.asyncio
async def test_create_schedule_rejects_missing_timezone() -> None:
    res = await execute_tool_call(
        "create_schedule",
        {"starts_at": 1750000000.0},
        default_sender="Gilang",
    )
    assert res["status"] == "error"
    assert "timezone" in res["error"]


@pytest.mark.asyncio
async def test_create_schedule_rejects_non_numeric_starts_at() -> None:
    res = await execute_tool_call(
        "create_schedule",
        {"starts_at": "besok pagi", "timezone": "Asia/Jakarta"},
        default_sender="Gilang",
    )
    assert res["status"] == "error"
    assert "starts_at" in res["error"]


@pytest.mark.asyncio
async def test_list_reminder_policies_scopes(sqlite_db) -> None:
    from src.memory.store import add_task

    task = add_task(title="Tugas B", due="besok 10:00", assignee="Gilang")
    task_id = task["task_id"]
    repo = TaskRepository(str(sqlite_db / "helmis.db"))
    repo.create_reminder_policy("p1", task_id=task_id, lead_minutes=30)
    repo.create_schedule("sx", starts_at=5.0, timezone="Asia/Jakarta")
    repo.create_reminder_policy("p2", schedule_id="sx", lead_minutes=60)

    by_task = await execute_tool_call("list_reminder_policies", {"task_id": task_id}, default_sender="Gilang")
    assert by_task["count"] == 1
    assert by_task["policies"][0]["policy_id"] == "p1"

    by_sched = await execute_tool_call("list_reminder_policies", {"schedule_id": "sx"}, default_sender="Gilang")
    assert by_sched["count"] == 1
    assert by_sched["policies"][0]["policy_id"] == "p2"


def test_schedule_tools_exposed_to_model_with_routing_description() -> None:
    from src.tools.schema import GEMINI_TOOLS

    decls = {d["name"]: d for d in GEMINI_TOOLS[0]["function_declarations"]}
    assert "list_schedules" in decls
    assert "jadwal" in decls["list_schedules"]["description"].lower()
