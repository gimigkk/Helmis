"""
test_quoted_messages.py — Tests for WAHA quoted message / reply payload extraction.
"""

import pytest
from httpx import ASGITransport, AsyncClient

import src.queue as queue_mod
import src.webhook as webhook_mod
from src.client import WahaClient
from src.queue import IncomingMessageEvent


@pytest.mark.asyncio
async def test_webhook_extracts_reply_to_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    dispatched_events: list[IncomingMessageEvent] = []

    monkeypatch.setattr(webhook_mod, "GILANG_PHONE", "628111111111")
    monkeypatch.setattr(webhook_mod, "BUNGA_PHONE", "628222222222")
    monkeypatch.setattr(webhook_mod, "BOT_PHONE", "628999999999")

    client = WahaClient(base_url="http://test", api_key="test", session_name="default")
    app = webhook_mod.create_webhook_app(client)

    # Intercept queue dispatch
    monkeypatch.setattr(
        queue_mod.ChatQueueManager,
        "dispatch",
        lambda self, event: dispatched_events.append(event),
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # 1. Payload with top-level replyTo from Helmis
        payload_reply_to = {
            "event": "message",
            "payload": {
                "id": "msg_reply_1",
                "from": "628111111111@c.us",
                "fromMe": False,
                "body": "Bisa baca apa yang gw quote via Waha ga?",
                "hasMedia": False,
                "replyTo": {
                    "id": "msg_orig_1",
                    "fromMe": True,
                    "body": "Catatan sudah diperbarui, Gilang. Bunga yang mengambil mata kuliah Ekonomi Syariah.",
                },
            },
        }

        resp = await ac.post("/webhooks/waha", json=payload_reply_to)
        assert resp.status_code == 200
        assert len(dispatched_events) == 1
        event = dispatched_events[0]
        assert event.sender_name == "Gilang"
        assert event.text == "Bisa baca apa yang gw quote via Waha ga?"
        assert event.quoted_text == "Catatan sudah diperbarui, Gilang. Bunga yang mengambil mata kuliah Ekonomi Syariah."
        assert event.quoted_sender == "Helmis"

        # 2. Payload with _data.quotedMsg from Bunga
        payload_data_quoted = {
            "event": "message",
            "payload": {
                "id": "msg_reply_2",
                "from": "628111111111@c.us",
                "fromMe": False,
                "body": "Maksudnya ini gimana ya?",
                "hasMedia": False,
                "_data": {
                    "quotedParticipant": "628222222222@c.us",
                    "quotedMsg": {
                        "fromMe": False,
                        "body": "Aku udah bayar tagihan listrik ya.",
                    },
                },
            },
        }

        resp2 = await ac.post("/webhooks/waha", json=payload_data_quoted)
        assert resp2.status_code == 200
        assert len(dispatched_events) == 2
        event2 = dispatched_events[1]
        assert event2.quoted_text == "Aku udah bayar tagihan listrik ya."
        assert event2.quoted_sender == "Bunga"
