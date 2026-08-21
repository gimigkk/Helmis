"""
queue.py — Per-Chat FIFO Turn Queue with 1.0s Burst Debouncing for Helmis.

Provides:
- Independent asynchronous workers per chat_id (Gilang DM, Bunga DM, Group Chat run concurrently).
- 1.0-second burst debouncer that combines rapid multi-line user messages into a single prompt.
- Strict sequential FIFO execution within each chat to eliminate race conditions.
"""

import asyncio
import logging
import time
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from typing import Any

log = logging.getLogger("helmis-queue")


@dataclass
class IncomingMessageEvent:
    sender_name: str
    from_user: str
    reply_id: str | None
    text: str
    has_media: bool
    media_url: str | None
    media_type: str | None
    timestamp: float
    quoted_text: str | None = None
    quoted_sender: str | None = None


class ChatQueueWorker:
    """Manages sequential execution and burst message combining for a single chat_id."""

    def __init__(
        self,
        chat_id: str,
        turn_handler: Callable[[list[IncomingMessageEvent]], Coroutine[Any, Any, None]],
        debounce_seconds: float = 1.0,
    ) -> None:
        self.chat_id = chat_id
        self.turn_handler = turn_handler
        self.debounce_seconds = debounce_seconds
        self.queue: asyncio.Queue[IncomingMessageEvent] = asyncio.Queue()
        self.worker_task: asyncio.Task[None] | None = None
        self._running = True

    def enqueue(self, event: IncomingMessageEvent) -> None:
        """Enqueue an incoming message event."""
        self.queue.put_nowait(event)
        if not self.worker_task or self.worker_task.done():
            self.worker_task = asyncio.create_task(self._worker_loop())

    async def _worker_loop(self) -> None:
        """Worker loop that debounces and processes turns sequentially."""
        while self._running:
            try:
                # Wait for at least one message
                first_event = await self.queue.get()
                batch = [first_event]

                # Burst Debouncer: wait debounce_seconds to collect rapid follow-up messages
                start_wait = time.time()
                step_sleep = max(0.02, min(0.05, self.debounce_seconds / 5))
                while time.time() - start_wait < self.debounce_seconds:
                    await asyncio.sleep(step_sleep)
                    while not self.queue.empty():
                        extra_event = self.queue.get_nowait()
                        batch.append(extra_event)
                        start_wait = time.time()

                log.debug(
                    "Chat [%s] debounced %d message(s) into single turn.",
                    self.chat_id,
                    len(batch),
                )

                # Process turn sequentially
                try:
                    await self.turn_handler(batch)
                except Exception as e:
                    log.exception("Error processing turn for chat [%s]: %s", self.chat_id, e)

            except asyncio.CancelledError:
                break
            except Exception as e:
                log.exception("Unexpected error in chat worker loop [%s]: %s", self.chat_id, e)
                await asyncio.sleep(0.5)


class ChatQueueManager:
    """Global manager maintaining independent ChatQueueWorkers per chat_id."""

    def __init__(
        self,
        turn_handler: Callable[[list[IncomingMessageEvent]], Coroutine[Any, Any, None]],
        debounce_seconds: float = 1.0,
    ) -> None:
        self.turn_handler = turn_handler
        self.debounce_seconds = debounce_seconds
        self.workers: dict[str, ChatQueueWorker] = {}

    def dispatch(self, event: IncomingMessageEvent) -> None:
        """Route event to its chat-specific worker."""
        chat_id = event.from_user
        if chat_id not in self.workers:
            self.workers[chat_id] = ChatQueueWorker(
                chat_id=chat_id,
                turn_handler=self.turn_handler,
                debounce_seconds=self.debounce_seconds,
            )
        self.workers[chat_id].enqueue(event)
