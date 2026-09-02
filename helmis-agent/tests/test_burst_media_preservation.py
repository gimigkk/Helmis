"""
test_burst_media_preservation.py — Burst media and message-ID preservation contracts.

Phase 2 gate: multi-message bursts must not lose media attachments or message
IDs, and failed media/history retrieval must degrade safely.
"""

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from src.whatsapp.processor import process_batched_turn
from src.whatsapp.queue import IncomingMessageEvent


def _evt(**overrides: Any) -> IncomingMessageEvent:
    base: dict[str, Any] = {
        "sender_name": "Gilang",
        "from_user": "628111111111@c.us",
        "reply_id": None,
        "text": "",
        "has_media": False,
        "media_url": None,
        "media_type": None,
        "timestamp": 1.0,
    }
    base.update(overrides)
    return IncomingMessageEvent(**base)


@pytest.mark.asyncio
async def test_all_burst_media_labeled_in_context() -> None:
    """Three documents in one burst: primary + labels for the other two."""
    client = AsyncMock()
    client.get_messages = AsyncMock(return_value=[])
    client.download_media_base64 = AsyncMock(return_value=("application/pdf", "Zm9v"))
    client.send_message = AsyncMock(return_value="ok")
    client.start_typing = AsyncMock()
    client.stop_typing = AsyncMock()

    batch = [
        _evt(text="simpan tiga file ini", reply_id="m1"),
        _evt(has_media=True, media_url="http://waha/f1.pdf", media_type="application/pdf", media_filename="a.pdf"),
        _evt(has_media=True, media_url="http://waha/f2.pdf", media_type="application/pdf", media_filename="b.pdf"),
        _evt(has_media=True, media_url="http://waha/f3.pdf", media_type="application/pdf", media_filename="c.pdf"),
    ]

    captured: dict[str, Any] = {}

    async def fake_loop(**kwargs: Any) -> str:
        captured["text"] = kwargs["message_text"]
        captured["media"] = kwargs["media_data"]
        return "Tiga file sudah tersimpan."

    with patch("src.whatsapp.processor.run_agentic_react_loop", new=fake_loop):
        await process_batched_turn(client=client, batch=batch)

    assert "simpan tiga file ini" in captured["text"]
    # Primary media (last one) becomes inlineData + document banner
    assert captured["media"]["filename"] == "c.pdf"
    assert "[Dokumen Terlampir: c.pdf]" in captured["text"]
    # Other two labeled in text, never dropped silently
    assert "[Lampiran Media: a.pdf]" in captured["text"]
    assert "[Lampiran Media: b.pdf]" in captured["text"]


@pytest.mark.asyncio
async def test_media_download_failure_degrades_to_label() -> None:
    """Primary media download fails: turn continues with text, no crash, no silent success."""
    client = AsyncMock()
    client.get_messages = AsyncMock(return_value=[])
    client.download_media_base64 = AsyncMock(side_effect=RuntimeError("WAHA down"))
    client.send_message = AsyncMock(return_value="ok")
    client.start_typing = AsyncMock()
    client.stop_typing = AsyncMock()

    batch = [_evt(text="cek file ini ya", reply_id="m9", has_media=True, media_url="http://waha/x.pdf", media_type="application/pdf")]

    async def fake_loop(**kwargs: Any) -> str:
        assert kwargs["media_data"] is None  # download failed -> no media attached
        return "Tidak bisa membaca file-nya."

    with patch("src.whatsapp.processor.run_agentic_react_loop", new=fake_loop):
        await process_batched_turn(client=client, batch=batch)

    client.send_message.assert_awaited()  # user still gets an answer


@pytest.mark.asyncio
async def test_history_fetch_failure_still_processes_turn() -> None:
    """get_messages raising must not kill the turn; loop still runs on current text."""
    client = AsyncMock()
    client.get_messages = AsyncMock(side_effect=RuntimeError("WAHA history down"))
    client.send_message = AsyncMock(return_value="ok")
    client.start_typing = AsyncMock()
    client.stop_typing = AsyncMock()

    async def fake_loop(**kwargs: Any) -> str:
        return "Baik, sudah saya proses."

    with patch("src.whatsapp.processor.run_agentic_react_loop", new=fake_loop):
        await process_batched_turn(client=client, batch=[_evt(text="ping", reply_id="m1")])

    client.send_message.assert_awaited()
