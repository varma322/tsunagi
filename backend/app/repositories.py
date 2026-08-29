"""Persistence layer. Services depend on these; nothing above this module
issues SQL directly."""

# Required: MessageRepository defines a method named `list`, which shadows the
# builtin for every annotation evaluated after it in the class body. Deferring
# annotation evaluation keeps `list[Message]` meaning the builtin. Python 3.14
# does this by default, so without it the module imports locally and fails on
# the 3.12 runtime used in the container.
from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import datetime

from sqlalchemy import Select, delete, func, select, text, tuple_, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ApiKey, Device, EnrolmentToken, Message, utcnow


class DeviceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, device_id: uuid.UUID) -> Device | None:
        return await self.session.get(Device, device_id)

    async def get_by_token_hash(self, token_hash: str) -> Device | None:
        """Matches on the token alone, including suspended and revoked devices.

        The caller distinguishes "unknown token" from "known but switched off",
        which is what lets the API answer 403 instead of 401 — the phone treats
        401 as a reason to re-enrol.
        """
        result = await self.session.execute(
            select(Device).where(Device.token_hash == token_hash)
        )
        return result.scalar_one_or_none()

    async def list_all(self) -> list[Device]:
        """Active and suspended devices. Revoked ones are gone for good."""
        result = await self.session.execute(
            select(Device).where(Device.revoked_at.is_(None)).order_by(Device.created_at.desc())
        )
        return list(result.scalars())

    async def set_disabled(self, device: Device, disabled: bool) -> None:
        device.disabled_at = utcnow() if disabled else None
        await self.session.flush()

    async def create(self, name: str, token_hash: str) -> Device:
        device = Device(name=name, token_hash=token_hash)
        self.session.add(device)
        await self.session.flush()
        return device

    async def touch(self, device: Device) -> None:
        device.last_seen = utcnow()
        await self.session.flush()

    async def record_capture(
        self,
        device: Device,
        *,
        capture_permitted: bool,
        inbox_readable: bool,
        battery_exempt: bool,
        last_captured_at: datetime | None,
        last_swept_at: datetime | None,
    ) -> None:
        """Store the device's own account of whether it can still receive SMS.

        last_seen is not touched here: every authenticated device call already
        refreshes it, and this one is no more proof of presence than any other.
        """
        device.capture_reported_at = utcnow()
        device.capture_permitted = capture_permitted
        device.inbox_readable = inbox_readable
        device.battery_exempt = battery_exempt
        device.last_captured_at = last_captured_at
        device.last_swept_at = last_swept_at
        await self.session.flush()

    async def revoke(self, device: Device) -> None:
        device.revoked_at = utcnow()
        await self.session.flush()

    async def count_active_since(self, cutoff: datetime) -> int:
        result = await self.session.execute(
            select(func.count())
            .select_from(Device)
            .where(
                Device.revoked_at.is_(None),
                Device.disabled_at.is_(None),
                Device.last_seen >= cutoff,
            )
        )
        return int(result.scalar_one())


class MessageRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    @property
    def _dialect(self) -> str:
        return self.session.bind.dialect.name if self.session.bind is not None else "sqlite"

    async def get(self, message_id: uuid.UUID) -> Message | None:
        return await self.session.get(Message, message_id)

    async def insert_if_absent(
        self,
        *,
        message_id: uuid.UUID,
        device_id: uuid.UUID,
        sender: str,
        body: str,
        received_at: datetime,
    ) -> tuple[Message, bool]:
        """Insert a message, returning (message, created). Retried uploads of an
        already-stored id resolve to the existing row rather than a duplicate."""
        message = Message(
            id=message_id,
            device_id=device_id,
            sender=sender,
            body=body,
            received_at=received_at,
        )
        try:
            async with self.session.begin_nested():
                self.session.add(message)
                await self.session.flush()
        except IntegrityError:
            existing = await self.get(message_id)
            if existing is None:  # pragma: no cover - only on a FK violation
                raise
            return existing, False
        return message, True

    def _apply_filters(
        self,
        statement: Select,
        *,
        sender: str | None,
        device_id: uuid.UUID | None,
        after: datetime | None,
        before: datetime | None,
    ) -> Select:
        if sender is not None:
            statement = statement.where(Message.sender == sender)
        if device_id is not None:
            statement = statement.where(Message.device_id == device_id)
        if after is not None:
            statement = statement.where(Message.received_at > after)
        if before is not None:
            statement = statement.where(Message.received_at < before)
        return statement

    def _apply_search(self, statement: Select, query: str) -> Select:
        if self._dialect == "postgresql":
            return statement.where(
                text("to_tsvector('simple', messages.body) @@ plainto_tsquery('simple', :q)")
            ).params(q=query)
        # SQLite and other dialects have no tsvector; substring match is the
        # documented fallback for development installs.
        return statement.where(Message.body.ilike(f"%{query}%"))

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
        base = self._apply_filters(
            select(Message), sender=sender, device_id=device_id, after=after, before=before
        )
        if query:
            base = self._apply_search(base, query)

        count_statement = select(func.count()).select_from(base.subquery())
        total = int((await self.session.execute(count_statement)).scalar_one())

        rows = await self.session.execute(
            base.order_by(Message.received_at.desc(), Message.id).limit(limit).offset(offset)
        )
        return total, list(rows.scalars())

    async def iter_filtered(
        self,
        *,
        sender: str | None = None,
        device_id: uuid.UUID | None = None,
        after: datetime | None = None,
        before: datetime | None = None,
        query: str | None = None,
        chunk: int = 1000,
    ) -> AsyncIterator[list[Message]]:
        """Every matching message, oldest first, a chunk at a time.

        Paged by keyset rather than OFFSET: an export of a large table walks the
        index once instead of re-scanning and discarding a growing prefix, and a
        message arriving mid-export cannot shift rows onto a page already sent.
        """
        base = self._apply_filters(
            select(Message), sender=sender, device_id=device_id, after=after, before=before
        )
        if query:
            base = self._apply_search(base, query)

        cursor: tuple[datetime, uuid.UUID] | None = None
        while True:
            statement = base.order_by(Message.received_at.asc(), Message.id.asc()).limit(chunk)
            if cursor is not None:
                statement = statement.where(
                    tuple_(Message.received_at, Message.id) > cursor
                )
            rows = list((await self.session.execute(statement)).scalars())
            if not rows:
                return
            yield rows
            if len(rows) < chunk:
                return
            cursor = (rows[-1].received_at, rows[-1].id)

    async def list_since(
        self, *, since: datetime, sender: str | None = None, limit: int = 100
    ) -> list[Message]:
        statement = select(Message).where(Message.created_at > since)
        if sender is not None:
            statement = statement.where(Message.sender == sender)
        result = await self.session.execute(
            statement.order_by(Message.created_at.asc()).limit(limit)
        )
        return list(result.scalars())

    async def count(self) -> int:
        result = await self.session.execute(select(func.count()).select_from(Message))
        return int(result.scalar_one())

    async def count_since(self, cutoff: datetime) -> int:
        result = await self.session.execute(
            select(func.count()).select_from(Message).where(Message.received_at >= cutoff)
        )
        return int(result.scalar_one())

    async def daily_counts(self, since: datetime) -> dict[str, int]:
        """Message counts keyed by ISO date.

        `date()` exists on both SQLite and PostgreSQL, so the bucketing runs in
        the database rather than pulling every row back to count them.
        """
        bucket = func.date(Message.received_at)
        result = await self.session.execute(
            select(bucket.label("day"), func.count().label("total"))
            .where(Message.received_at >= since)
            .group_by(bucket)
        )
        counts: dict[str, int] = {}
        for day, total in result.all():
            key = day.isoformat() if hasattr(day, "isoformat") else str(day)[:10]
            counts[key] = int(total)
        return counts

    async def storage_bytes(self) -> int:
        result = await self.session.execute(
            select(
                func.coalesce(func.sum(func.length(Message.body) + func.length(Message.sender)), 0)
            )
        )
        return int(result.scalar_one())

    async def delete_for_device(self, device_id: uuid.UUID) -> None:
        await self.session.execute(delete(Message).where(Message.device_id == device_id))


class EnrolmentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, token_id: uuid.UUID) -> EnrolmentToken | None:
        return await self.session.get(EnrolmentToken, token_id)

    async def get_by_hash(self, code_hash: str) -> EnrolmentToken | None:
        """Returns the token whatever state it is in; the caller reports why it
        was refused (spent, cancelled, expired)."""
        result = await self.session.execute(
            select(EnrolmentToken).where(EnrolmentToken.code_hash == code_hash)
        )
        return result.scalar_one_or_none()

    async def list_recent(self, limit: int = 50) -> list[EnrolmentToken]:
        result = await self.session.execute(
            select(EnrolmentToken).order_by(EnrolmentToken.created_at.desc()).limit(limit)
        )
        return list(result.scalars())

    async def create(
        self,
        *,
        code_hash: str,
        expires_at: datetime,
        label: str | None,
        created_by_key_id: uuid.UUID | None,
    ) -> EnrolmentToken:
        token = EnrolmentToken(
            code_hash=code_hash,
            expires_at=expires_at,
            label=label,
            created_by_key_id=created_by_key_id,
        )
        self.session.add(token)
        await self.session.flush()
        return token

    async def consume(self, token_id: uuid.UUID, device_id: uuid.UUID) -> bool:
        """Spend a token, returning False if it was already spent.

        The eligibility conditions live in the UPDATE rather than in a preceding
        SELECT, so two registrations racing on the same code cannot both win:
        exactly one UPDATE matches a row.
        """
        result = await self.session.execute(
            update(EnrolmentToken)
            .where(
                EnrolmentToken.id == token_id,
                EnrolmentToken.used_at.is_(None),
                EnrolmentToken.cancelled_at.is_(None),
                EnrolmentToken.expires_at > utcnow(),
            )
            .values(used_at=utcnow(), used_by_device_id=device_id)
            # The criteria must be evaluated by the database, not against
            # objects in the session: that is what makes this atomic, and
            # SQLite hands back naive datetimes that Python cannot compare.
            .execution_options(synchronize_session=False)
        )
        return result.rowcount == 1

    async def cancel(self, token: EnrolmentToken) -> bool:
        result = await self.session.execute(
            update(EnrolmentToken)
            .where(EnrolmentToken.id == token.id, EnrolmentToken.used_at.is_(None))
            .values(cancelled_at=utcnow())
            .execution_options(synchronize_session=False)
        )
        await self.session.flush()
        return result.rowcount == 1


class ApiKeyRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, key_id: uuid.UUID) -> ApiKey | None:
        return await self.session.get(ApiKey, key_id)

    async def get_by_hash(self, key_hash: str) -> ApiKey | None:
        result = await self.session.execute(
            select(ApiKey).where(ApiKey.key_hash == key_hash, ApiKey.revoked_at.is_(None))
        )
        return result.scalar_one_or_none()

    async def list_all(self) -> list[ApiKey]:
        result = await self.session.execute(select(ApiKey).order_by(ApiKey.created_at.desc()))
        return list(result.scalars())

    async def create(self, name: str, key_hash: str, scope: str) -> ApiKey:
        api_key = ApiKey(name=name, key_hash=key_hash, scope=scope)
        self.session.add(api_key)
        await self.session.flush()
        return api_key

    async def revoke(self, api_key: ApiKey) -> None:
        api_key.revoked_at = utcnow()
        await self.session.flush()

    async def count_active(self) -> int:
        result = await self.session.execute(
            select(func.count()).select_from(ApiKey).where(ApiKey.revoked_at.is_(None))
        )
        return int(result.scalar_one())
