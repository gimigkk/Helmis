import pytest
from httpx import ASGITransport, AsyncClient

from src.whatsapp.webhook import create_webhook_app


class _Client:
    async def is_reachable(self) -> bool:
        return True


@pytest.mark.asyncio
async def test_status_broadcast_is_rejected_before_queue(monkeypatch) -> None:
    monkeypatch.delenv("WAHA_WEBHOOK_SECRET", raising=False)
    app = create_webhook_app(_Client())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/webhooks/waha",
            json={"event": "message", "payload": {"from": "status@broadcast", "body": "status"}},
        )
    assert response.json()["status"] == "ignored_status_event"


@pytest.mark.asyncio
async def test_webhook_secret_is_required_when_configured(monkeypatch) -> None:
    monkeypatch.setenv("WAHA_WEBHOOK_SECRET", "secret")
    app = create_webhook_app(_Client())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/webhooks/waha", json={"event": "unknown"})
        authorized = await client.post(
            "/webhooks/waha", headers={"x-waha-webhook-secret": "secret"}, json={"event": "unknown"}
        )
    assert response.status_code == 401
    assert authorized.status_code == 200


@pytest.mark.asyncio
async def test_scheduler_uses_a_separate_secret(monkeypatch) -> None:
    monkeypatch.delenv("WAHA_WEBHOOK_SECRET", raising=False)
    monkeypatch.setenv("SCHEDULER_WEBHOOK_SECRET", "scheduler-secret")
    app = create_webhook_app(_Client())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        wrong = await client.post("/webhooks/scheduler", json={"event": "unknown"})
        right = await client.post(
            "/webhooks/scheduler",
            headers={"x-scheduler-webhook-secret": "scheduler-secret"},
            json={"event": "unknown"},
        )
    assert wrong.status_code == 401
    assert right.status_code == 200
