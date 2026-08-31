"""Real-time event fan-out.

Two implementations share one interface. The in-process bus is the default and
is enough for a single API worker; the Redis-backed bus additionally survives
multiple workers by round-tripping every frame through pub/sub. Neither is
durable storage: PostgreSQL remains the source of truth and the event log here
is capped observability data.
"""

import asyncio
import contextlib
import json
import logging
from collections import deque
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)

EVENT_CHANNEL = "tsunagi:events"
EVENT_STREAM = "events:log"

LEVEL_INFO = "info"
LEVEL_WARN = "warn"
LEVEL_ERROR = "error"


@dataclass(slots=True)
class Event:
    type: str
    level: str
    payload: dict[str, Any]
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["timestamp"] = self.timestamp.isoformat()
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Event":
        return cls(
            type=data["type"],
            level=data["level"],
            payload=data.get("payload") or {},
            timestamp=datetime.fromisoformat(data["timestamp"]),
        )


class EventBus:
    """In-process fan-out with a capped event log."""

    def __init__(self, max_log: int = 1000) -> None:
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()
        self._log: deque[Event] = deque(maxlen=max_log)
        # An optional durable sink. Injected rather than imported so the bus
        # stays free of storage concerns; the log above remains capped and
        # transient regardless.
        self._audit_sink: Callable[[Event], Awaitable[None]] | None = None

    def set_audit_sink(self, sink: Callable[[Event], Awaitable[None]] | None) -> None:
        self._audit_sink = sink

    async def start(self) -> None:
        return None

    async def close(self) -> None:
        return None

    @property
    def redis(self) -> Any:
        """The shared Redis client, or None when running in-process.

        Exposed so other subsystems (the rate limiter) can reuse one connection
        pool rather than opening their own.
        """
        return None

    @asynccontextmanager
    async def subscribe(self) -> AsyncIterator[asyncio.Queue[dict[str, Any]]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=256)
        self._subscribers.add(queue)
        try:
            yield queue
        finally:
            self._subscribers.discard(queue)

    def _deliver_local(self, frame: dict[str, Any]) -> None:
        for queue in list(self._subscribers):
            try:
                queue.put_nowait(frame)
            except asyncio.QueueFull:
                # A slow consumer must not stall ingestion. Delivery is
                # best-effort by design; clients reconcile via the REST API.
                logger.warning("dropping frame for slow subscriber: %s", frame.get("type"))

    async def publish(self, frame: dict[str, Any]) -> None:
        self._deliver_local(frame)

    async def emit(self, type_: str, level: str = LEVEL_INFO, **payload: Any) -> Event:
        event = Event(type=type_, level=level, payload=payload)
        await self._record(event)
        if self._audit_sink is not None:
            await self._audit_sink(event)
        await self.publish({"type": "system.event", "data": event.to_dict()})
        return event

    async def _record(self, event: Event) -> None:
        self._log.append(event)

    async def recent(
        self, limit: int = 100, level: str | None = None, type_: str | None = None
    ) -> list[Event]:
        events = [
            event
            for event in reversed(self._log)
            if (level is None or event.level == level) and (type_ is None or event.type == type_)
        ]
        return events[:limit]


class RedisEventBus(EventBus):
    """Fan-out through Redis so every API worker sees every frame.

    Frames are delivered to local subscribers only via the pub/sub reader, never
    directly, so a publish reaches each subscriber exactly once regardless of
    which worker produced it.
    """

    def __init__(self, redis_url: str, max_log: int = 1000) -> None:
        super().__init__(max_log=max_log)
        self._redis_url = redis_url
        self._redis: Any = None
        self._pubsub: Any = None
        self._reader: asyncio.Task[None] | None = None

    async def start(self) -> None:
        import redis.asyncio as redis  # imported lazily so Redis stays optional

        self._redis = redis.from_url(self._redis_url, decode_responses=True)
        await self._redis.ping()
        self._pubsub = self._redis.pubsub(ignore_subscribe_messages=True)
        await self._pubsub.subscribe(EVENT_CHANNEL)
        self._reader = asyncio.create_task(self._read_loop())
        logger.info("event bus connected to redis at %s", self._redis_url)

    async def close(self) -> None:
        if self._reader is not None:
            self._reader.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._reader
        if self._pubsub is not None:
            await self._pubsub.aclose()
        if self._redis is not None:
            await self._redis.aclose()

    @property
    def redis(self) -> Any:
        return self._redis

    async def _read_loop(self) -> None:
        assert self._pubsub is not None
        while True:
            try:
                message = await self._pubsub.get_message(timeout=1.0)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("redis pub/sub read failed; retrying")
                await asyncio.sleep(1.0)
                continue
            if message is None:
                continue
            try:
                self._deliver_local(json.loads(message["data"]))
            except (ValueError, KeyError, TypeError):
                logger.exception("discarding malformed frame from redis")

    async def publish(self, frame: dict[str, Any]) -> None:
        if self._redis is None:
            self._deliver_local(frame)
            return
        await self._redis.publish(EVENT_CHANNEL, json.dumps(frame))

    async def _record(self, event: Event) -> None:
        if self._redis is None:
            await super()._record(event)
            return
        await self._redis.xadd(
            EVENT_STREAM,
            {"event": json.dumps(event.to_dict())},
            maxlen=self._log.maxlen,
            approximate=True,
        )

    async def recent(
        self, limit: int = 100, level: str | None = None, type_: str | None = None
    ) -> list[Event]:
        if self._redis is None:
            return await super().recent(limit=limit, level=level, type_=type_)
        # Over-read so filtering still returns a full page.
        entries = await self._redis.xrevrange(EVENT_STREAM, count=limit * 5 if limit else 100)
        events: list[Event] = []
        for _entry_id, fields in entries:
            try:
                event = Event.from_dict(json.loads(fields["event"]))
            except (ValueError, KeyError, TypeError):
                continue
            if level is not None and event.level != level:
                continue
            if type_ is not None and event.type != type_:
                continue
            events.append(event)
            if len(events) >= limit:
                break
        return events


def build_event_bus(redis_url: str | None, max_log: int) -> EventBus:
    if redis_url:
        return RedisEventBus(redis_url, max_log=max_log)
    return EventBus(max_log=max_log)
