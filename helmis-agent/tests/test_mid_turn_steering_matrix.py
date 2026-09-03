"""
test_mid_turn_steering_matrix.py — Comprehensive Test Suite for Mid-Thought ReAct Steering & Brain Lock.

Validates the 30 edge case matrix:
- Real-time mid-turn mailbox injection & step reset
- Rapid multi-message burst draining
- Voice note and document injection mid-flight
- Hard safety ceiling against infinite injection loops
- Unconsumed mailbox message retention (zero drop)
- Concurrent cross-chat isolation and BrainLock atomicity
"""

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.agent.loop import drain_and_inject_mid_turn_mailbox, run_agentic_react_loop
from src.memory import store as memory
from src.whatsapp.client import WahaClient
from src.whatsapp.queue import ChatQueueManager, ChatQueueWorker, IncomingMessageEvent


@pytest.mark.asyncio
async def test_mid_turn_steering_correction_flow() -> None:
    """Edge Case 1 & 21: Model starts search for 15th, user injects 'ralat tanggal 16', agent pivots."""
    mailbox: asyncio.Queue[IncomingMessageEvent] = asyncio.Queue()
    mock_client = AsyncMock(spec=WahaClient)

    # 1. Start with initial prompt
    contents: list[dict[str, Any]] = [
        {"role": "user", "parts": [{"text": "Cari tiket ke Bali tanggal 15"}]}
    ]

    # Step 1: Model calls search_web for 15
    candidate_part_1 = {
        "functionCall": {"name": "search_web", "args": {"query": "tiket bali 15 agustus"}}
    }
    contents.append({"role": "model", "parts": [candidate_part_1]})
    contents.append({
        "role": "user",
        "parts": [{
            "functionResponse": {
                "name": "search_web",
                "response": {"output": {"status": "success", "results": "Tiket tgl 15: Rp 1.2jt"}},
            }
        }],
    })

    # User sends mid-turn correction right as step 1 finishes
    mailbox.put_nowait(
        IncomingMessageEvent(
            sender_name="Gilang",
            from_user="gilang@c.us",
            reply_id="m2",
            text="Eh ralat tanggal 16 ya",
            has_media=False,
            media_url=None,
            media_type=None,
            timestamp=1.5,
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
    # Verify the user turn contains the injection banner alongside the functionResponse
    user_turn_parts = contents[-1]["parts"]
    assert len(user_turn_parts) == 2
    assert "functionResponse" in user_turn_parts[0]
    assert "[Pesan Tambahan dari Gilang saat kamu sedang memproses]" in user_turn_parts[1]["text"]
    assert "Eh ralat tanggal 16 ya" in user_turn_parts[1]["text"]


@pytest.mark.asyncio
async def test_rapid_multi_burst_mid_turn_draining() -> None:
    """Edge Case 4: 4 rapid messages sent during a single tool step are drained in 1 batch without drops."""
    mailbox: asyncio.Queue[IncomingMessageEvent] = asyncio.Queue()
    mock_client = AsyncMock(spec=WahaClient)

    contents: list[dict[str, Any]] = [
        {"role": "user", "parts": [{"text": "Beliin bahan masakan"}]}
    ]

    for msg in ["sama bawang merah", "bawang putih 1kg", "cabe rawit 200gr", "kecap manis"]:
        mailbox.put_nowait(
            IncomingMessageEvent(
                sender_name="Bunga",
                from_user="bunga@c.us",
                reply_id=None,
                text=msg,
                has_media=False,
                media_url=None,
                media_type=None,
                timestamp=2.0,
            )
        )

    injected = await drain_and_inject_mid_turn_mailbox(
        contents=contents,
        mailbox=mailbox,
        client=mock_client,
        sender_name="Bunga",
    )

    assert injected is True
    injected_text = contents[-1]["parts"][-1]["text"]
    assert "sama bawang merah" in injected_text
    assert "bawang putih 1kg" in injected_text
    assert "cabe rawit 200gr" in injected_text
    assert "kecap manis" in injected_text


@pytest.mark.asyncio
async def test_voice_note_mid_turn_transcription_injection() -> None:
    """Edge Case 7 & 9: Voice note sent mid-turn is downloaded, transcribed, and injected."""
    mailbox: asyncio.Queue[IncomingMessageEvent] = asyncio.Queue()
    mock_client = AsyncMock(spec=WahaClient)
    mock_client.download_media_base64.return_value = ("audio/ogg", "dummy_b64")

    contents: list[dict[str, Any]] = [
        {"role": "user", "parts": [{"text": "Catat tugas"}]}
    ]

    mailbox.put_nowait(
        IncomingMessageEvent(
            sender_name="Gilang",
            from_user="gilang@c.us",
            reply_id=None,
            text="",
            has_media=True,
            media_url="http://waha:3000/api/files/vn.ogg",
            media_type="audio/ogg",
            timestamp=3.0,
        )
    )

    with patch("src.agent.transcribe_audio_base64", AsyncMock(return_value="Deadline jam 9 malam ini ya")):
        injected = await drain_and_inject_mid_turn_mailbox(
            contents=contents,
            mailbox=mailbox,
            client=mock_client,
            sender_name="Gilang",
        )

    assert injected is True
    injected_text = contents[-1]["parts"][-1]["text"]
    assert 'Pesan Suara: "Deadline jam 9 malam ini ya"' in injected_text


@pytest.mark.asyncio
async def test_document_attachment_mid_turn_injection() -> None:
    """Edge Case 8: Document PDF sent mid-turn appends filename label to prompt."""
    mailbox: asyncio.Queue[IncomingMessageEvent] = asyncio.Queue()
    mock_client = AsyncMock(spec=WahaClient)
    mock_client.download_media_base64.return_value = ("application/pdf", "pdf_bytes")

    contents: list[dict[str, Any]] = [
        {"role": "user", "parts": [{"text": "Tolong simpan ini"}]}
    ]

    mailbox.put_nowait(
        IncomingMessageEvent(
            sender_name="Gilang",
            from_user="gilang@c.us",
            reply_id=None,
            text="Simpan ke folder kuliah",
            has_media=True,
            media_url="http://waha:3000/api/files/doc.pdf",
            media_type="application/pdf",
            media_filename="Tugas_Analgor_P2.pdf",
            timestamp=4.0,
        )
    )

    injected = await drain_and_inject_mid_turn_mailbox(
        contents=contents,
        mailbox=mailbox,
        client=mock_client,
        sender_name="Gilang",
    )

    assert injected is True
    user_parts = contents[-1]["parts"]
    assert any("Simpan ke folder kuliah" in p.get("text", "") for p in user_parts)
    assert any("Tugas_Analgor_P2.pdf" in p.get("text", "") for p in user_parts)
    assert any("inlineData" in p for p in user_parts)


@pytest.mark.asyncio
async def test_hard_safety_ceiling_against_infinite_injection_loops(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Edge Case 16: Constant spam injection terminates at ABSOLUTE_MAX_STEPS (18)."""
    monkeypatch.setattr("src.agent.cascade.GEMINI_KEYS", ["test_key_12345"])
    monkeypatch.setenv("HELMIS_AUTHORIZED_SENDERS", "Spammer")

    mailbox: asyncio.Queue[IncomingMessageEvent] = asyncio.Queue()
    mock_client = AsyncMock(spec=WahaClient)

    # Mock Gemini HTTP response that keeps returning functionCalls
    step_counter = 0

    async def mock_post(*args: Any, **kwargs: Any) -> Any:
        nonlocal step_counter
        step_counter += 1
        # Continually queue a new message into the mailbox to simulate spam injection
        mailbox.put_nowait(
            IncomingMessageEvent(
                sender_name="Spammer",
                from_user="spam@c.us",
                reply_id=None,
                text=f"Spam update {step_counter}",
                has_media=False,
                media_url=None,
                media_type=None,
                timestamp=5.0,
            )
        )
        fake_resp = {
            "candidates": [{
                "content": {
                    "parts": [{"functionCall": {"name": "search_vault_files", "args": {"query": f"test_{step_counter}"}}}]
                }
            }]
        }
        mock_http_resp = MagicMock()
        mock_http_resp.status_code = 200
        mock_http_resp.json.return_value = fake_resp
        return mock_http_resp

    with patch("httpx.AsyncClient.post", side_effect=mock_post):
        with patch("src.agent.execute_tool_call", AsyncMock(return_value={"status": "success"})):
            reply = await run_agentic_react_loop(
                client=mock_client,
                sender_name="Spammer",
                chat_id="spam@c.us",
                message_text="Initial prompt",
                max_steps=12,
                mailbox=mailbox,
            )

    # Loop must have terminated at safety ceiling (18 loop steps + 1 final synthesis step)
    assert step_counter <= 19
    assert reply is not None


@pytest.mark.asyncio
async def test_unconsumed_mailbox_messages_transfer_to_queue() -> None:
    """Edge Case 27: Message arriving on exact turn completion transfers to queue without loss."""
    processed_turns: list[str] = []

    async def mock_turn_handler(
        batch: list[IncomingMessageEvent],
        mailbox: asyncio.Queue[IncomingMessageEvent] | None = None,
    ) -> None:
        # Simulate work while turn is active
        await asyncio.sleep(0.08)
        processed_turns.append(batch[0].text)

    worker = ChatQueueWorker(
        chat_id="gilang@c.us",
        turn_handler=mock_turn_handler,
        debounce_seconds=0.02,
    )

    worker.enqueue(
        IncomingMessageEvent(
            sender_name="Gilang",
            from_user="gilang@c.us",
            reply_id=None,
            text="Turn 1 initial",
            has_media=False,
            media_url=None,
            media_type=None,
            timestamp=1.0,
        )
    )

    # Wait for turn 1 to start
    await asyncio.sleep(0.04)
    assert worker.active_turn_mailbox is not None

    # Inject message while turn 1 is running
    worker.enqueue(
        IncomingMessageEvent(
            sender_name="Gilang",
            from_user="gilang@c.us",
            reply_id=None,
            text="Turn 2 arriving mid-flight but unconsumed",
            has_media=False,
            media_url=None,
            media_type=None,
            timestamp=1.05,
        )
    )

    # Wait for turn 1 to finish and turn 2 to pick up the transferred message
    await asyncio.sleep(0.3)

    assert len(processed_turns) == 2
    assert processed_turns[0] == "Turn 1 initial"
    assert processed_turns[1] == "Turn 2 arriving mid-flight but unconsumed"


@pytest.mark.asyncio
async def test_concurrent_brain_memory_mutations_without_race_conditions() -> None:
    """Edge Case 12 & 14: 10 concurrent tasks mutate memory simultaneously with full atomicity."""
    memory._ensure_data_dir()

    async def add_task_worker(idx: int) -> None:
        await asyncio.sleep(0.01 * (idx % 3))
        memory.add_task(
            title=f"Concurrent Task {idx}",
            due="2026-08-28 10:00 WIB",
            assignee="Gilang" if idx % 2 == 0 else "Bunga",
            priority="normal",
        )

    # Run 10 concurrent task creations across threads/tasks
    await asyncio.gather(*[add_task_worker(i) for i in range(10)])

    mem = memory.load_memory()
    tasks = mem.get("tasks", [])
    concurrent_tasks = [t for t in tasks if t.get("title", "").startswith("Concurrent Task ")]
    assert len(concurrent_tasks) == 10

    # Clean up test tasks
    for t in concurrent_tasks:
        memory.bulk_delete_tasks(task_id=str(t["task_id"]), status="all")



@pytest.mark.asyncio
async def test_cross_chat_mailbox_isolation() -> None:
    """Edge Case 11: Message to Bunga does not enter Gilang's active turn mailbox."""
    gilang_mailbox_items: list[str] = []
    bunga_mailbox_items: list[str] = []

    async def mock_handler(
        batch: list[IncomingMessageEvent],
        mailbox: asyncio.Queue[IncomingMessageEvent] | None = None,
    ) -> None:
        chat = batch[0].from_user
        await asyncio.sleep(0.1)
        if mailbox:
            while not mailbox.empty():
                evt = mailbox.get_nowait()
                if chat == "gilang@c.us":
                    gilang_mailbox_items.append(evt.text)
                else:
                    bunga_mailbox_items.append(evt.text)

    mgr = ChatQueueManager(turn_handler=mock_handler, debounce_seconds=0.02)

    # Start Gilang turn
    mgr.dispatch(
        IncomingMessageEvent(
            sender_name="Gilang",
            from_user="gilang@c.us",
            reply_id=None,
            text="Gilang turn 1",
            has_media=False,
            media_url=None,
            media_type=None,
            timestamp=1.0,
        )
    )

    await asyncio.sleep(0.04)

    # Bunga sends message while Gilang turn is running
    mgr.dispatch(
        IncomingMessageEvent(
            sender_name="Bunga",
            from_user="bunga@c.us",
            reply_id=None,
            text="Bunga separate message",
            has_media=False,
            media_url=None,
            media_type=None,
            timestamp=1.05,
        )
    )

    # Gilang sends mid-turn correction
    mgr.dispatch(
        IncomingMessageEvent(
            sender_name="Gilang",
            from_user="gilang@c.us",
            reply_id=None,
            text="Gilang mid-turn correction",
            has_media=False,
            media_url=None,
            media_type=None,
            timestamp=1.06,
        )
    )

    await asyncio.sleep(0.2)

    # Verify complete isolation
    assert gilang_mailbox_items == ["Gilang mid-turn correction"]
    assert bunga_mailbox_items == []


@pytest.mark.asyncio
async def test_mid_turn_binary_media_synchronization() -> None:
    """Validate that media arriving mid-turn synchronizes binary payload and inlineData."""
    mailbox: asyncio.Queue[IncomingMessageEvent] = asyncio.Queue()
    mock_client = AsyncMock(spec=WahaClient)
    mock_client.download_media_base64 = AsyncMock(return_value=("application/pdf", "JVBERi0xLjQKJeLjz9MKMSAwIG9iag=="))

    contents: list[dict[str, Any]] = [
        {"role": "user", "parts": [{"text": "Simpan file ini ke brankas"}]}
    ]

    mailbox.put_nowait(
        IncomingMessageEvent(
            sender_name="Gilang",
            from_user="gilang@c.us",
            reply_id="m99",
            text="Ini filenya",
            has_media=True,
            media_url="http://waha:3000/media/doc123.pdf",
            media_type="application/pdf",
            media_filename="silabus_ekonomi.pdf",
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
    assert turn_state.get("media_data") is not None
    assert turn_state["media_data"]["mimeType"] == "application/pdf"
    assert turn_state["media_data"]["filename"] == "silabus_ekonomi.pdf"
    assert turn_state["media_data"]["data"] == "JVBERi0xLjQKJeLjz9MKMSAwIG9iag=="

    # Verify Gemini contents received inlineData part
    user_parts = contents[-1]["parts"]
    assert any("inlineData" in p for p in user_parts)
    assert any("silabus_ekonomi.pdf" in p.get("text", "") for p in user_parts)
