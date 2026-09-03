"""
test_fastpath.py — Deterministic fast-path routing and fallback safety.
"""

from typing import Any

import pytest

from src.agent.fastpath import classify_fastpath, run_fastpath


class TestClassify:
    def test_greetings_route_to_chat(self) -> None:
        for text in ["halo", "halow", "hai", "pagi", "selamat sore", "woi", "p", "assalamualaikum"]:
            assert classify_fastpath(text) == "chat", text

    def test_casual_ack_route_to_chat(self) -> None:
        for text in ["makasih", "sip", "oke", "wkwk", "gt", "oh"]:
            assert classify_fastpath(text) == "chat", text

    def test_task_query_routes(self) -> None:
        assert classify_fastpath("ada tugas apa aja?") == "tasks"
        assert classify_fastpath("cek tugas") == "tasks"
        assert classify_fastpath("list reminder dong") == "tasks"

    def test_schedule_query_routes(self) -> None:
        assert classify_fastpath("ada jadwal apa?") == "schedules"
        assert classify_fastpath("cek jadwal") == "schedules"

    def test_notes_query_routes(self) -> None:
        assert classify_fastpath("catatan apa aja?") == "notes"
        assert classify_fastpath("list notes") == "notes"

    def test_time_query_routes(self) -> None:
        assert classify_fastpath("jam berapa sekarang?") == "time"
        assert classify_fastpath("hari apa sekarang") == "time"

    def test_actions_never_route(self) -> None:
        for text in [
            "ingetin gw bayar kosan",
            "hapus tugas absen",
            "catat tugas beli beras",
            "kirim file rapor ke bunga",
            "tandai tugas selesai",
            "ubah jadwal seminar besok jam 3",
            "buatkan reminder absensi",
        ]:
            assert classify_fastpath(text) == "", text

    def test_media_and_long_text_never_route(self) -> None:
        assert classify_fastpath("") == ""
        assert classify_fastpath("x" * 250) == ""

    def test_ambiguous_freeform_does_not_route(self) -> None:
        assert classify_fastpath("kamu lagi apa?") == ""
        assert classify_fastpath("besok kita kemana ya") == ""

    def test_compound_query_falls_back(self) -> None:
        # 'jadwal' + 'tugas' both present -> ambiguous, no fast path
        assert classify_fastpath("cek tugas dan jadwal") == ""


class TestRun:
    @pytest.mark.asyncio
    async def test_chat_reply_passthrough(self) -> None:
        async def fake_completion(payload: dict[str, Any]) -> str:
            return "Halo Gilang! Sore ya."

        reply = await run_fastpath("halo", "chat", "Gilang", fake_completion)
        assert reply == "Halo Gilang! Sore ya."

    @pytest.mark.asyncio
    async def test_time_query_needs_no_model(self) -> None:
        reply = await run_fastpath("jam berapa?", "time", "Gilang", None)
        assert "WIB" in reply


class TestVisionAlignment:
    """Fast-path output must honor system-prompt.md contracts."""

    @pytest.mark.asyncio
    async def test_tasks_render_layout_contract(self, monkeypatch, tmp_path) -> None:
        """Manual §4: numbered items, section headers, └ sub-lines, blank lines."""
        data_dir = tmp_path / "data"
        monkeypatch.setenv("DATA_DIR", str(data_dir))
        import src.memory as memory
        memory.add_task(title="Bikin PPT", due="Sabtu, 5 September 2026 (23:59 WIB)", assignee="Gilang")
        memory.add_task(title="Isi Gform", due="", assignee="Bunga")

        reply = await run_fastpath("ada tugas apa?", "tasks", "Gilang", None)
        assert "> *Daftar Tugas Aktif*" in reply
        assert "*Tugas Gilang:*" in reply
        assert "1. *Bikin PPT*" in reply
        assert "   └ Deadline: Sabtu, 5 September 2026 (23:59 WIB)" in reply
        assert "*Tugas Bunga:*" in reply
        assert "1. *Isi Gform*" in reply

    @pytest.mark.asyncio
    async def test_tasks_render_proactive_footer(self, monkeypatch, tmp_path) -> None:
        """Vision: anticipate needs — list closes with nearest deadline + routine note."""
        data_dir = tmp_path / "data2"
        monkeypatch.setenv("DATA_DIR", str(data_dir))
        import src.memory as memory
        memory.add_task(title="Bikin PPT", due="Sabtu 5 Sep", assignee="Gilang")
        memory.add_task(title="Absen Kuliah X", due="", assignee="Bunga", recurrence={"type": "weekly", "weekdays": ["senin"], "time": "09:00", "timezone": "Asia/Jakarta"})

        reply = await run_fastpath("ada tugas apa?", "tasks", "Gilang", None)
        assert "Terdekat: *Bikin PPT*" in reply
        assert "absen" in reply.lower()

    @pytest.mark.asyncio
    async def test_chat_prompt_has_clock(self) -> None:
        """Greetings must match the real time of day, not assume morning."""
        captured: dict[str, Any] = {}

        async def fake_completion(payload: dict[str, Any]) -> str:
            captured["sys"] = payload["systemInstruction"]["parts"][0]["text"]
            return "Sip."

        await run_fastpath("halo", "chat", "Gilang", fake_completion)
        assert "WIB" in captured["sys"]
        assert "sapaan" in captured["sys"].lower()

    @pytest.mark.asyncio
    async def test_chat_deterministic_fallback_when_provider_fails(self) -> None:
        """Provider down => instant deterministic greeting, never dead, never slow."""
        async def boom(payload: dict[str, Any]) -> str:
            raise RuntimeError("provider down")

        reply = await run_fastpath("halo", "chat", "Gilang", boom)
        assert reply is not None
        assert "Gilang" in reply
        assert "WIB" not in reply  # greeting, not a clock dump


class TestRoutineFiltering:
    """Routine absen pings are hidden from task overviews."""

    def test_routine_tasks_counted_but_not_listed(self, monkeypatch, tmp_path) -> None:
        import src.memory as memory
        from src.agent.fastpath import _render_tasks_reply

        data_dir = tmp_path / "data"
        monkeypatch.setenv("DATA_DIR", str(data_dir))

        memory.add_task(title="Absen Kuliah Statistika", due="", assignee="Bunga", recurrence={"type": "weekly", "weekdays": ["senin"], "time": "09:00", "timezone": "Asia/Jakarta"})
        memory.add_task(title="Bikin laporan mingguan", due="Besok 10:00 WIB", assignee="Gilang")
        memory.add_task(title="Bayar listrik", due="Jumat 12:00 WIB", assignee="Gilang")

        work = memory.list_tasks(status="pending", include_routine=False)
        routine_count = len(memory.list_tasks(status="pending", include_routine=True)) - len(work)
        reply = _render_tasks_reply(work, routine_count)
        assert "Absen Kuliah Statistika" not in reply
        assert "Bikin laporan mingguan" in reply
        assert "Bayar listrik" in reply
        assert "disembunyikan" in reply
        assert "+1" in reply

    def test_routine_only_shows_offer(self) -> None:
        from src.agent.fastpath import _render_tasks_reply

        reply = _render_tasks_reply([], 8)
        assert "8 jadwal absen rutin" in reply
        assert "Mau dilihat" in reply
