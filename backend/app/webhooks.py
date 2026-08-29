"""Outbound webhook delivery.

The dashboard hears about events over a WebSocket, which works for as long as
someone has a browser open. A webhook is how something without a browser finds
out that an SMS arrived — a script, a ticketing system, a home automation box —
without polling for it.

Delivered over `urllib` in a worker thread rather than an async HTTP client. The
production install carries no HTTP client (`httpx` is a development dependency,
which is why `scripts/smoke_test.py` was rewritten on urllib), and adding one to
every deployment for a few small POSTs is a poor trade. Concurrency is bounded
by the worker count instead, so a phone uploading a backlog of five hundred
messages cannot open five hundred connections.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import secrets
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Awaitable, Callable

from app.db import get_session_factory
from app.events import LEVEL_ERROR, LEVEL_WARN, EventBus
from app.repositories import WebhookRepository

logger = logging.getLogger("tsunagi.webhooks")

#: Event types a webhook can subscribe to. Deliberately a short list: the bus
#: also carries per-pass sync chatter and the internal event log, neither of
#: which is worth waking somebody's server for.
DELIVERABLE_EVENTS = ("message.new", "device.status")

USER_AGENT = "Tsunagi-Webhook/1.0"
TIMEOUT_SECONDS = 10.0
#: Deliveries in flight at once. Bounds both threads and connections.
WORKERS = 4
#: Pending deliveries held before the oldest are dropped. A webhook is a
#: notification, not the record — the record is in the database either way.
QUEUE_SIZE = 1000
#: Consecutive failures before a webhook is switched off. A dead endpoint should
#: stop costing every message a timeout.
FAILURE_LIMIT = 20
#: Attempts per delivery, for a blip rather than a broken endpoint.
ATTEMPTS = 3


@dataclass(slots=True)
class Delivery:
    webhook_id: uuid.UUID
    url: str
    secret: str
    event: str
    data: dict[str, Any]


@dataclass(slots=True)
class DeliveryResult:
    ok: bool
    status: int | None = None
    error: str | None = None


#: Sends one signed request. Injected so tests can watch what would go out.
Transport = Callable[[str, bytes, dict[str, str]], Awaitable[DeliveryResult]]


def generate_secret() -> str:
    return secrets.token_urlsafe(32)


def sign(secret: str, timestamp: str, body: bytes) -> str:
    """The signature a receiver checks.

    Over `timestamp.body` rather than the body alone: signing the body by itself
    lets anyone who captures one delivery replay it forever, and the timestamp
    is what gives the receiver something to reject on.
    """
    payload = timestamp.encode() + b"." + body
    digest = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def render(event: str, data: dict[str, Any]) -> bytes:
    return json.dumps(
        {"event": event, "delivered_at": datetime.now(UTC).isoformat(), "data": data},
        separators=(",", ":"),
    ).encode()


async def send_over_http(url: str, body: bytes, headers: dict[str, str]) -> DeliveryResult:
    """The real transport. Blocking work is pushed to a thread."""

    def _send() -> DeliveryResult:
        request = urllib.request.Request(url, data=body, method="POST")
        for key, value in headers.items():
            request.add_header(key, value)
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
                # The body is read and discarded: a receiver that answers 200
                # with a megabyte of HTML should not be able to hold a worker.
                response.read(2048)
                return DeliveryResult(ok=True, status=response.status)
        except urllib.error.HTTPError as error:
            return DeliveryResult(ok=False, status=error.code, error=f"HTTP {error.code}")
        except Exception as error:  # noqa: BLE001 - any transport failure is the same here
            return DeliveryResult(ok=False, error=str(error)[:200])

    return await asyncio.to_thread(_send)


def _retryable(result: DeliveryResult) -> bool:
    """Whether trying the same request again could plausibly work.

    A 4xx is the receiver saying it understood and refused; repeating it just
    costs both sides. Anything else — no response at all, a 5xx, a 429 — is
    worth another go.
    """
    if result.status is None:
        return True
    return result.status >= 500 or result.status == 429


async def deliver(
    delivery: Delivery,
    transport: Transport = send_over_http,
    attempts: int = ATTEMPTS,
    backoff: float = 1.0,
) -> DeliveryResult:
    """One delivery, retried only where a retry could help."""
    timestamp = str(int(datetime.now(UTC).timestamp()))
    body = render(delivery.event, delivery.data)
    headers = {
        "Content-Type": "application/json",
        "User-Agent": USER_AGENT,
        "X-Tsunagi-Event": delivery.event,
        "X-Tsunagi-Delivery": str(uuid.uuid4()),
        "X-Tsunagi-Timestamp": timestamp,
        "X-Tsunagi-Signature": sign(delivery.secret, timestamp, body),
    }

    result = DeliveryResult(ok=False, error="not attempted")
    for attempt in range(attempts):
        result = await transport(delivery.url, body, headers)
        if result.ok or not _retryable(result):
            return result
        if attempt + 1 < attempts:
            await asyncio.sleep(backoff * (attempt + 1))
    return result


class WebhookDispatcher:
    """Watches the event bus and posts matching events to subscribed endpoints.

    Nothing here may slow ingestion down. The pump only enqueues, the queue is
    bounded, and a delivery that cannot be queued is dropped with a log line
    rather than blocking the request that produced the event.
    """

    def __init__(self, bus: EventBus, transport: Transport = send_over_http) -> None:
        self.bus = bus
        self.transport = transport
        self.queue: asyncio.Queue[Delivery] = asyncio.Queue(maxsize=QUEUE_SIZE)
        self._tasks: list[asyncio.Task[None]] = []
        self.dropped = 0

    async def start(self) -> None:
        self._tasks.append(asyncio.create_task(self._pump(), name="webhook-pump"))
        for index in range(WORKERS):
            self._tasks.append(
                asyncio.create_task(self._worker(), name=f"webhook-worker-{index}")
            )
        logger.info("webhook dispatcher started with %d worker(s)", WORKERS)

    async def close(self) -> None:
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            try:
                await task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        self._tasks.clear()

    async def _pump(self) -> None:
        async with self.bus.subscribe() as queue:
            while True:
                frame = await queue.get()
                event = frame.get("type")
                if event not in DELIVERABLE_EVENTS:
                    continue
                try:
                    await self._fan_out(event, frame.get("data") or {})
                except Exception:  # noqa: BLE001 - a bad frame must not stop the pump
                    logger.exception("webhook fan-out failed for %s", event)

    async def _fan_out(self, event: str, data: dict[str, Any]) -> None:
        async with get_session_factory()() as session:
            subscribers = await WebhookRepository(session).subscribed_to(event)

        for webhook in subscribers:
            delivery = Delivery(
                webhook_id=webhook.id,
                url=webhook.url,
                secret=webhook.secret,
                event=event,
                data=data,
            )
            try:
                self.queue.put_nowait(delivery)
            except asyncio.QueueFull:
                self.dropped += 1
                logger.warning(
                    "webhook queue full, dropping %s for %s", event, webhook.url
                )

    async def _worker(self) -> None:
        while True:
            delivery = await self.queue.get()
            try:
                result = await deliver(delivery, self.transport)
                await self._record(delivery, result)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - one bad delivery must not kill the worker
                logger.exception("webhook delivery raised for %s", delivery.url)
            finally:
                self.queue.task_done()

    async def _record(self, delivery: Delivery, result: DeliveryResult) -> None:
        async with get_session_factory()() as session:
            repository = WebhookRepository(session)
            webhook = await repository.get(delivery.webhook_id)
            if webhook is None:
                return
            disabled = await repository.record_attempt(
                webhook, ok=result.ok, status=result.status, error=result.error,
                failure_limit=FAILURE_LIMIT,
            )
            await session.commit()

        if not result.ok:
            logger.warning(
                "webhook delivery to %s failed: %s", delivery.url, result.error or result.status
            )
        if disabled:
            logger.error("webhook %s disabled after %d failures", delivery.url, FAILURE_LIMIT)
            await self.bus.emit(
                "WEBHOOK_DISABLED",
                LEVEL_ERROR,
                webhook_id=str(delivery.webhook_id),
                url=delivery.url,
                failures=FAILURE_LIMIT,
            )
        elif not result.ok:
            await self.bus.emit(
                "WEBHOOK_FAILED",
                LEVEL_WARN,
                webhook_id=str(delivery.webhook_id),
                url=delivery.url,
                status=result.status,
                error=result.error,
            )
