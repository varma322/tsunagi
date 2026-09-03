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
from typing import Any

from fastapi import status
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.errors import ApiError, describe_validation_error
from app.events import LEVEL_ERROR, LEVEL_INFO, LEVEL_WARN, EventBus
from app.models import ApiKey, Device, EnrolmentToken, Message
from app.repositories import (
    ApiKeyRepository,
    DeviceRepository,
    EnrolmentRepository,
    MessageRepository,
)
from app.schemas import (
    CaptureStatus,
    DeviceCheckInRequest,
    DeviceOut,
    MessageCreate,
    MessageOut,
    MessageResult,
)
from app.security import (
    API_KEY_PREFIX,
    as_utc,
    generate_api_key,
    generate_device_token,
    generate_enrolment_code,
    hash_secret,
    normalize_enrolment_code,
)


def _readable_uuid(payload: Any) -> uuid.UUID | None:
    """The message id, if this payload has one that parses.

    A rejected message is matched back to the client's own row by id, so it is
    worth salvaging even from a payload that is otherwise unusable.
    """
    if not isinstance(payload, dict):
        return None
    try:
        return uuid.UUID(str(payload.get("id")))
    except (ValueError, TypeError):
        return None


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

    def capture_status(self, device: Device) -> CaptureStatus:
        """Whether this device can still receive SMS.

        Deliberately separate from is_online. A phone answers the heartbeat as
        long as the app can run at all, which says nothing about whether the
        platform will still hand it a message — the case this exists for is a
        revoked SMS permission, where the app keeps checking in and captures
        nothing.
        """
        if device.capture_reported_at is None:
            # An app older than the check-in. Reporting "ok" would invent a
            # reassurance the device never gave.
            return "unknown"
        if not device.capture_permitted or not device.inbox_readable:
            return "blocked"
        return "ok"

    def to_out(self, device: Device) -> DeviceOut:
        return DeviceOut(
            id=device.id,
            name=device.name,
            status=self.is_online(device),
            enabled=device.is_active,
            last_seen=device.last_seen,
            created_at=device.created_at,
            disabled_at=device.disabled_at,
            capture=self.capture_status(device),
            capture_reported_at=device.capture_reported_at,
            capture_permitted=device.capture_permitted,
            inbox_readable=device.inbox_readable,
            battery_exempt=device.battery_exempt,
            last_captured_at=device.last_captured_at,
            last_swept_at=device.last_swept_at,
        )

    async def record_check_in(self, device: Device, report: DeviceCheckInRequest) -> Device:
        """Store what a phone says about its own capture path.

        Announced only on a change. A blocked device checks in every fifteen
        minutes, and an event per pass would bury the transition that matters
        in a log of identical lines.
        """
        before = self.capture_status(device)
        await self.devices.record_capture(
            device,
            capture_permitted=report.capture_permitted,
            inbox_readable=report.inbox_readable,
            battery_exempt=report.battery_exempt,
            last_captured_at=report.last_captured_at,
            last_swept_at=report.last_swept_at,
        )
        await self.session.commit()

        after = self.capture_status(device)
        if after != before:
            await self._announce_capture(device, before, after)
        return device

    async def _announce_capture(
        self, device: Device, before: CaptureStatus, after: CaptureStatus
    ) -> None:
        if after == "blocked":
            await self.bus.emit(
                "DEVICE_CAPTURE_BLOCKED",
                LEVEL_ERROR,
                device_id=str(device.id),
                name=device.name,
                reason=self.capture_reason(device),
            )
        elif before == "blocked":
            await self.bus.emit(
                "DEVICE_CAPTURE_RESTORED",
                LEVEL_INFO,
                device_id=str(device.id),
                name=device.name,
            )
        else:
            # unknown -> ok, which is an app being upgraded rather than a
            # device changing state. Nothing worth logging.
            return

        await self.bus.publish(
            {
                "type": "device.status",
                "data": {
                    "device_id": str(device.id),
                    "status": self.is_online(device),
                    "enabled": device.is_active,
                    "capture": after,
                },
            }
        )

    @staticmethod
    def capture_reason(device: Device) -> str | None:
        """Why capture is blocked, in the words the dashboard shows."""
        if device.capture_permitted is False:
            return "SMS permission has been revoked on the device."
        if device.inbox_readable is False:
            return "The device cannot read its SMS inbox, so the sweep cannot recover a miss."
        return None

    async def list_devices(self) -> list[Device]:
        return await self.devices.list_all()

    async def revoke(self, device: Device) -> None:
        await self.devices.revoke(device)
        await self.session.commit()
        await self.bus.emit("DEVICE_REVOKED", LEVEL_WARN, device_id=str(device.id))
        await self.bus.publish(
            {"type": "device.status", "data": {"device_id": str(device.id), "status": False}}
        )

    async def clear_messages(self, device: Device) -> int:
        """Permanently delete a device's messages, returning how many.

        The only destructive operation in the API. Everything else that looks
        like a delete is reversible -- an off switch, a revocation that keeps
        the row -- so this one is deliberately explicit rather than folded into
        revoke, where an operator retiring a phone would trigger it without
        having decided to.

        The audit event is the point of care here. After this commits, the
        messages are gone and the trail is the only remaining record that they
        existed at all, so it carries the device, its name and the count.

        No guard on a revoked device: clearing a retired phone's messages is
        the ordinary reason to reach for this.
        """
        deleted = await self.messages.delete_for_device(device.id)
        await self.session.commit()
        await self.bus.emit(
            "DEVICE_MESSAGES_CLEARED",
            LEVEL_WARN,
            device_id=str(device.id),
            name=device.name,
            count=deleted,
        )
        return deleted


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

    @staticmethod
    def parse_batch(payloads: list[Any]) -> tuple[list[tuple[int, MessageCreate]], list[MessageResult]]:
        """Split a batch into the messages that can be stored and those that cannot.

        Validating per message is the whole point: one unacceptable message
        used to reject every message it travelled with, and the response could
        not say which one was at fault, so the client had to find out by
        re-uploading them one at a time.
        """
        valid: list[tuple[int, MessageCreate]] = []
        rejected: list[MessageResult] = []
        for index, payload in enumerate(payloads):
            try:
                valid.append((index, MessageCreate.model_validate(payload)))
            except ValidationError as error:
                rejected.append(
                    MessageResult(
                        index=index,
                        # Only if the id itself survived; it is what a client
                        # matches the verdict back to its own row by.
                        id=_readable_uuid(payload),
                        status="rejected",
                        error=describe_validation_error(error, prefix=f"messages.{index}"),
                    )
                )
        return valid, rejected

    async def ingest_batch(
        self, device: Device, payloads: list[MessageCreate]
    ) -> tuple[int, int, list[bool]]:
        """Store a batch, reporting per message whether it was new.

        The third element is aligned with `payloads`, so a caller can tell a
        client which of its messages were stored and which it had already sent.
        """
        fresh: list[Message] = []
        created_flags: list[bool] = []
        for payload in payloads:
            message, created = await self.messages.insert_if_absent(
                message_id=payload.id,
                device_id=device.id,
                sender=payload.sender,
                body=payload.body,
                received_at=payload.received_at,
            )
            created_flags.append(created)
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
        return len(fresh), len(payloads) - len(fresh), created_flags

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
