"""Webhook ingestion integration: group admission + durable replay dedup."""

import pytest
from httpx import ASGITransport, AsyncClient

from src.memory.task_repository import TaskRepository
from src.whatsapp.webhook import create_webhook_app


@pytest.fixture(autouse=True)
def _owner_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Identity resolution requires a known owner phone and authorized group."""
    monkeypatch.setenv("OWNER_PHONE", "628222000000")
    monkeypatch.setenv("TRIO_GROUP_JID", "120363021816354259@g.us")
    monkeypatch.delenv("WAHA_WEBHOOK_SECRET", raising=False)


class _Client:
    async def is_reachable(self) -> bool:
        return True


def _message_payload(**overrides):
    payload = {
        "from": "628222000000@c.us",
        "body": "halo helmis",
        "fromMe": False,
        "id": "false_628222000000@c.us_MSG1",
    }
    payload.update(overrides)
    return payload


@pytest.mark.asyncio
async def test_group_message_directed_at_other_human_is_ignored() -> None:
    app = create_webhook_app(_Client())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/webhooks/waha",
            json={
                "event": "message",
                "payload": _message_payload(
                    **{
                        "from": "120363021816354259@g.us",
                        "author": "628222000000@c.us",
                        "body": "@bunga kamu dimana",
                    }
                ),
            },
        )
    assert response.json()["status"] == "ignored_directed_to_other"


@pytest.mark.asyncio
async def test_group_message_addressing_bot_is_queued() -> None:
    app = create_webhook_app(_Client())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/webhooks/waha",
            json={
                "event": "message",
                "payload": _message_payload(
                    **{
                        "from": "120363021816354259@g.us",
                        "author": "628222000000@c.us",
                        "id": "false_group_BOT_OK",
                    }
                ),
            },
        )
    assert response.json()["status"] == "queued"


@pytest.mark.asyncio
async def test_replayed_message_id_is_rejected_durably() -> None:
    from src.whatsapp.history import _seen_message_ids

    app = create_webhook_app(_Client())
    message_id = "false_628222000000@c.us_DUP"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        first = await client.post(
            "/webhooks/waha", json={"event": "message", "payload": _message_payload(id=message_id)}
        )
        # Simulate a restart: the in-memory 60s cache is gone, the durable
        # processed-messages record must still catch the replay.
        _seen_message_ids.clear()
        fresh_app = create_webhook_app(_Client())
        async with AsyncClient(transport=ASGITransport(app=fresh_app), base_url="http://test") as fresh:
            second = await fresh.post(
                "/webhooks/waha",
                json={"event": "message", "payload": _message_payload(id=message_id)},
            )
    assert first.json()["status"] == "queued"
    assert second.json()["status"] == "ignored_replayed_message"


@pytest.mark.asyncio
async def test_unauthorized_group_jid_is_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    # webhook.py imports TRIO_GROUP_JID at module load; patch there directly.
    import src.whatsapp.webhook as webhook_module

    monkeypatch.setattr(webhook_module, "TRIO_GROUP_JID", "120363021816354259@g.us")
    app = create_webhook_app(_Client())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/webhooks/waha",
            json={
                "event": "message",
                "payload": _message_payload(
                    **{
                        "from": "999888777@g.us",
                        "author": "628222000000@c.us",
                        "id": "false_group_UNAUTH",
                    }
                ),
            },
        )
    assert response.json()["status"] == "ignored_non_whitelisted_group"


@pytest.mark.asyncio
async def test_distinct_message_ids_are_not_confused() -> None:
    app = create_webhook_app(_Client())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        one = await client.post(
            "/webhooks/waha",
            json={"event": "message", "payload": _message_payload(id="false_x_A")},
        )
        two = await client.post(
            "/webhooks/waha",
            json={"event": "message", "payload": _message_payload(id="false_x_B")},
        )
    assert one.json()["status"] == "queued"
    assert two.json()["status"] == "queued"


def test_register_seen_message_window_expiry() -> None:
    import os

    db_path = os.environ["HELMIS_DB_PATH"]
    repo = TaskRepository(db_path)
    assert repo.register_seen_message("m1", now=1000.0) is False
    assert repo.register_seen_message("m1", now=1000.0 + 10) is True
    # Past the window the same ID is treated as new again.
    assert repo.register_seen_message("m1", now=1000.0 + 7200.0, window_seconds=3600.0) is False
    assert repo.list_processed_message_ids() == ["m1"]

    # Empty IDs never register.
    assert repo.register_seen_message("", now=1000.0) is False
    assert repo.register_seen_message("   ", now=1000.0) is False
