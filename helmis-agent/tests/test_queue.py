"""
test_queue.py — Tests for Per-Chat FIFO Queue and Burst Debouncing.
"""

import asyncio
from typing import Any

import pytest

from src.whatsapp.queue import ChatQueueManager, ChatQueueWorker, IncomingMessageEvent


@pytest.mark.asyncio
async def test_queue_debounces_burst_messages() -> None:
    processed_batches: list[list[IncomingMessageEvent]] = []

    async def mock_handler(batch: list[IncomingMessageEvent]) -> None:
        processed_batches.append(batch)

    mgr = ChatQueueManager(turn_handler=mock_handler, debounce_seconds=0.3)

    # Simulate rapid burst of 3 messages in same chat within 0.1s
    mgr.dispatch(
        IncomingMessageEvent(
            sender_name="Gilang",
            from_user="628111111111@c.us",
            reply_id="m1",
            text="Halo helmis",
            has_media=False,
            media_url=None,
            media_type=None,
            timestamp=1.0,
        )
    )
    await asyncio.sleep(0.05)
    mgr.dispatch(
        IncomingMessageEvent(
            sender_name="Gilang",
            from_user="628111111111@c.us",
            reply_id="m2",
            text="tolong ingetin besok",
            has_media=False,
            media_url=None,
            media_type=None,
            timestamp=1.1,
        )
    )

    # Wait for debounce window (0.3s) to fire
    await asyncio.sleep(0.5)

    assert len(processed_batches) == 1
    assert len(processed_batches[0]) == 2
    assert processed_batches[0][0].text == "Halo helmis"
    assert processed_batches[0][1].text == "tolong ingetin besok"


@pytest.mark.asyncio
async def test_queue_processes_different_chats_concurrently() -> None:
    completed_chats: list[str] = []

    async def mock_handler(batch: list[IncomingMessageEvent]) -> None:
        chat = batch[0].from_user
        if chat == "gilang@c.us":
            await asyncio.sleep(0.1)
        else:
            await asyncio.sleep(0.05)
        completed_chats.append(chat)

    mgr = ChatQueueManager(turn_handler=mock_handler, debounce_seconds=0.1)

    # Dispatch to Gilang and Bunga simultaneously
    mgr.dispatch(
        IncomingMessageEvent(
            sender_name="Gilang",
            from_user="gilang@c.us",
            reply_id="g1",
            text="Gilang msg",
            has_media=False,
            media_url=None,
            media_type=None,
            timestamp=1.0,
        )
    )
    mgr.dispatch(
        IncomingMessageEvent(
            sender_name="Bunga",
            from_user="bunga@c.us",
            reply_id="b1",
            text="Bunga msg",
            has_media=False,
            media_url=None,
            media_type=None,
            timestamp=1.0,
        )
    )

    await asyncio.sleep(0.4)

    # Bunga finished first because its task was shorter (0.05s vs 0.1s)
    assert "bunga@c.us" in completed_chats
    assert "gilang@c.us" in completed_chats
    assert completed_chats[0] == "bunga@c.us"


def test_split_into_bubbles_explicit_separator() -> None:
    from src.whatsapp.processor import split_into_bubbles

    text = "Sip Gilang, udah kusimpan nomor kontaknya ya.\n---\nBtw besok ada meeting jam 10 pagi, mau diingetin?"
    bubbles = split_into_bubbles(text)
    assert len(bubbles) == 2
    assert bubbles[0] == "Sip Gilang, udah kusimpan nomor kontaknya ya."
    assert bubbles[1] == "Btw besok ada meeting jam 10 pagi, mau diingetin?"


def test_split_into_bubbles_preserves_multi_paragraph_schedules_in_one_bubble() -> None:
    from src.whatsapp.processor import split_into_bubbles

    schedule_text = (
        "Jadwal kuliah Gilang semester ini:\n\n"
        "Selasa:\n"
        "1. 08:00-09:40 - Komunikasi Data dan Jaringan Komputer (Kuliah) | Ruangan: RK. CCR 2.15\n"
        "2. 10:00-12:00 - Komunikasi Data dan Jaringan Komputer (Praktikum) | Ruangan: Disesuaikan\n"
        "3. 13:00-14:40 - Sistem Informasi (Kuliah) | Ruangan: RK. CCR 1.02\n\n"
        "Rabu:\n"
        "1. 08:00-09:40 - Analisis Algoritme (Kuliah) | Ruangan: IPBW8 501\n"
        "2. 10:00-11:40 - Analisis Algoritme (Responsi) | Ruangan: IPBW8 501\n"
        "3. 13:00-14:40 - Sistem Operasi (Kuliah) | Ruangan: IPBW6 504\n\n"
        "Kamis:\n"
        "1. 10:00-12:00 - Sistem Operasi (Praktikum) | Ruangan: Labkom 3\n"
        "2. 13:00-15:00 - Kecerdasan Buatan (Praktikum) | Ruangan: Computer Hall B\n\n"
        "Jumat:\n"
        "1. 09:00-10:40 - Kecerdasan Buatan (Kuliah) | Ruangan: RK. OFAC 3 B2 / R. Pinus 1"
    )
    bubbles = split_into_bubbles(schedule_text)
    assert len(bubbles) == 1
    assert "Jadwal kuliah Gilang" in bubbles[0]
    assert "Jumat:" in bubbles[0]


def test_split_into_bubbles_empty_and_short() -> None:
    from src.whatsapp.processor import split_into_bubbles

    assert split_into_bubbles("") == []
    assert split_into_bubbles("Sip udah ya.") == ["Sip udah ya."]
    assert split_into_bubbles("Halo Gilang\n\nAda apa nih?") == ["Halo Gilang\n\nAda apa nih?"]


@pytest.mark.asyncio
async def test_active_turn_mailbox_routes_messages_mid_turn() -> None:
    """Verify that messages arriving while a turn is in-flight route directly into active_turn_mailbox."""
    mailbox_received: list[str] = []

    async def mock_handler(
        batch: list[IncomingMessageEvent],
        mailbox: asyncio.Queue[IncomingMessageEvent] | None = None,
    ) -> None:
        assert mailbox is not None
        # Simulate long-running turn
        await asyncio.sleep(0.15)
        # Drain mailbox
        while not mailbox.empty():
            evt = mailbox.get_nowait()
            mailbox_received.append(evt.text)

    worker = ChatQueueWorker(
        chat_id="gilang@c.us",
        turn_handler=mock_handler,
        debounce_seconds=0.05,
    )

    # 1. Enqueue initial message
    worker.enqueue(
        IncomingMessageEvent(
            sender_name="Gilang",
            from_user="gilang@c.us",
            reply_id="m1",
            text="Cari tiket ke Bali tanggal 15",
            has_media=False,
            media_url=None,
            media_type=None,
            timestamp=1.0,
        )
    )

    # Wait for debounce to finish and turn loop to start
    await asyncio.sleep(0.08)
    assert worker.active_turn_mailbox is not None

    # 2. Enqueue mid-turn correction while turn is actively running
    worker.enqueue(
        IncomingMessageEvent(
            sender_name="Gilang",
            from_user="gilang@c.us",
            reply_id="m2",
            text="Eh ralat tanggal 16 ya",
            has_media=False,
            media_url=None,
            media_type=None,
            timestamp=1.05,
        )
    )

    # Wait for turn handler to finish
    await asyncio.sleep(0.15)

    assert len(mailbox_received) == 1
    assert mailbox_received[0] == "Eh ralat tanggal 16 ya"


@pytest.mark.asyncio
async def test_drain_and_inject_mid_turn_mailbox() -> None:
    """Verify drain_and_inject_mid_turn_mailbox injects steering text into conversation contents."""
    from unittest.mock import AsyncMock

    from src.agent.loop import drain_and_inject_mid_turn_mailbox
    from src.whatsapp.client import WahaClient

    mock_client = AsyncMock(spec=WahaClient)
    mailbox: asyncio.Queue[IncomingMessageEvent] = asyncio.Queue()

    contents: list[dict[str, Any]] = [
        {"role": "user", "parts": [{"text": "Cari tiket ke Bali"}]},
        {"role": "model", "parts": [{"functionCall": {"name": "search_web", "args": {"query": "tiket bali 15"}}}]},
        {"role": "user", "parts": [{"functionResponse": {"name": "search_web", "response": {"output": "Hasil 15"}}}]},
    ]

    # Push mid-turn correction
    mailbox.put_nowait(
        IncomingMessageEvent(
            sender_name="Gilang",
            from_user="gilang@c.us",
            reply_id="m2",
            text="Ralat tanggal 16 maksudnya",
            has_media=False,
            media_url=None,
            media_type=None,
            timestamp=2.0,
        )
    )

    turn_state: dict[str, Any] = {}
    injected = await drain_and_inject_mid_turn_mailbox(
        contents=contents,
        mailbox=mailbox,
        client=mock_client,
        sender_name="Gilang",
        turn_state=turn_state,
    )

    assert injected is True
    assert turn_state.get("has_mid_turn_update") is True
    # The last user turn should now contain the injection banner
    assert len(contents[-1]["parts"]) == 2
    injected_part = contents[-1]["parts"][1]["text"]
    assert "[Pesan Tambahan dari Gilang saat kamu sedang memproses]" in injected_part
    assert "Ralat tanggal 16 maksudnya" in injected_part


