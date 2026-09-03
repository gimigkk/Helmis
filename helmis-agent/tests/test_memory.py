"""
test_memory.py — Tests for persistent memory operations and time awareness.
"""

from datetime import datetime

import src.memory as memory


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

    completed = memory.complete_task_result(title="Meeting with client")
    assert completed["status"] == "applied"
    assert completed["task"]["status"] == "completed"
    assert "completed_at" in completed["task"]

    # Pending should now be 0, completed should be 1
    assert len(memory.list_tasks(status="pending")) == 0
    assert len(memory.list_tasks(status="completed")) == 1

    deleted = memory.bulk_delete_tasks(title_query="Meeting with client", status="all")
    assert deleted["outcome"] == "committed"
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
    memory.bulk_delete_tasks(title_query="Beli tiket")
    memory.bulk_delete_tasks(title_query="Jemput adik")
    memory.bulk_delete_tasks(title_query="Bayar tagihan")
    memory.bulk_delete_tasks(title_query="Meeting dokter")


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


def test_bulk_delete_reports_exact_scope() -> None:
    """Bulk delete is explicitly scoped: it deletes every match and reports the exact count."""
    memory.add_task("tugas", "Tomorrow 10:00 WIB")
    memory.add_task("tugas ekonomi syariah", "Tomorrow 12:00 WIB")
    memory.add_task("tugas statistik", "Tomorrow 14:00 WIB")

    result = memory.bulk_delete_tasks(title_query="tugas", status="all")
    assert result["outcome"] == "committed"
    assert result["deleted_count"] == 3
    assert sorted(d["title"] for d in result["deleted"]) == [
        "tugas", "tugas ekonomi syariah", "tugas statistik",
    ]
    assert memory.list_tasks(status="all") == []

    # Missing scope returns an error instead of wiping unscoped rows.
    assert memory.bulk_delete_tasks(status="all")["status"] == "error"


def test_parse_due_timestamp_indonesian_natural_expressions() -> None:
    now_ts = datetime.now(memory.TZ).timestamp()

    # Relative offsets
    ts_30m = memory.parse_due_timestamp("30 menit lagi")
    assert 1700 < (ts_30m - now_ts) < 1900

    ts_2h = memory.parse_due_timestamp("2 jam lagi")
    assert 7100 < (ts_2h - now_ts) < 7300

    # Indonesian hour + period
    ts_sore = memory.parse_due_timestamp("besok jam 3 sore")
    dt_sore = datetime.fromtimestamp(ts_sore, tz=memory.TZ)
    assert dt_sore.hour == 15
    assert dt_sore.minute == 0

    ts_malam = memory.parse_due_timestamp("besok jam 8 malam")
    dt_malam = datetime.fromtimestamp(ts_malam, tz=memory.TZ)
    assert dt_malam.hour == 20
    assert dt_malam.minute == 0

    # Setengah X
    ts_setengah = memory.parse_due_timestamp("besok setengah 4 sore")
    dt_setengah = datetime.fromtimestamp(ts_setengah, tz=memory.TZ)
    assert dt_setengah.hour == 15
    assert dt_setengah.minute == 30

    # Subuh
    ts_subuh = memory.parse_due_timestamp("besok subuh")
    dt_subuh = datetime.fromtimestamp(ts_subuh, tz=memory.TZ)
    assert dt_subuh.hour == 4
    assert dt_subuh.minute == 30

    # Maghrib
    ts_maghrib = memory.parse_due_timestamp("besok habis maghrib")
    dt_maghrib = datetime.fromtimestamp(ts_maghrib, tz=memory.TZ)
    assert dt_maghrib.hour == 18
    assert dt_maghrib.minute == 30


def test_task_identity_and_recurring_policy_are_persisted() -> None:
    first = memory.add_task(
        title="Weekly planning",
        due="2026-09-07 09:00 WIB",
        identity_key_value="planning-weekly",
        recurrence={"type": "weekly", "weekdays": ["monday"], "time": "09:00", "timezone": "Asia/Jakarta"},
        nag_policy={"interval_minutes": 5, "max_nags": 3},
    )
    second = memory.add_task(
        title="Planning reminder",
        due="2026-09-14 09:00 WIB",
        identity_key_value="planning-weekly",
        recurrence={"type": "weekly", "weekdays": ["monday"], "time": "09:00", "timezone": "Asia/Jakarta"},
        nag_policy={"interval_minutes": 5, "max_nags": 3},
    )
    assert first["task_id"] == second["task_id"]
    assert second["identity_key"] == "planning weekly"
    assert second["nag_policy"] == {"interval_minutes": 5, "max_nags": 3}
    assert second["recurrence"]["type"] == "weekly"


def test_empty_or_ambiguous_task_selectors_do_not_mutate() -> None:
    first = memory.add_task("Same logical work", "Tomorrow 10:00 WIB", identity_key_value="one")
    second = memory.add_task("Same logical work", "Tomorrow 11:00 WIB", identity_key_value="two")
    assert memory.complete_task_result(title="")["status"] == "error"
    assert memory.bulk_delete_tasks(status="pending")["status"] == "error"
    result = memory.complete_task_result(title="Same logical work")
    assert result["status"] == "ambiguous"
    assert result["count"] == 2
    assert memory.load_memory()["tasks"][0]["status"] == "pending"
    assert first["task_id"] != second["task_id"]


def test_exact_id_mutations_and_version_conflict_are_lossless() -> None:
    task = memory.add_task("Rename this task", "Tomorrow 10:00 WIB")
    task_id = task["task_id"]
    version = task["version"]

    updated = memory.update_task_result(
        task_id=task_id,
        expected_version=version,
        new_title="Renamed task",
    )
    assert updated["status"] == "applied"
    assert updated["outcome"] == "committed"
    assert updated["affected_ids"] == [task_id]
    assert updated["before"]["title"] == "Rename this task"
    assert updated["after"]["title"] == "Renamed task"

    conflict = memory.update_task_result(
        task_id=task_id,
        expected_version=version,
        new_due="Tomorrow 12:00 WIB",
    )
    assert conflict["status"] == "conflict"
    assert conflict["outcome"] == "conflict"
    assert memory.load_memory()["tasks"][0]["due"] == "Tomorrow 10:00 WIB"

    deleted = memory.bulk_delete_tasks(task_id=task_id)
    assert deleted["status"] == "applied"
    assert deleted["outcome"] == "committed"
    assert deleted["affected_ids"] == [task_id]
    assert memory.load_memory()["tasks"] == []


def test_update_result_preserves_not_found_and_ambiguous() -> None:
    memory.add_task("Repeated task", "Tomorrow 10:00 WIB", identity_key_value="first")
    memory.add_task("Repeated task", "Tomorrow 11:00 WIB", identity_key_value="second")

    ambiguous = memory.update_task_result(title="Repeated task", new_due="Tomorrow 12:00 WIB")
    assert ambiguous["status"] == "ambiguous"
    assert ambiguous["outcome"] == "ambiguous"
    assert ambiguous["count"] == 2

    missing = memory.update_task_result(task_id="missing-task", new_due="Tomorrow 12:00 WIB")
    assert missing["status"] == "not_found"
    assert missing["outcome"] == "not_found"
    assert missing["affected_ids"] == []


def test_weekly_and_interval_recurrence() -> None:
    from src.memory.recurrence import interval_next_occurrence, weekly_next_occurrence

    after = datetime(2026, 9, 2, 12, 0, tzinfo=memory.TZ)
    weekly = weekly_next_occurrence(["kamis"], "09:30", after, "Asia/Jakarta")
    assert weekly is not None
    assert weekly.weekday() == 3
    assert (weekly.hour, weekly.minute) == (9, 30)

    interval = interval_next_occurrence(5, "minutes", after, after)
    assert interval is not None
    assert (interval - after).total_seconds() == 300


def test_get_memory_context_summary_temporal_isolation() -> None:
    """Verify that get_memory_context_summary provides temporal anchoring without leaking tasks, notes, or contacts."""
    memory.add_task(title="Secret Task 123", due="Tomorrow 10:00 WIB")
    memory.add_person(name="Secret Contact", phone="+628111999888")
    memory.save_note(title="Secret Note", content="Secret note body")

    summary = memory.get_memory_context_summary()
    assert "Current Local Time" in summary
    assert "WIB" in summary
    # Assert no static database leaks into prompt
    assert "Secret Task 123" not in summary
    assert "Secret Contact" not in summary
    assert "Secret note body" not in summary
