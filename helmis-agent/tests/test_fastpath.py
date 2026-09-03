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
    async def test_fallback_marker_returns_none(self) -> None:
        async def fake_completion(payload: dict[str, Any]) -> str:
            return "[FALLBACK]"

        assert await run_fastpath("halo", "chat", "Gilang", fake_completion) is None

    @pytest.mark.asyncio
    async def test_time_query_needs_no_model(self) -> None:
        reply = await run_fastpath("jam berapa?", "time", "Gilang", None)
        assert "WIB" in reply

    @pytest.mark.asyncio
    async def test_task_query_includes_snapshot(self) -> None:
        captured: dict[str, Any] = {}

        async def fake_completion(payload: dict[str, Any]) -> str:
            captured["text"] = payload["contents"][0]["parts"][0]["text"]
            return "Ada 1 tugas pending."

        reply = await run_fastpath("ada tugas apa?", "tasks", "Gilang", fake_completion)
        assert reply == "Ada 1 tugas pending."
        assert "DATA (pending tasks" in captured["text"]
        assert "PERTANYAAN: ada tugas apa?" in captured["text"]


class TestVisionAlignment:
    """Fast-path output must honor system-prompt.md contracts."""

    @pytest.mark.asyncio
    async def test_query_prompt_carries_layout_contract(self) -> None:
        """Manual §4: numbered items, section headers, └ sub-lines, no emoji."""
        captured: dict[str, Any] = {}

        async def fake_completion(payload: dict[str, Any]) -> str:
            captured["sys"] = payload["systemInstruction"]["parts"][0]["text"]
            return "> *Daftar Tugas Aktif*"

        await run_fastpath("ada tugas apa?", "tasks", "Gilang", fake_completion)
        sys = captured["sys"]
        assert "*Tugas Gilang:*" in sys
        assert "└ Deadline" in sys
        assert "Nomori" in sys
        assert "tanpa emoji" in sys.lower()

    @pytest.mark.asyncio
    async def test_chat_prompt_has_clock(self) -> None:
        """Greetings must match the real time of day, not assume morning."""
        captured: dict[str, Any] = {}

        async def fake_completion(payload: dict[str, Any]) -> str:
            captured["sys"] = payload["systemInstruction"]["parts"][0]["text"]
            return "Sip."

        await run_fastpath("halo", "chat", "Gilang", fake_completion)
        assert "WIB" in captured["sys"]
        assert "Sapaan" in captured["sys"] or "sapaan" in captured["sys"]

    @pytest.mark.asyncio
    async def test_query_prompt_ends_with_proactive_offer(self) -> None:
        """Vision: anticipate needs — list answers close with one offer."""
        captured: dict[str, Any] = {}

        async def fake_completion(payload: dict[str, Any]) -> str:
            captured["sys"] = payload["systemInstruction"]["parts"][0]["text"]
            return "> *Daftar Tugas Aktif*\n\n1. *Absen Senin*"

        await run_fastpath("ada tugas apa?", "tasks", "Gilang", fake_completion)
        assert "proaktif" in captured["sys"].lower()
