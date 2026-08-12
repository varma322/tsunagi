"""Business logic. Routers handle HTTP concerns only and delegate here.

Services own their transaction boundary: they commit before publishing, so a
client woken by an event always finds the row already visible in PostgreSQL.
"""

# Required for the same reason as in repositories.py: MessageService.list
# shadows the builtin for annotations later in the class body.
from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.errors import ApiError
from app.events import LEVEL_INFO, LEVEL_WARN, EventBus
from app.models import ApiKey, Device, EnrolmentToken, Message
from app.repositories import (
    ApiKeyRepository,
    DeviceRepository,
    EnrolmentRepository,
    MessageRepository,
)
from app.schemas import MessageCreate, MessageOut
from app.security import (
    API_KEY_PREFIX,
    as_utc,
    generate_api_key,
    generate_device_token,
    generate_enrolment_code,
    hash_secret,
    normalize_enrolment_code,
)


class DeviceService:
    def __init__(self, session: AsyncSession, bus: EventBus, settings: Settings) -> None:
        self.session = session
        self.bus = bus
        self.settings = settings
        self.devices = DeviceRepository(session)
        self.messages = MessageRepository(session)

    def is_online(self, device: Device) -> bool:
        # A switched-off device is never "online", however recently it called.
        if not device.is_active:
            return False
        last_seen = as_utc(device.last_seen)
        if last_seen is None:
            return False
        window = timedelta(seconds=self.settings.device_online_window_seconds)
        return datetime.now(UTC) - last_seen <= window

    async def set_enabled(self, device: Device, enabled: bool) -> None:
        await self.devices.set_disabled(device, disabled=not enabled)
        await self.session.commit()
        await self.bus.emit(
            "DEVICE_ENABLED" if enabled else "DEVICE_DISABLED",
            LEVEL_INFO if enabled else LEVEL_WARN,
            device_id=str(device.id),
            name=device.name,
        )
        await self.bus.publish(
            {
                "type": "device.status",
                "data": {"device_id": str(device.id), "status": False, "enabled": enabled},
            }
        )

    async def register(
        self, name: str, enrolment: EnrolmentToken | None = None
    ) -> tuple[Device, str]:
        """Register a device, spending an enrolment code if one was presented.

        The code is consumed in the same transaction as the device row, so a
        failure at either step leaves neither behind.
        """
        token = generate_device_token()
        device = await self.devices.create(name=name, token_hash=hash_secret(token))

        if enrolment is not None:
            spent = await EnrolmentRepository(self.session).consume(enrolment.id, device.id)
            if not spent:
                # Lost a race with a concurrent registration using the same code.
                await self.session.rollback()
                raise ApiError(
                    status.HTTP_403_FORBIDDEN,
                    "enrolment_used",
                    "This enrolment code has already been used.",
                )

        await self.session.commit()
        await self.bus.emit(
            "DEVICE_REGISTERED",
            LEVEL_INFO,
            device_id=str(device.id),
            name=device.name,
            enrolment_id=str(enrolment.id) if enrolment else None,
        )
        if enrolment is not None:
            await self.bus.emit(
                "ENROLMENT_USED",
                LEVEL_INFO,
                enrolment_id=str(enrolment.id),
                device_id=str(device.id),
            )
        return device, token

    async def list_devices(self) -> list[Device]:
        return await self.devices.list_all()

    async def revoke(self, device: Device) -> None:
        await self.devices.revoke(device)
        await self.session.commit()
        await self.bus.emit("DEVICE_REVOKED", LEVEL_WARN, device_id=str(device.id))
        await self.bus.publish(
            {"type": "device.status", "data": {"device_id": str(device.id), "status": False}}
        )


class EnrolmentService:
    def __init__(self, session: AsyncSession, bus: EventBus, settings: Settings) -> None:
        self.session = session
        self.bus = bus
        self.settings = settings
        self.enrolments = EnrolmentRepository(session)

    async def issue(
        self,
        *,
        label: str | None,
        ttl_seconds: int | None,
        created_by_key_id: uuid.UUID | None,
    ) -> tuple[EnrolmentToken, str]:
        code = generate_enrolment_code()
        ttl = ttl_seconds or self.settings.enrolment_token_ttl_seconds
        token = await self.enrolments.create(
            code_hash=hash_secret(normalize_enrolment_code(code)),
            expires_at=datetime.now(UTC) + timedelta(seconds=ttl),
            label=label,
            created_by_key_id=created_by_key_id,
        )
        await self.session.commit()
        await self.bus.emit(
            "ENROLMENT_CREATED",
            LEVEL_INFO,
            enrolment_id=str(token.id),
            label=label,
            ttl_seconds=ttl,
        )
        return token, code

    async def list_recent(self) -> list[EnrolmentToken]:
        return await self.enrolments.list_recent()

    async def cancel(self, token: EnrolmentToken) -> bool:
        cancelled = await self.enrolments.cancel(token)
        await self.session.commit()
        if cancelled:
            await self.bus.emit("ENROLMENT_CANCELLED", LEVEL_WARN, enrolment_id=str(token.id))
        return cancelled


class MessageService:
    def __init__(self, session: AsyncSession, bus: EventBus, settings: Settings) -> None:
        self.session = session
        self.bus = bus
        self.settings = settings
        self.messages = MessageRepository(session)
        self.devices = DeviceRepository(session)

    async def ingest(self, device: Device, payload: MessageCreate) -> tuple[Message, bool]:
        message, created = await self.messages.insert_if_absent(
            message_id=payload.id,
            device_id=device.id,
            sender=payload.sender,
            body=payload.body,
            received_at=payload.received_at,
        )
        await self.session.commit()
        if created:
            await self._announce(message)
        return message, created

    async def ingest_batch(self, device: Device, payloads: list[MessageCreate]) -> tuple[int, int]:
        fresh: list[Message] = []
        for payload in payloads:
            message, created = await self.messages.insert_if_absent(
                message_id=payload.id,
                device_id=device.id,
                sender=payload.sender,
                body=payload.body,
                received_at=payload.received_at,
            )
            if created:
                fresh.append(message)
        await self.session.commit()
        for message in fresh:
            await self._announce(message)
        if fresh:
            await self.bus.publish(
                {
                    "type": "sync.event",
                    "data": {"device_id": str(device.id), "uploaded": len(fresh)},
                }
            )
        await self.bus.emit(
            "SYNC_OK",
            LEVEL_INFO,
            device_id=str(device.id),
            received=len(payloads),
            stored=len(fresh),
        )
        return len(fresh), len(payloads) - len(fresh)

    async def _announce(self, message: Message) -> None:
        frame = MessageOut.model_validate(message).model_dump(mode="json")
        await self.bus.publish({"type": "message.new", "data": frame})
        await self.bus.emit(
            "MSG_RECV",
            LEVEL_INFO,
            id=str(message.id),
            device_id=str(message.device_id),
            sender=message.sender,
            length=len(message.body),
        )

    async def list(
        self,
        *,
        limit: int,
        offset: int,
        sender: str | None = None,
        device_id: uuid.UUID | None = None,
        after: datetime | None = None,
        before: datetime | None = None,
        query: str | None = None,
    ) -> tuple[int, list[Message]]:
        return await self.messages.list(
            limit=limit,
            offset=offset,
            sender=sender,
            device_id=device_id,
            after=after,
            before=before,
            query=query,
        )

    async def wait_for_new(
        self, *, since: datetime, timeout: float, sender: str | None = None
    ) -> list[Message]:
        """Long-poll for messages stored after `since`.

        Subscription happens before the first read so a message arriving in
        between is not missed.
        """
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        async with self.bus.subscribe() as queue:
            backlog = await self.messages.list_since(since=since, sender=sender)
            if backlog:
                return backlog

            while True:
                remaining = deadline - loop.time()
                if remaining <= 0:
                    return []
                try:
                    frame = await asyncio.wait_for(queue.get(), timeout=remaining)
                except (TimeoutError, asyncio.TimeoutError):
                    return []
                if frame.get("type") != "message.new":
                    continue
                # End the read transaction so the follow-up query observes rows
                # committed by the request that produced this frame.
                await self.session.rollback()
                found = await self.messages.list_since(since=since, sender=sender)
                if found:
                    return found

    async def volume(self, days: int) -> list[dict[str, object]]:
        """Daily message counts for the last `days` days, including empty days
        so the caller can chart a continuous axis."""
        today = datetime.now(UTC).date()
        start = today - timedelta(days=days - 1)
        counts = await self.messages.daily_counts(
            since=datetime.combine(start, datetime.min.time(), tzinfo=UTC)
        )
        return [
            {"date": (day := (start + timedelta(days=offset))).isoformat(),
             "count": counts.get(day.isoformat(), 0)}
            for offset in range(days)
        ]

    async def stats(self) -> dict[str, int]:
        midnight = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        cutoff = datetime.now(UTC) - timedelta(seconds=self.settings.device_online_window_seconds)
        return {
            "messages_total": await self.messages.count(),
            "messages_today": await self.messages.count_since(midnight),
            "active_devices": await self.devices.count_active_since(cutoff),
            "storage_bytes": await self.messages.storage_bytes(),
        }


class ApiKeyService:
    def __init__(self, session: AsyncSession, bus: EventBus) -> None:
        self.session = session
        self.bus = bus
        self.keys = ApiKeyRepository(session)

    async def create(self, name: str, scope: str, raw: str | None = None) -> tuple[ApiKey, str]:
        raw = raw or generate_api_key()
        api_key = await self.keys.create(name=name, key_hash=hash_secret(raw), scope=scope)
        await self.session.commit()
        await self.bus.emit("KEY_CREATED", LEVEL_INFO, key_id=str(api_key.id), name=name)
        return api_key, raw

    async def list_keys(self) -> list[ApiKey]:
        return await self.keys.list_all()

    async def revoke(self, api_key: ApiKey) -> None:
        await self.keys.revoke(api_key)
        await self.session.commit()
        await self.bus.emit("KEY_REVOKED", LEVEL_WARN, key_id=str(api_key.id))

    async def ensure_bootstrap_key(self, preset: str | None = None) -> str | None:
        """Mint an admin key on a fresh install so the deployment is usable.

        Returns None when keys already exist, so restarts do not accumulate
        credentials.
        """
        if await self.keys.count_active() > 0:
            return None
        if preset and not preset.startswith(API_KEY_PREFIX):
            # The prefix is how the authenticator tells keys from device tokens.
            preset = API_KEY_PREFIX + preset
        _api_key, raw = await self.create("bootstrap-admin", "admin", raw=preset)
        return raw
