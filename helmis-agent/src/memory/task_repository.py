"""SQLite/WAL repository for structured task state.

The JSON memory file remains a compatibility mirror for legacy callers and for
non-task records. Task reads and mutations use this repository so selector
resolution, optimistic version checks, and commits can share one transaction.
"""

from __future__ import annotations

import copy
import json
import os
import sqlite3
import time
from collections.abc import Callable, Iterable
from typing import Any

_SCHEMA_VERSION = 3


class TaskRepository:
    """Small transactional repository for task records."""

    def __init__(self, database_path: str, *, max_delivery_attempts: int = 5) -> None:
        self.database_path = database_path
        self._max_delivery_attempts = max(1, int(max_delivery_attempts))
        os.makedirs(os.path.dirname(database_path), exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=30.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 30000")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = NORMAL")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS repository_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS tasks (
                    task_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    identity_key TEXT NOT NULL,
                    status TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    record_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS schedules (
                    schedule_id TEXT PRIMARY KEY,
                    task_id TEXT,
                    owner TEXT NOT NULL DEFAULT '',
                    timezone TEXT NOT NULL,
                    starts_at REAL NOT NULL,
                    ends_at REAL,
                    recurrence_json TEXT,
                    source TEXT NOT NULL DEFAULT 'user',
                    location TEXT,
                    status TEXT NOT NULL DEFAULT 'active',
                    version INTEGER NOT NULL,
                    record_json TEXT NOT NULL,
                    FOREIGN KEY(task_id) REFERENCES tasks(task_id) ON DELETE SET NULL
                );
                CREATE TABLE IF NOT EXISTS reminder_policies (
                    policy_id TEXT PRIMARY KEY,
                    schedule_id TEXT,
                    task_id TEXT,
                    owner TEXT NOT NULL DEFAULT '',
                    lead_minutes INTEGER NOT NULL DEFAULT 0,
                    repeat_interval_minutes INTEGER,
                    max_repeats INTEGER NOT NULL DEFAULT 0,
                    acknowledgment_required INTEGER NOT NULL DEFAULT 0,
                    stand_down_after_minutes INTEGER,
                    version INTEGER NOT NULL,
                    record_json TEXT NOT NULL,
                    FOREIGN KEY(schedule_id) REFERENCES schedules(schedule_id) ON DELETE CASCADE,
                    FOREIGN KEY(task_id) REFERENCES tasks(task_id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_schedules_start ON schedules(status, starts_at);
                CREATE INDEX IF NOT EXISTS idx_policies_task ON reminder_policies(task_id);
                CREATE TABLE IF NOT EXISTS task_occurrences (
                    occurrence_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    scheduled_for REAL NOT NULL,
                    stage TEXT NOT NULL DEFAULT 'default',
                    state TEXT NOT NULL DEFAULT 'pending',
                    claim_token TEXT,
                    claim_until REAL,
                    created_at REAL NOT NULL,
                    UNIQUE(task_id, scheduled_for, stage),
                    FOREIGN KEY(task_id) REFERENCES tasks(task_id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_occurrences_due
                    ON task_occurrences(state, scheduled_for);
                CREATE TABLE IF NOT EXISTS outbox (
                    outbox_id TEXT PRIMARY KEY,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    occurrence_id TEXT,
                    target_chat TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    state TEXT NOT NULL DEFAULT 'pending',
                    claim_token TEXT,
                    claim_until REAL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    next_retry_at REAL,
                    provider_message_id TEXT,
                    last_error TEXT,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    FOREIGN KEY(occurrence_id) REFERENCES task_occurrences(occurrence_id) ON DELETE SET NULL
                );
                CREATE INDEX IF NOT EXISTS idx_outbox_claim
                    ON outbox(state, claim_until, created_at);
                CREATE TABLE IF NOT EXISTS delivery_attempts (
                    attempt_id TEXT PRIMARY KEY,
                    outbox_id TEXT NOT NULL,
                    attempt_number INTEGER NOT NULL,
                    state TEXT NOT NULL,
                    provider_message_id TEXT,
                    error TEXT,
                    created_at REAL NOT NULL,
                    FOREIGN KEY(outbox_id) REFERENCES outbox(outbox_id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS activity_log (
                    activity_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    summary TEXT NOT NULL,
                    created_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS processed_messages (
                    message_id TEXT PRIMARY KEY,
                    first_seen_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_tasks_identity ON tasks(identity_key);
                CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
                """
            )
            connection.execute(
                "INSERT OR REPLACE INTO repository_meta(key, value) VALUES (?, ?)",
                ("schema_version", str(_SCHEMA_VERSION)),
            )
            self._migrate_columns(connection)
            self._migrate_occurrence_stage(connection)

    @staticmethod
    def _migrate_columns(connection: sqlite3.Connection) -> None:
        """Add columns introduced after a database was first created.

        ``CREATE TABLE IF NOT EXISTS`` never alters an existing table, so
        columns added in later schema versions are applied idempotently here.
        """
        outbox_columns = {
            str(row[1]) for row in connection.execute("PRAGMA table_info(outbox)")
        }
        if "next_retry_at" not in outbox_columns:
            connection.execute("ALTER TABLE outbox ADD COLUMN next_retry_at REAL")

    @staticmethod
    def _migrate_occurrence_stage(connection: sqlite3.Connection) -> None:
        """Add stage identity while preserving pre-stage occurrence rows."""
        columns = {str(row[1]) for row in connection.execute("PRAGMA table_info(task_occurrences)")}
        if "stage" in columns:
            return
        connection.execute("PRAGMA foreign_keys=OFF")
        connection.execute(
            """CREATE TABLE task_occurrences_v3 (
                occurrence_id TEXT PRIMARY KEY,
                task_id TEXT NOT NULL,
                scheduled_for REAL NOT NULL,
                stage TEXT NOT NULL DEFAULT 'default',
                state TEXT NOT NULL DEFAULT 'pending',
                claim_token TEXT,
                claim_until REAL,
                created_at REAL NOT NULL,
                UNIQUE(task_id, scheduled_for, stage),
                FOREIGN KEY(task_id) REFERENCES tasks(task_id) ON DELETE CASCADE
            )"""
        )
        connection.execute(
            """INSERT INTO task_occurrences_v3
               (occurrence_id, task_id, scheduled_for, stage, state, claim_token, claim_until, created_at)
               SELECT occurrence_id, task_id, scheduled_for, 'default', state, claim_token, claim_until, created_at
               FROM task_occurrences"""
        )
        connection.execute("DROP TABLE task_occurrences")
        connection.execute("ALTER TABLE task_occurrences_v3 RENAME TO task_occurrences")
        connection.execute(
            """CREATE UNIQUE INDEX IF NOT EXISTS uq_occurrences_task_time_stage
               ON task_occurrences(task_id, scheduled_for, stage)"""
        )
        connection.execute("PRAGMA foreign_keys=ON")

    @staticmethod
    def _row_to_task(row: sqlite3.Row) -> dict[str, Any]:
        try:
            record = json.loads(str(row["record_json"]))
        except (TypeError, json.JSONDecodeError):
            record = {}
        if not isinstance(record, dict):
            record = {}
        record["task_id"] = str(row["task_id"])
        record["title"] = str(row["title"])
        record["identity_key"] = str(row["identity_key"])
        record["status"] = str(row["status"])
        record["version"] = int(row["version"])
        return record

    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> dict[str, Any]:
        try:
            record = json.loads(str(row["record_json"]))
        except (TypeError, json.JSONDecodeError):
            record = {}
        if not isinstance(record, dict):
            record = {}
        record["version"] = int(row["version"])
        return record

    def create_schedule(
        self,
        schedule_id: str,
        *,
        starts_at: float,
        timezone: str,
        task_id: str | None = None,
        ends_at: float | None = None,
        recurrence: dict[str, Any] | None = None,
        owner: str = "",
        source: str = "user",
        location: str | None = None,
    ) -> dict[str, Any]:
        """Persist a generic timezone-aware schedule/event record."""
        record = {
            "schedule_id": schedule_id,
            "task_id": task_id,
            "starts_at": starts_at,
            "ends_at": ends_at,
            "timezone": timezone,
            "recurrence": recurrence,
            "owner": owner,
            "source": source,
            "location": location,
            "status": "active",
            "version": 1,
        }
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO schedules
                   (schedule_id, task_id, owner, timezone, starts_at, ends_at,
                    recurrence_json, source, location, status, version, record_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', 1, ?)""",
                (schedule_id, task_id, owner, timezone, starts_at, ends_at,
                 json.dumps(recurrence, ensure_ascii=False, sort_keys=True) if recurrence else None,
                 source, location, json.dumps(record, ensure_ascii=False, sort_keys=True)),
            )
        return record

    def list_schedules(self, *, task_id: str | None = None, active_only: bool = True) -> list[dict[str, Any]]:
        """List generic schedule/event records by task and lifecycle status."""
        clauses = []
        params: list[Any] = []
        if task_id is not None:
            clauses.append("task_id=?")
            params.append(task_id)
        if active_only:
            clauses.append("status='active'")
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM schedules{where} ORDER BY starts_at", params
            ).fetchall()
        return [self._row_to_record(row) for row in rows]

    def create_reminder_policy(
        self,
        policy_id: str,
        *,
        task_id: str | None = None,
        schedule_id: str | None = None,
        owner: str = "",
        lead_minutes: int = 0,
        repeat_interval_minutes: int | None = None,
        max_repeats: int = 0,
        acknowledgment_required: bool = False,
        stand_down_after_minutes: int | None = None,
    ) -> dict[str, Any]:
        """Persist a generic reminder policy without domain-specific branches."""
        if task_id is None and schedule_id is None:
            raise ValueError("A reminder policy must reference a task or schedule")
        record = {
            "policy_id": policy_id, "task_id": task_id, "schedule_id": schedule_id,
            "owner": owner, "lead_minutes": max(0, int(lead_minutes)),
            "repeat_interval_minutes": repeat_interval_minutes,
            "max_repeats": max(0, int(max_repeats)),
            "acknowledgment_required": bool(acknowledgment_required),
            "stand_down_after_minutes": stand_down_after_minutes, "version": 1,
        }
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO reminder_policies
                   (policy_id, schedule_id, task_id, owner, lead_minutes,
                    repeat_interval_minutes, max_repeats, acknowledgment_required,
                    stand_down_after_minutes, version, record_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)""",
                (policy_id, schedule_id, task_id, owner, record["lead_minutes"],
                 repeat_interval_minutes, record["max_repeats"],
                 int(record["acknowledgment_required"]), stand_down_after_minutes,
                 json.dumps(record, ensure_ascii=False, sort_keys=True)),
            )
        return record

    def list_reminder_policies(
        self, *, task_id: str | None = None, schedule_id: str | None = None
    ) -> list[dict[str, Any]]:
        clauses = []
        params: list[Any] = []
        if task_id is not None:
            clauses.append("task_id=?")
            params.append(task_id)
        if schedule_id is not None:
            clauses.append("schedule_id=?")
            params.append(schedule_id)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._connect() as connection:
            rows = connection.execute(f"SELECT * FROM reminder_policies{where} ORDER BY policy_id", params).fetchall()
        return [self._row_to_record(row) for row in rows]

    @staticmethod
    def _task_values(task: dict[str, Any]) -> tuple[str, str, str, str, int, str]:
        task_id = str(task.get("task_id") or "")
        if not task_id:
            raise ValueError("Task records must have a task_id")
        title = str(task.get("title") or "")
        identity = str(task.get("identity_key") or "")
        status = str(task.get("status") or "pending")
        version = max(1, int(task.get("version") or 1))
        record = dict(task)
        record["task_id"] = task_id
        record["title"] = title
        record["identity_key"] = identity
        record["status"] = status
        record["version"] = version
        return task_id, title, identity, status, version, json.dumps(record, ensure_ascii=False)

    def _all_tasks(self, connection: sqlite3.Connection) -> list[dict[str, Any]]:
        rows = connection.execute(
            "SELECT task_id, title, identity_key, status, version, record_json "
            "FROM tasks ORDER BY rowid"
        ).fetchall()
        return [self._row_to_task(row) for row in rows]

    def load_or_migrate(self, legacy_tasks: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
        """Import normalized legacy rows once, then read tasks from SQLite."""
        with self._connect() as connection:
            migrated = connection.execute(
                "SELECT value FROM repository_meta WHERE key = ?",
                ("legacy_tasks_migrated",),
            ).fetchone()
            if migrated is None:
                for task in legacy_tasks:
                    values = self._task_values(task)
                    connection.execute(
                        """INSERT OR IGNORE INTO tasks
                           (task_id, title, identity_key, status, version, record_json)
                           VALUES (?, ?, ?, ?, ?, ?)""",
                        values,
                    )
                connection.execute(
                    "INSERT INTO repository_meta(key, value) VALUES (?, ?)",
                    ("legacy_tasks_migrated", "1"),
                )
            return self._all_tasks(connection)

    def list_tasks(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            return self._all_tasks(connection)

    def fetch_tickable_tasks(self) -> list[dict[str, Any]]:
        """Return non-terminal tasks eligible for scheduler evaluation."""
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT task_id, title, identity_key, status, version, record_json
                   FROM tasks
                   WHERE status NOT IN ('completed', 'failed', 'expired')
                   ORDER BY rowid"""
            ).fetchall()
            return [self._row_to_task(row) for row in rows]

    def update_task_fields(
        self,
        task_id: str,
        fields: dict[str, Any],
        *,
        expected_version: int | None = None,
    ) -> dict[str, Any]:
        """Update one task by ID atomically, optionally enforcing its version."""
        with self._connect() as connection:
            row = connection.execute(
                """SELECT task_id, title, identity_key, status, version, record_json
                   FROM tasks WHERE task_id = ?""",
                (task_id,),
            ).fetchone()
            if row is None:
                return {"outcome": "not_found", "affected_ids": []}
            before = self._row_to_task(row)
            current_version = int(before["version"])
            if expected_version is not None and current_version != expected_version:
                return {
                    "outcome": "conflict", "task_id": task_id,
                    "current_version": current_version,
                    "expected_version": expected_version, "before": before,
                }
            updated = copy.deepcopy(before)
            updated.update(copy.deepcopy(fields))
            updated["task_id"] = task_id
            updated["version"] = current_version + 1
            values = self._task_values(updated)
            cursor = connection.execute(
                """UPDATE tasks SET title=?, identity_key=?, status=?, version=?, record_json=?
                   WHERE task_id=? AND version=?""",
                (values[1], values[2], values[3], values[4], values[5], task_id, current_version),
            )
            if cursor.rowcount != 1:
                return {
                    "outcome": "conflict", "task_id": task_id,
                    "current_version": current_version,
                    "expected_version": expected_version, "before": before,
                }
            return {
                "outcome": "committed", "task_id": task_id,
                "affected_ids": [task_id], "before": before,
                "after": updated, "task": updated,
            }

    def upsert_pending_identity(
        self,
        payload: dict[str, Any],
        identity_matcher: Callable[[dict[str, Any]], bool],
        new_record_factory: Callable[[], dict[str, Any]],
    ) -> dict[str, Any]:
        """Update the first matching pending task or insert a new task.

        ``payload`` holds only the schedule fields an upsert may refresh;
        ``new_record_factory`` builds the full record for a fresh insert so
        system fields like ``created_at`` are never clobbered on update.
        """
        with self._connect() as connection:
            tasks = self._all_tasks(connection)
            existing = next(
                (candidate for candidate in tasks
                 if candidate.get("status") == "pending" and identity_matcher(candidate)),
                None,
            )
            if existing is not None:
                updated = copy.deepcopy(existing)
                task_id = str(updated["task_id"])
                old_version = int(updated.get("version") or 1)
                updated.update(copy.deepcopy(payload))
                updated["task_id"] = task_id
                updated["version"] = old_version + 1
                values = self._task_values(updated)
                cursor = connection.execute(
                    """UPDATE tasks SET title=?, identity_key=?, status=?, version=?, record_json=?
                       WHERE task_id=? AND version=?""",
                    (values[1], values[2], values[3], values[4], values[5], task_id, old_version),
                )
                if cursor.rowcount != 1:
                    raise RuntimeError("Task changed while being upserted")
                return updated

            task = new_record_factory()
            values = self._task_values(task)
            connection.execute(
                """INSERT INTO tasks
                   (task_id, title, identity_key, status, version, record_json)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                values,
            )
            return copy.deepcopy(task)

    def mutate_one(
        self,
        resolver: Callable[[list[dict[str, Any]]], list[dict[str, Any]]],
        expected_version: int | None,
        mutator: Callable[[dict[str, Any]], dict[str, Any]],
    ) -> dict[str, Any]:
        """Resolve and mutate one task inside one SQLite transaction."""
        with self._connect() as connection:
            tasks = self._all_tasks(connection)
            candidates = resolver(tasks)
            if not candidates:
                return {"outcome": "not_found", "count": 0, "affected_ids": []}
            if len(candidates) > 1:
                return {
                    "outcome": "ambiguous",
                    "count": len(candidates),
                    "candidates": [
                        {
                            "task_id": task.get("task_id"),
                            "title": task.get("title"),
                            "version": task.get("version", 1),
                        }
                        for task in candidates
                    ],
                }

            before = copy.deepcopy(candidates[0])
            current_version = int(before.get("version") or 1)
            if expected_version is not None and current_version != expected_version:
                return {
                    "outcome": "conflict",
                    "task_id": before.get("task_id"),
                    "current_version": current_version,
                    "expected_version": expected_version,
                    "before": before,
                }

            updated = mutator(copy.deepcopy(before))
            updated["task_id"] = before["task_id"]
            updated["version"] = current_version + 1
            values = self._task_values(updated)
            cursor = connection.execute(
                """UPDATE tasks SET title=?, identity_key=?, status=?, version=?, record_json=?
                   WHERE task_id=? AND version=?""",
                (
                    values[1],
                    values[2],
                    values[3],
                    values[4],
                    values[5],
                    str(before["task_id"]),
                    current_version,
                ),
            )
            if cursor.rowcount != 1:
                return {
                    "outcome": "conflict",
                    "task_id": before.get("task_id"),
                    "current_version": current_version,
                    "expected_version": expected_version,
                    "before": before,
                }
            return {
                "outcome": "committed",
                "task_id": updated.get("task_id"),
                "affected_ids": [updated.get("task_id")],
                "before": before,
                "after": copy.deepcopy(updated),
                "task": updated,
            }

    def ensure_occurrence(
        self, task_id: str, scheduled_for: float, occurrence_id: str, created_at: float,
        stage: str = "default",
    ) -> dict[str, Any]:
        """Create an occurrence once; repeated generation is idempotent."""
        with self._connect() as connection:
            connection.execute(
                """INSERT OR IGNORE INTO task_occurrences
                   (occurrence_id, task_id, scheduled_for, stage, created_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (occurrence_id, task_id, scheduled_for, stage, created_at),
            )
            row = connection.execute(
                """SELECT occurrence_id, task_id, scheduled_for, stage, state, claim_token, claim_until
                   FROM task_occurrences WHERE task_id=? AND scheduled_for=? AND stage=?""",
                (task_id, scheduled_for, stage),
            ).fetchone()
            return dict(row) if row else {}

    def claim_due_occurrences(
        self, now: float, lease_seconds: float, claim_token: str, limit: int = 50
    ) -> list[dict[str, Any]]:
        """Claim due occurrences atomically, reclaiming expired leases."""
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute(
                """SELECT occurrence_id FROM task_occurrences
                   WHERE scheduled_for <= ?
                     AND (state='pending' OR (state='claimed' AND claim_until <= ?))
                   ORDER BY scheduled_for LIMIT ?""",
                (now, now, limit),
            ).fetchall()
            ids = [str(row["occurrence_id"]) for row in rows]
            for occurrence_id in ids:
                connection.execute(
                    """UPDATE task_occurrences SET state='claimed', claim_token=?, claim_until=?
                       WHERE occurrence_id=?""",
                    (claim_token, now + lease_seconds, occurrence_id),
                )
            if not ids:
                return []
            placeholders = ",".join("?" for _ in ids)
            claimed = connection.execute(
                f"SELECT * FROM task_occurrences WHERE occurrence_id IN ({placeholders})", ids
            ).fetchall()
            return [dict(row) for row in claimed]

    def claim_occurrence(
        self, occurrence_id: str, now: float, lease_seconds: float, claim_token: str
    ) -> dict[str, Any] | None:
        """Claim one occurrence without consuming unrelated due work."""
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute(
                """UPDATE task_occurrences SET state='claimed', claim_token=?, claim_until=?
                   WHERE occurrence_id=?
                     AND (state='pending' OR (state='claimed' AND claim_until <= ?))""",
                (claim_token, now + lease_seconds, occurrence_id, now),
            )
            if cursor.rowcount != 1:
                return None
            row = connection.execute(
                "SELECT * FROM task_occurrences WHERE occurrence_id=?", (occurrence_id,)
            ).fetchone()
            return dict(row) if row else None

    def complete_occurrence(self, occurrence_id: str, claim_token: str) -> bool:
        with self._connect() as connection:
            cursor = connection.execute(
                """UPDATE task_occurrences SET state='completed', claim_token=NULL, claim_until=NULL
                   WHERE occurrence_id=? AND state='claimed' AND claim_token=?""",
                (occurrence_id, claim_token),
            )
            return cursor.rowcount == 1

    def release_occurrence(self, occurrence_id: str, claim_token: str) -> bool:
        """Return a claimed occurrence to pending when execution must retry."""
        with self._connect() as connection:
            cursor = connection.execute(
                """UPDATE task_occurrences SET state='pending', claim_token=NULL, claim_until=NULL
                   WHERE occurrence_id=? AND state='claimed' AND claim_token=?""",
                (occurrence_id, claim_token),
            )
            return cursor.rowcount == 1

    def enqueue_outbox(
        self, outbox_id: str, idempotency_key: str, target_chat: str,
        payload: dict[str, Any], created_at: float, occurrence_id: str | None = None,
    ) -> dict[str, Any]:
        """Enqueue an outbound action exactly once by idempotency key."""
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        with self._connect() as connection:
            connection.execute(
                """INSERT OR IGNORE INTO outbox
                   (outbox_id, idempotency_key, occurrence_id, target_chat, payload_json, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (outbox_id, idempotency_key, occurrence_id, target_chat, encoded, created_at, created_at),
            )
            row = connection.execute(
                "SELECT * FROM outbox WHERE idempotency_key=?", (idempotency_key,)
            ).fetchone()
            return dict(row) if row else {}

    def claim_outbox(
        self, now: float, lease_seconds: float, claim_token: str, limit: int = 50
    ) -> list[dict[str, Any]]:
        """Claim retryable outbound actions for one worker.

        Rows become retryable when they are pending, their lease expired, or
        their backoff window elapsed. Dead rows are never claimed.
        """
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute(
                """SELECT outbox_id FROM outbox
                   WHERE (state='pending' OR (state='claimed' AND claim_until <= ?))
                     AND (next_retry_at IS NULL OR next_retry_at <= ?)
                   ORDER BY created_at LIMIT ?""",
                (now, now, limit),
            ).fetchall()
            ids = [str(row["outbox_id"]) for row in rows]
            for outbox_id in ids:
                connection.execute(
                    """UPDATE outbox SET state='claimed', claim_token=?, claim_until=?,
                       attempts=attempts+1, updated_at=? WHERE outbox_id=?""",
                    (claim_token, now + lease_seconds, now, outbox_id),
                )
            if not ids:
                return []
            placeholders = ",".join("?" for _ in ids)
            claimed = connection.execute(
                f"SELECT * FROM outbox WHERE outbox_id IN ({placeholders})", ids
            ).fetchall()
            return [dict(row) for row in claimed]

    def claim_outbox_id(
        self, outbox_id: str, now: float, lease_seconds: float, claim_token: str
    ) -> dict[str, Any] | None:
        """Claim one specific outbox row without consuming another worker's job."""
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute(
                """UPDATE outbox SET state='claimed', claim_token=?, claim_until=?,
                   attempts=attempts+1, updated_at=?
                   WHERE outbox_id=?
                     AND (state='pending' OR (state='claimed' AND claim_until <= ?))
                     AND (next_retry_at IS NULL OR next_retry_at <= ?)""",
                (claim_token, now + lease_seconds, now, outbox_id, now, now),
            )
            if cursor.rowcount != 1:
                return None
            row = connection.execute("SELECT * FROM outbox WHERE outbox_id=?", (outbox_id,)).fetchone()
            return dict(row) if row else None

    def record_delivery_attempt(
        self, outbox_id: str, claim_token: str, state: str,
        *, provider_message_id: str | None = None, error: str | None = None,
        now: float | None = None,
    ) -> bool:
        """Record a provider attempt and transition the claimed outbox row.

        Successful sends become ``delivered``. Failures are returned to
        ``pending`` with exponential backoff until ``max_attempts`` is
        reached, after which the row becomes ``dead`` and is never
        re-claimed. ``now`` is injectable for deterministic tests.
        """
        now = time.time() if now is None else now
        with self._connect() as connection:
            row = connection.execute(
                "SELECT attempts FROM outbox WHERE outbox_id=? AND claim_token=? AND state='claimed'",
                (outbox_id, claim_token),
            ).fetchone()
            if row is None:
                return False
            attempt_number = int(row["attempts"])
            connection.execute(
                """INSERT INTO delivery_attempts
                   (attempt_id, outbox_id, attempt_number, state, provider_message_id, error, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (f"{outbox_id}:{attempt_number}", outbox_id, attempt_number, state,
                 provider_message_id, error, now),
            )
            if state == "delivered":
                connection.execute(
                    """UPDATE outbox SET state='delivered', claim_token=NULL, claim_until=NULL,
                       next_retry_at=NULL, provider_message_id=?, last_error=NULL, updated_at=?
                       WHERE outbox_id=? AND claim_token=?""",
                    (provider_message_id, now, outbox_id, claim_token),
                )
                return True
            max_attempts = self._max_delivery_attempts
            if attempt_number >= max_attempts:
                connection.execute(
                    """UPDATE outbox SET state='dead', claim_token=NULL, claim_until=NULL,
                       next_retry_at=NULL, last_error=?, updated_at=?
                       WHERE outbox_id=? AND claim_token=?""",
                    (error, now, outbox_id, claim_token),
                )
            else:
                backoff = min(600.0, 30.0 * (2 ** (attempt_number - 1)))
                connection.execute(
                    """UPDATE outbox SET state='pending', claim_token=NULL, claim_until=NULL,
                       next_retry_at=?, last_error=?, updated_at=?
                       WHERE outbox_id=? AND claim_token=?""",
                    (now + backoff, error, now, outbox_id, claim_token),
                )
            return True

    def delete_matching(
        self,
        resolver: Callable[[list[dict[str, Any]]], list[dict[str, Any]]],
    ) -> dict[str, Any]:
        """Delete an explicitly resolved set inside one transaction."""
        with self._connect() as connection:
            tasks = self._all_tasks(connection)
            matches = resolver(tasks)
            if not matches:
                return {
                    "outcome": "not_found",
                    "deleted_count": 0,
                    "affected_ids": [],
                    "deleted": [],
                }
            ids = [str(task["task_id"]) for task in matches]
            connection.executemany("DELETE FROM tasks WHERE task_id = ?", [(task_id,) for task_id in ids])
            return {
                "outcome": "committed",
                "deleted_count": len(ids),
                "affected_ids": ids,
                "deleted": [
                    {"task_id": task.get("task_id"), "title": task.get("title")}
                    for task in matches
                ],
            }

    def register_seen_message(
        self,
        message_id: str,
        *,
        window_seconds: float = 3600.0,
        now: float | None = None,
    ) -> bool:
        """Durably mark a message ID as processed; True if it is a replay.

        Survives restarts, unlike the in-memory 60s cache. Rows older than
        ``window_seconds`` are pruned opportunistically within the same
        transaction, so the table stays bounded.
        """
        message_id = str(message_id or "").strip()
        if not message_id:
            return False
        current = time.time() if now is None else float(now)
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM processed_messages WHERE first_seen_at <= ?",
                (current - window_seconds,),
            )
            row = connection.execute(
                "SELECT first_seen_at FROM processed_messages WHERE message_id = ?",
                (message_id,),
            ).fetchone()
            if row is not None:
                return True
            connection.execute(
                "INSERT INTO processed_messages (message_id, first_seen_at) VALUES (?, ?)",
                (message_id, current),
            )
            return False

    def list_processed_message_ids(self) -> list[str]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT message_id FROM processed_messages ORDER BY first_seen_at"
            ).fetchall()
            return [str(row[0]) for row in rows]
