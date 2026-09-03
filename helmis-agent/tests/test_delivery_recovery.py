"""
test_delivery_recovery.py — Outbox drain lifecycle, crash/restart recovery,
provider-failure retries, and duplicate-send suppression.
"""

import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest

from src.agent.delivery import deliver_outbox_batch, run_outbox_drain_loop
from src.memory.task_repository import TaskRepository
from src.whatsapp.client import WahaClient


class FlakyClient:
    """Fake WAHA client that fails the first N sends, then succeeds."""

    def __init__(self, failures: int = 1) -> None:
        self.remaining_failures = failures
        self.sent: list[dict[str, Any]] = []

    async def send_message(self, chat_id: str, text: str) -> dict[str, Any]:
        self.sent.append({"chat_id": chat_id, "text": text})
        if self.remaining_failures > 0:
            self.remaining_failures -= 1
            raise RuntimeError("provider temporarily unavailable")
        return {"id": f"msg-{len(self.sent)}"}


@pytest.fixture()
def repo_db(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    db_path = tmp_path / "helmis.db"
    monkeypatch.setenv("HELMIS_DB_PATH", str(db_path))
    return db_path


@pytest.mark.asyncio
async def test_provider_failure_is_retried_by_drain_loop(
    monkeypatch: pytest.MonkeyPatch, repo_db: Path
) -> None:
    TaskRepository(str(repo_db))
    client = FlakyClient(failures=1)

    first = await deliver_outbox_batch(client)  # type: ignore[arg-type]
    assert first["failed"] == 0  # nothing enqueued yet

    repository = TaskRepository(str(repo_db))
    repository.enqueue_outbox("out-1", "event-1", "chat@c.us", {"text": "hello"}, 1.0)

    failed_round = await deliver_outbox_batch(client)  # type: ignore[arg-type]
    assert failed_round == {"claimed": 1, "delivered": 0, "failed": 1}
    assert len(client.sent) == 1

    # Backoff blocks an immediate retry claim; the drain loop simply waits.
    repository.enqueue_outbox("out-1", "event-1", "chat@c.us", {"text": "hello"}, 1.0)
    blocked = await deliver_outbox_batch(client)  # type: ignore[arg-type]
    assert blocked["claimed"] == 0

    # Simulate the backoff window elapsing before the next drain cycle.
    with repository._connect() as connection:
        connection.execute("UPDATE outbox SET next_retry_at=0 WHERE outbox_id='out-1'")
    recovered = await deliver_outbox_batch(client)  # type: ignore[arg-type]
    assert recovered == {"claimed": 1, "delivered": 1, "failed": 0}
    assert len(client.sent) == 2  # exactly one retry, no duplicates


@pytest.mark.asyncio
async def test_restart_recovers_claimed_rows_after_lease_expiry(
    monkeypatch: pytest.MonkeyPatch, repo_db: Path
) -> None:
    repository = TaskRepository(str(repo_db))
    repository.enqueue_outbox("out-1", "event-1", "chat@c.us", {"text": "hello"}, 1.0)

    # Simulate a crash mid-send: row left claimed with a stale lease.
    repository.claim_outbox(1.0, 30.0, "crashed-worker")

    # New process: a fresh client drains the expired lease exactly once.
    client = FlakyClient(failures=0)
    recovered = await deliver_outbox_batch(client)  # type: ignore[arg-type]
    assert recovered == {"claimed": 1, "delivered": 1, "failed": 0}

    # Restarting the drain again must not resend the delivered row.
    again = await deliver_outbox_batch(client)  # type: ignore[arg-type]
    assert again["claimed"] == 0
    assert len(client.sent) == 1


@pytest.mark.asyncio
async def test_drain_loop_stops_cleanly_on_cancellation(
    monkeypatch: pytest.MonkeyPatch, repo_db: Path
) -> None:
    TaskRepository(str(repo_db))
    client = AsyncMock(spec=WahaClient)
    task = asyncio.create_task(
        run_outbox_drain_loop(client, interval_seconds=0.01)  # type: ignore[arg-type]
    )
    await asyncio.sleep(0.05)
    assert not task.done()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not client.send_message.called
