import uuid
from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, Text, Uuid
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(UTC)


def _aware(value: datetime) -> datetime:
    """SQLite drops tzinfo on round-trip; everything is stored as UTC."""
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


class Base(DeclarativeBase):
    pass


class Device(Base):
    """A registered Android device that uploads messages."""

    __tablename__ = "devices"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    # Raw device tokens are never stored, only their SHA-256 digest.
    token_hash: Mapped[str] = mapped_column(String(128), nullable=False, unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    last_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Reversible suspension, toggled by an admin. Distinct from revoked_at,
    # which is permanent.
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # --- capture health ---------------------------------------------------
    # What the phone reports about its own ability to receive SMS, as opposed
    # to its ability to reach the server. last_seen proves only the latter, so
    # without these a phone whose SMS permission was revoked looks exactly like
    # one that simply has not been texted.
    #
    # All null until a device new enough to report them checks in, which is why
    # they are nullable rather than defaulted: "not reporting" and "reporting a
    # problem" are different answers and must not collapse into one.
    capture_reported_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    capture_permitted: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    inbox_readable: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    battery_exempt: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    #: Newest message the device holds, however it was captured.
    last_captured_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    #: When the inbox sweep last completed, whether or not it found anything.
    last_swept_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    @property
    def is_active(self) -> bool:
        return self.disabled_at is None and self.revoked_at is None

    messages: Mapped[list["Message"]] = relationship(
        back_populates="device", cascade="all, delete-orphan"
    )

    __table_args__ = (Index("idx_devices_last_seen", last_seen.desc()),)


class Message(Base):
    """A synchronized SMS. The primary key is generated on the device, which is
    what makes re-uploading after a lost response idempotent."""

    __tablename__ = "messages"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    device_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("devices.id", ondelete="CASCADE"), nullable=False
    )
    sender: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )

    device: Mapped[Device] = relationship(back_populates="messages")

    __table_args__ = (
        Index("idx_messages_received_at", received_at.desc()),
        Index("idx_messages_device_received", device_id, received_at.desc()),
        Index("idx_messages_sender", sender),
    )


class EnrolmentToken(Base):
    """A single-use code that authorizes exactly one device registration.

    Replaces the shared setup key: a leaked code is worth one device for a few
    minutes rather than unlimited devices forever, and every enrolment is
    attributable to the admin who issued it.
    """

    __tablename__ = "enrolment_tokens"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code_hash: Mapped[str] = mapped_column(String(128), nullable=False, unique=True, index=True)
    label: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Audit trail: who issued it, and which device it produced.
    created_by_key_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("api_keys.id", ondelete="SET NULL"), nullable=True
    )
    used_by_device_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("devices.id", ondelete="SET NULL"), nullable=True
    )

    def status(self, now: datetime) -> str:
        if self.used_at is not None:
            return "used"
        if self.cancelled_at is not None:
            return "cancelled"
        if _aware(self.expires_at) <= _aware(now):
            return "expired"
        return "pending"


class ApiKey(Base):
    """Credential for dashboard users and third-party integrations."""

    __tablename__ = "api_keys"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    key_hash: Mapped[str] = mapped_column(String(128), nullable=False, unique=True, index=True)
    scope: Mapped[str] = mapped_column(String(16), nullable=False, default="user")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    # Soft delete: revoked keys stay queryable so usage history remains auditable.
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
