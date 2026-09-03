"""Durable outbox delivery worker primitives.

The drain loop is the only component allowed to retry failed sends; inline
senders enqueue and optionally deliver once, while the loop owns recovery
after crashes, restarts, and provider failures.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
import uuid

from ..memory.store import get_repository
from ..whatsapp.client import WahaClient

log = logging.getLogger("helmis-delivery")

_DEFAULT_DRAIN_INTERVAL = 15.0


async def deliver_outbox_batch(
    client: WahaClient, *, limit: int = 50, lease_seconds: float = 60.0,
    outbox_id: str | None = None,
) -> dict[str, int]:
    """Deliver one claimed outbox batch and record every provider attempt."""
    repository = get_repository()
    claim_token = str(uuid.uuid4())
    now = time.time()
    rows = (
        [row] if (row := repository.claim_outbox_id(outbox_id, now, lease_seconds, claim_token)) else []
        if outbox_id
        else repository.claim_outbox(now, lease_seconds, claim_token, limit)
    )
    delivered = 0
    failed = 0
    for row in rows:
        try:
            payload = json.loads(str(row["payload_json"]))
            response = await client.send_message(
                chat_id=str(row["target_chat"]), text=str(payload.get("text", ""))
            )
            provider_id = None
            if isinstance(response, dict):
                provider_id = response.get("id") or response.get("messageId")
            repository.record_delivery_attempt(
                str(row["outbox_id"]), claim_token, "delivered",
                provider_message_id=str(provider_id) if provider_id else None,
            )
            delivered += 1
        except Exception as exc:
            repository.record_delivery_attempt(
                str(row["outbox_id"]), claim_token, "failed", error=str(exc)
            )
            failed += 1
    return {"claimed": len(rows), "delivered": delivered, "failed": failed}


async def run_outbox_drain_loop(
    client: WahaClient,
    *,
    interval_seconds: float = _DEFAULT_DRAIN_INTERVAL,
) -> None:
    """Drain the durable outbox forever, reclaiming expired leases and retries.

    Runs until the enclosing task is cancelled; cancellation is expected on
    shutdown and is not an error.
    """
    log.info("Outbox drain loop started (interval: %.1fs)", interval_seconds)
    while True:
        try:
            result = await deliver_outbox_batch(client)
            if result["claimed"]:
                log.info(
                    "Outbox drain: %d claimed, %d delivered, %d failed",
                    result["claimed"], result["delivered"], result["failed"],
                )
        except asyncio.CancelledError:
            log.info("Outbox drain loop stopped")
            raise
        except Exception as exc:
            log.error("Outbox drain cycle failed: %s", exc)
        await asyncio.sleep(interval_seconds)


def start_outbox_drain_loop(client: WahaClient, *, interval_seconds: float = _DEFAULT_DRAIN_INTERVAL) -> asyncio.Task[None]:
    """Start the drain loop as a background task on the running event loop."""
    return asyncio.create_task(
        run_outbox_drain_loop(client, interval_seconds=interval_seconds),
        name="outbox-drain-loop",
    )


@contextlib.asynccontextmanager
async def outbox_drain_lifespan(client: WahaClient, *, interval_seconds: float = _DEFAULT_DRAIN_INTERVAL):
    """Starlette lifespan that runs the outbox drain loop for the app's lifetime."""
    task = start_outbox_drain_loop(client, interval_seconds=interval_seconds)
    try:
        yield
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
