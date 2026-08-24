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


@pytest.mark.asyncio
async def test_webhook_extracts_quoted_voice_note_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    dispatched_events: list[IncomingMessageEvent] = []

    monkeypatch.setattr(webhook_mod, "GILANG_PHONE", "628111111111")
    monkeypatch.setattr(webhook_mod, "BUNGA_PHONE", "628222222222")
    monkeypatch.setattr(webhook_mod, "BOT_PHONE", "628999999999")

    client = WahaClient(base_url="http://test", api_key="test", session_name="default")
    app = webhook_mod.create_webhook_app(client)

    monkeypatch.setattr(
        queue_mod.ChatQueueManager,
        "dispatch",
        lambda self, event: dispatched_events.append(event),
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        payload_voice_note_quote = {
            "event": "message",
            "payload": {
                "id": "msg_reply_vn",
                "from": "628111111111@c.us",
                "fromMe": False,
                "body": "kalo ini?",
                "hasMedia": False,
                "replyTo": {
                    "id": "msg_vn_1",
                    "from": "628222222222@c.us",
                    "participant": "628222222222@c.us",
                    "fromMe": False,
                    "type": "ptt",
                    "hasMedia": True,
                    "media": {
                        "url": "http://waha:3000/api/files/vn1.ogg",
                        "mimetype": "audio/ogg",
                    },
                },
            },
        }

        resp = await ac.post("/webhooks/waha", json=payload_voice_note_quote)
        assert resp.status_code == 200
        assert len(dispatched_events) == 1
        event = dispatched_events[0]
        assert event.sender_name == "Gilang"
        assert event.text == "kalo ini?"
        assert event.quoted_type == "ptt"
        assert event.quoted_sender == "Bunga"
        assert event.quoted_media_url == "http://waha:3000/api/files/vn1.ogg"


@pytest.mark.asyncio
async def test_webhook_extracts_gows_protobuf_context_info(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dispatched_events: list[IncomingMessageEvent] = []

    monkeypatch.setattr(webhook_mod, "GILANG_PHONE", "628111111111")
    monkeypatch.setattr(webhook_mod, "BUNGA_PHONE", "628222222222")
    monkeypatch.setattr(webhook_mod, "BOT_PHONE", "628999999999")

    client = WahaClient(base_url="http://test", api_key="test", session_name="default")
    app = webhook_mod.create_webhook_app(client)

    monkeypatch.setattr(
        queue_mod.ChatQueueManager,
        "dispatch",
        lambda self, event: dispatched_events.append(event),
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        payload_gows_vn = {
            "event": "message",
            "payload": {
                "id": "msg_gows_reply",
                "from": "120363411261097957@g.us",
                "participant": "628111111111@c.us",
                "fromMe": False,
                "body": "coba apa yang gw quote",
                "hasMedia": False,
                "_data": {
                    "Message": {
                        "extendedTextMessage": {
                            "text": "coba apa yang gw quote",
                            "contextInfo": {
                                "participant": "628222222222@c.us",
                                "quotedMessage": {
                                    "audioMessage": {
                                        "seconds": 8,
                                        "ptt": True,
                                        "mimetype": "audio/ogg; codecs=opus",
                                    }
                                },
                            },
                        }
                    }
                },
            },
        }

        resp = await ac.post("/webhooks/waha", json=payload_gows_vn)
        assert resp.status_code == 200
        assert len(dispatched_events) == 1
        event = dispatched_events[0]
        assert event.sender_name == "Gilang"
        assert event.text == "coba apa yang gw quote"
        assert event.quoted_type == "ptt"
        assert event.quoted_sender == "Bunga"
        assert "8 detik" in str(event.quoted_text)


@pytest.mark.asyncio
async def test_webhook_extracts_quoted_video_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dispatched_events: list[IncomingMessageEvent] = []

    monkeypatch.setattr(webhook_mod, "GILANG_PHONE", "628111111111")
    monkeypatch.setattr(webhook_mod, "BUNGA_PHONE", "628222222222")
    monkeypatch.setattr(webhook_mod, "BOT_PHONE", "628999999999")

    client = WahaClient(base_url="http://test", api_key="test", session_name="default")
    app = webhook_mod.create_webhook_app(client)

    monkeypatch.setattr(
        queue_mod.ChatQueueManager,
        "dispatch",
        lambda self, event: dispatched_events.append(event),
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        payload_video_quote = {
            "event": "message",
            "payload": {
                "id": "msg_reply_vid",
                "from": "628111111111@c.us",
                "fromMe": False,
                "body": "Itu video apa",
                "hasMedia": False,
                "_data": {
                    "Message": {
                        "extendedTextMessage": {
                            "text": "Itu video apa",
                            "contextInfo": {
                                "stanzaId": "vid_msg_123",
                                "participant": "628111111111@c.us",
                                "quotedMessage": {
                                    "videoMessage": {
                                        "caption": "lagi naik vespa",
                                        "mimetype": "video/mp4",
                                    }
                                },
                            },
                        }
                    }
                },
            },
        }

        resp = await ac.post("/webhooks/waha", json=payload_video_quote)
        assert resp.status_code == 200
        assert len(dispatched_events) == 1
        event = dispatched_events[0]
        assert event.sender_name == "Gilang"
        assert event.text == "Itu video apa"
        assert event.quoted_type == "video"
        assert event.quoted_sender == "Gilang"
        assert event.quoted_stanza_id == "vid_msg_123"
        assert "lagi naik vespa" in str(event.quoted_text)



