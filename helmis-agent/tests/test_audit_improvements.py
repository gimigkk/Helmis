"""
test_audit_improvements.py — Verification for fixes discovered during deep log audit.
"""

import os
import pytest
from src.memory.store import (
    add_task,
    complete_task_result,
    _matching_tasks,
    save_note,
    get_note,
    list_notes,
    delete_note,
    bulk_delete_tasks,
)
from src.tools.notes import handle_search_notes
from src.agent.guardrails import inject_tool_directive
from src.tools.skills import _get_skills_dir, _get_skills_dirs


def test_matching_tasks_bidirectional_and_tokens() -> None:
    tasks = [
        {"task_id": "1", "title": "Sistem Operasi", "status": "pending"},
        {"task_id": "2", "title": "Absen Advance Excel", "status": "pending"},
        {"task_id": "3", "title": "Ngerjain LKP analgor", "status": "pending"},
    ]
    # Reverse substring: query is longer than stored title
    matched = _matching_tasks(tasks, title="Sistem Operasi (Praktikum)")
    assert len(matched) == 1
    assert matched[0]["task_id"] == "1"

    # Forward substring: query is shorter than stored title
    matched2 = _matching_tasks(tasks, title="Advance Excel")
    assert len(matched2) == 1
    assert matched2[0]["task_id"] == "2"

    # Reordered tokens: "analgor LKP"
    matched3 = _matching_tasks(tasks, title="analgor LKP")
    assert len(matched3) == 1
    assert matched3[0]["task_id"] == "3"


def test_complete_task_already_completed() -> None:
    bulk_delete_tasks(title_query="", status="all")
    task = add_task(title="Praktikum Komdat", due="besok 10:00 WIB", assignee="Gilang")
    tid = task["task_id"]

    res1 = complete_task_result(task_id=tid)
    assert res1["status"] == "applied"
    assert res1["outcome"] == "committed"

    # Second completion: must return already_completed cleanly instead of failing
    res2 = complete_task_result(task_id=tid)
    assert res2["status"] == "applied"
    assert res2["outcome"] == "already_completed"
    assert "sudah selesai sebelumnya" in res2["message"]

    bulk_delete_tasks(title_query="", status="all")


def test_get_note_token_overlap() -> None:
    save_note(title="Jadwal Kuliah Semester 5", content="Senin: AI, Selasa: OS")
    found = get_note("Jadwal Kuliah Gilang Semester Ini")
    assert found is not None
    assert found["title"] == "Jadwal Kuliah Semester 5"
    delete_note("Jadwal Kuliah Semester 5")


def test_search_notes_tool() -> None:
    save_note(title="Daftar Belanja Mingguan", content="1. Telur\n2. Susu\n3. Roti gandum")
    save_note(title="Ide Liburan Akhir Tahun", content="Pilihan: Labuan Bajo atau Bromo")

    res = handle_search_notes({"query": "gandum"})
    assert res["status"] == "success"
    assert res["count"] == 1
    assert res["notes"][0]["title"] == "Daftar Belanja Mingguan"

    res_empty = handle_search_notes({"query": "tokyo"})
    assert res_empty["status"] == "success"
    assert res_empty["count"] == 0

    delete_note("Daftar Belanja Mingguan")
    delete_note("Ide Liburan Akhir Tahun")


def test_guardrails_query_directive_does_not_override_mutation_state() -> None:
    read_res = inject_tool_directive({"status": "success", "count": 2}, "list_tasks")
    assert "Do NOT claim you updated, completed, or deleted" in read_res["_model_directive"]

    mut_res = inject_tool_directive({"status": "success", "affected_ids": ["1"]}, "complete_task")
    assert "Action confirmed successful" in mut_res["_model_directive"]


def test_skills_dir_writable_fallback() -> None:
    writable = _get_skills_dir(require_writable=True)
    assert writable != ""
    assert os.path.exists(writable)
    assert os.access(writable, os.W_OK)


@pytest.mark.asyncio
async def test_add_task_smart_buffer_override_zero() -> None:
    from src.tools.tasks import handle_add_task

    res = await handle_add_task(
        {
            "title": "Tugas Asah Mandiri",
            "due": "2026-10-06 20:00 WIB",
            "assignee": "Gilang",
            "lead_time_minutes": 0,
        },
        default_sender="Gilang",
    )
    assert res["status"] == "success"
    task = res["task"]
    assert task["lead_time_minutes"] == 120

    res_meet = await handle_add_task(
        {
            "title": "Meet Hackaton Diskusi Ide",
            "due": "2026-10-06 21:00 WIB",
            "assignee": "Gilang",
            "lead_time_minutes": 0,
        },
        default_sender="Gilang",
    )
    assert res_meet["status"] == "success"
    assert res_meet["task"]["lead_time_minutes"] == 30

