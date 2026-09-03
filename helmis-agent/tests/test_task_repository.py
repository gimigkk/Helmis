import time
from pathlib import Path

from src.memory.task_repository import TaskRepository


def _task(task_id: str = "task-1") -> dict[str, object]:
    return {
        "task_id": task_id,
        "title": "Test task",
        "identity_key": "test task",
        "status": "pending",
        "version": 1,
    }


def test_occurrence_generation_is_idempotent(tmp_path: Path) -> None:
    repo = TaskRepository(str(tmp_path / "helmis.db"))
    repo.load_or_migrate([_task()])

    first = repo.ensure_occurrence("task-1", 100.0, "occ-1", 1.0)
    second = repo.ensure_occurrence("task-1", 100.0, "occ-other", 2.0)

    assert first["occurrence_id"] == "occ-1"
    assert second["occurrence_id"] == "occ-1"
    assert len(repo.claim_due_occurrences(100.0, 30.0, "worker-a")) == 1
    assert repo.claim_due_occurrences(100.0, 30.0, "worker-b") == []
    assert repo.complete_occurrence("occ-1", "worker-b") is False
    assert repo.complete_occurrence("occ-1", "worker-a") is True


def test_occurrence_can_be_released_for_retry(tmp_path: Path) -> None:
    repo = TaskRepository(str(tmp_path / "helmis.db"))
    repo.load_or_migrate([_task()])
    repo.ensure_occurrence("task-1", 100.0, "occ-1", 1.0)

    assert repo.claim_occurrence("occ-1", 100.0, 30.0, "worker-a") is not None
    assert repo.release_occurrence("occ-1", "worker-b") is False
    assert repo.release_occurrence("occ-1", "worker-a") is True
    assert repo.claim_occurrence("occ-1", 101.0, 30.0, "worker-b") is not None


def test_existing_database_gains_new_outbox_columns(tmp_path: Path) -> None:
    db_path = tmp_path / "helmis.db"
    repo = TaskRepository(str(db_path))
    # Simulate a pre-v3 database by dropping the column added in v3.
    with repo._connect() as connection:
        connection.execute("DROP TABLE outbox")
        connection.executescript(
            """
            CREATE TABLE outbox (
                outbox_id TEXT PRIMARY KEY,
                idempotency_key TEXT NOT NULL UNIQUE,
                occurrence_id TEXT,
                target_chat TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                state TEXT NOT NULL DEFAULT 'pending',
                claim_token TEXT,
                claim_until REAL,
                attempts INTEGER NOT NULL DEFAULT 0,
                provider_message_id TEXT,
                last_error TEXT,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            );
            INSERT OR REPLACE INTO repository_meta(key, value) VALUES ('schema_version', '2');
            """
        )

    reopened = TaskRepository(str(db_path))

    with reopened._connect() as connection:
        columns = {str(row[1]) for row in connection.execute("PRAGMA table_info(outbox)")}
        stamp = connection.execute(
            "SELECT value FROM repository_meta WHERE key='schema_version'"
        ).fetchone()
    assert "next_retry_at" in columns
    assert stamp["value"] == "3"
    reopened.enqueue_outbox("out-1", "event-1", "chat@c.us", {"text": "hi"}, 1.0)
    assert reopened.claim_outbox(1.0, 30.0, "worker-a")


def test_generic_schedule_and_reminder_policy_records(tmp_path: Path) -> None:
    repo = TaskRepository(str(tmp_path / "helmis.db"))
    repo.load_or_migrate([_task()])

    schedule = repo.create_schedule(
        "schedule-1",
        task_id="task-1",
        starts_at=100.0,
        ends_at=160.0,
        timezone="Asia/Jakarta",
        recurrence={"type": "weekly", "weekdays": [0], "time": "09:00"},
        owner="Gilang",
        source="calendar",
        location="Campus",
    )
    policy = repo.create_reminder_policy(
        "policy-1",
        schedule_id="schedule-1",
        owner="Gilang",
        lead_minutes=30,
        repeat_interval_minutes=10,
        max_repeats=3,
        acknowledgment_required=True,
        stand_down_after_minutes=60,
    )

    assert repo.list_schedules(task_id="task-1") == [schedule]
    assert repo.list_reminder_policies(schedule_id="schedule-1") == [policy]


def test_reminder_policy_requires_domain_reference(tmp_path: Path) -> None:
    repo = TaskRepository(str(tmp_path / "helmis.db"))

    try:
        repo.create_reminder_policy("policy-1")
    except ValueError as exc:
        assert "reference" in str(exc)
    else:
        raise AssertionError("unscoped reminder policy should be rejected")


def test_outbox_is_deduplicated_by_idempotency_key(tmp_path: Path) -> None:
    repo = TaskRepository(str(tmp_path / "helmis.db"))

    first = repo.enqueue_outbox("out-1", "event-1", "chat@c.us", {"text": "hello"}, 1.0)
    second = repo.enqueue_outbox("out-2", "event-1", "other@c.us", {"text": "changed"}, 2.0)

    assert first["outbox_id"] == "out-1"
    assert second["outbox_id"] == "out-1"
    assert second["target_chat"] == "chat@c.us"


def test_outbox_claim_and_delivery_attempt_are_owned_by_worker(tmp_path: Path) -> None:
    repo = TaskRepository(str(tmp_path / "helmis.db"))
    repo.enqueue_outbox("out-1", "event-1", "chat@c.us", {"text": "hello"}, time.time())

    claimed = repo.claim_outbox(time.time(), 30.0, "worker-a")
    assert len(claimed) == 1
    assert repo.claim_outbox(time.time(), 30.0, "worker-b") == []
    assert repo.record_delivery_attempt("out-1", "worker-b", "delivered") is False
    assert repo.record_delivery_attempt("out-1", "worker-a", "delivered", provider_message_id="m-1")


def test_specific_outbox_claim_does_not_consume_another_job(tmp_path: Path) -> None:
    repo = TaskRepository(str(tmp_path / "helmis.db"))
    repo.enqueue_outbox("old", "old-event", "chat@c.us", {"text": "old"}, 1.0)
    repo.enqueue_outbox("new", "new-event", "chat@c.us", {"text": "new"}, 2.0)

    claimed = repo.claim_outbox_id("new", 3.0, 30.0, "worker-a")

    assert claimed is not None
    assert claimed["outbox_id"] == "new"
    assert repo.claim_outbox(3.0, 30.0, "worker-b") == [{"outbox_id": "old", "idempotency_key": "old-event", "occurrence_id": None, "target_chat": "chat@c.us", "payload_json": '{"text": "old"}', "state": "claimed", "claim_token": "worker-b", "claim_until": 33.0, "attempts": 1, "provider_message_id": None, "last_error": None, "next_retry_at": None, "created_at": 1.0, "updated_at": 3.0}]


def test_failed_delivery_backs_off_then_retries(tmp_path: Path) -> None:
    repo = TaskRepository(str(tmp_path / "helmis.db"), max_delivery_attempts=5)
    repo.enqueue_outbox("out-1", "event-1", "chat@c.us", {"text": "hello"}, 1.0)

    repo.claim_outbox(10.0, 30.0, "worker-a")
    repo.record_delivery_attempt(
        "out-1", "worker-a", "failed", error="provider down", now=10.0
    )
    row = repo.claim_outbox_id("out-1", 11.0, 30.0, "worker-b")
    assert row is None  # backoff window active

    retried = repo.claim_outbox_id("out-1", 60.0, 30.0, "worker-b")
    assert retried is not None
    assert retried["attempts"] == 2
    repo.record_delivery_attempt("out-1", "worker-b", "delivered", provider_message_id="m-1")
    with repo._connect() as connection:
        state = connection.execute(
            "SELECT state, provider_message_id, next_retry_at FROM outbox WHERE outbox_id='out-1'"
        ).fetchone()
    assert state["state"] == "delivered"
    assert state["provider_message_id"] == "m-1"
    assert state["next_retry_at"] is None


def test_exhausted_retries_become_dead(tmp_path: Path) -> None:
    repo = TaskRepository(str(tmp_path / "helmis.db"), max_delivery_attempts=2)
    repo.enqueue_outbox("out-1", "event-1", "chat@c.us", {"text": "hello"}, 1.0)

    first = repo.claim_outbox_id("out-1", 1.0, 30.0, "worker-a")
    assert first is not None
    repo.record_delivery_attempt("out-1", "worker-a", "failed", error="down", now=1.0)

    second = repo.claim_outbox_id("out-1", 60.0, 30.0, "worker-b")
    assert second is not None
    repo.record_delivery_attempt("out-1", "worker-b", "failed", error="still down")

    assert repo.claim_outbox_id("out-1", 3600.0, 30.0, "worker-c") is None
    assert repo.claim_outbox(3600.0, 30.0, "worker-c") == []
    with repo._connect() as connection:
        row = connection.execute("SELECT state FROM outbox WHERE outbox_id='out-1'").fetchone()
    assert row["state"] == "dead"
