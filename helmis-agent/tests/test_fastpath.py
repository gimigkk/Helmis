"""
test_fastpath.py — Model-driven fast-path routing and fallback safety.

Contract: only chat pings + clock queries take the fast path. ALL data
queries (tasks/schedules/notes, filtered or not) go through the full agent
loop so the model decides filtering and formatting via tools.
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

    def test_time_query_routes(self) -> None:
        assert classify_fastpath("jam berapa sekarang?") == "time"
        assert classify_fastpath("hari apa sekarang") == "time"

    def test_all_data_queries_reach_agent(self) -> None:
        """Model must decide filtering/formatting — no deterministic bypass."""
        for text in [
            "ada tugas apa aja?",
            "tugas apa aja",
            "list tugas",
            "ada jadwal apa?",
            "catatan apa aja?",
            "tugas Bunga",
            "tugas yang jatuh tempo besok",
            "rangkum task list jadi 3 prioritas",
            "semua tugas termasuk absen",
        ]:
            assert classify_fastpath(text) == "", text

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

    def test_freeform_does_not_route(self) -> None:
        assert classify_fastpath("kamu lagi apa?") == ""
        assert classify_fastpath("besok kita kemana ya") == ""


class TestRun:
    @pytest.mark.asyncio
    async def test_chat_reply_passthrough(self) -> None:
        async def fake_completion(payload: dict[str, Any]) -> str:
            return "Halo Gilang! Sore ya."

        reply = await run_fastpath("halo", "chat", "Gilang", fake_completion)
        assert reply == "Halo Gilang! Sore ya."

    @pytest.mark.asyncio
    async def test_chat_model_escape_hatch(self) -> None:
        """Model may bail to the full agent via [FALLBACK]."""
        async def fake_completion(payload: dict[str, Any]) -> str:
            return "[FALLBACK]"

        # [FALLBACK] => None triggers caller-side full-loop fallback; the
        # deterministic greeting is ONLY for provider failure, not refusal.
        reply = await run_fastpath("halo", "chat", "Gilang", fake_completion)
        assert reply is None

    @pytest.mark.asyncio
    async def test_chat_deterministic_fallback_when_provider_fails(self) -> None:
        """Provider down => instant deterministic greeting, never dead."""

        async def boom(payload: dict[str, Any]) -> str:
            raise RuntimeError("provider down")

        reply = await run_fastpath("halo", "chat", "Gilang", boom)
        assert reply is not None
        assert "Gilang" in reply

    @pytest.mark.asyncio
    async def test_time_query_needs_no_model(self) -> None:
        reply = await run_fastpath("jam berapa?", "time", "Gilang", None)
        assert "WIB" in reply
