import uuid
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, field_validator


def _ensure_utc(value: Any) -> Any:
    if isinstance(value, datetime) and value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


UtcDatetime = Annotated[datetime, BeforeValidator(_ensure_utc)]

Scope = Literal["user", "admin"]

#: Whether a device can still receive SMS, as distinct from whether it can
#: reach the server. "unknown" means the device has never reported — an app
#: older than this field, not a device in trouble.
CaptureStatus = Literal["unknown", "ok", "blocked"]


# --- errors ---------------------------------------------------------------


class ErrorDetail(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    error: ErrorDetail


# --- devices --------------------------------------------------------------


class DeviceRegisterRequest(BaseModel):
    device_name: str = Field(min_length=1, max_length=120)


class DeviceRegisterResponse(BaseModel):
    device_id: uuid.UUID
    token: str


class DeviceCheckInRequest(BaseModel):
    """What a phone reports about its own ability to capture SMS.

    Sent on every sync pass. The server cannot derive any of this: from here a
    phone that has been denied SMS permission and a phone nobody has texted
    look the same.
    """

    #: RECEIVE_SMS and READ_SMS are both still granted.
    capture_permitted: bool
    #: The last sweep could read the platform SMS store. False means the sweep
    #: ran and was refused, which is a broken safety net rather than a quiet one.
    inbox_readable: bool
    #: Exempt from battery optimization. Not required, but an optimized app can
    #: be parked in the stopped state, where no SMS broadcast is delivered.
    battery_exempt: bool
    last_captured_at: UtcDatetime | None = None
    last_swept_at: UtcDatetime | None = None


class DeviceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    #: Seen recently enough to count as online. Always false when disabled.
    status: bool
    #: False when an admin has switched this device off.
    enabled: bool
    last_seen: UtcDatetime | None
    created_at: UtcDatetime
    disabled_at: UtcDatetime | None = None

    #: Derived from the fields below: can this device still capture SMS?
    capture: CaptureStatus = "unknown"
    capture_reported_at: UtcDatetime | None = None
    capture_permitted: bool | None = None
    inbox_readable: bool | None = None
    battery_exempt: bool | None = None
    #: Newest message the device holds. An "ok" device with an old timestamp
    #: here is quiet; that is the distinction this endpoint exists to make.
    last_captured_at: UtcDatetime | None = None
    last_swept_at: UtcDatetime | None = None


class DeviceListResponse(BaseModel):
    devices: list[DeviceOut]


class DeviceEnabledRequest(BaseModel):
    enabled: bool


class MessagesClearedResponse(BaseModel):
    """How many messages were deleted.

    Reported because the operator has no other way to check: once the call
    returns there is nothing left to count.
    """

    deleted: int


# --- enrolment ------------------------------------------------------------


class EnrolmentCreateRequest(BaseModel):
    label: str | None = Field(default=None, max_length=120)
    #: Overrides TSUNAGI_ENROLMENT_TOKEN_TTL_SECONDS for this code.
    ttl_seconds: int | None = Field(default=None, ge=60, le=86_400)


class EnrolmentOut(BaseModel):
    id: uuid.UUID
    label: str | None
    #: pending | used | expired | cancelled
    status: str
    created_at: UtcDatetime
    expires_at: UtcDatetime
    used_at: UtcDatetime | None
    cancelled_at: UtcDatetime | None
    used_by_device_id: uuid.UUID | None


class EnrolmentCreatedResponse(EnrolmentOut):
    # Returned exactly once, at creation time.
    code: str


class EnrolmentListResponse(BaseModel):
    enrolments: list[EnrolmentOut]


# --- identity -------------------------------------------------------------


class MeResponse(BaseModel):
    """What the caller's credential is allowed to do.

    The dashboard reads this once at sign-in so it can hide actions the key
    cannot perform, instead of surfacing a 403 after the click.
    """

    kind: str
    scope: str
    name: str | None = None
    id: uuid.UUID | None = None


# --- messages -------------------------------------------------------------


class MessageCreate(BaseModel):
    id: uuid.UUID
    sender: str = Field(min_length=1)
    body: str
    received_at: UtcDatetime


class MessageBatchCreate(BaseModel):
    """A batch upload.

    `messages` is untyped here and validated one message at a time, which is
    what lets a single unacceptable message be named instead of rejecting the
    batch it arrived in. With `partial` false — the default — the outcome is
    unchanged: the first invalid message rejects the whole request with the
    same 422.
    """

    messages: list[Any] = Field(min_length=1, max_length=500)
    #: Accept what is valid and report the rest, rather than refusing the batch.
    #:
    #: Off by default, and it has to be. A client that does not read the
    #: per-message results would take 200 to mean everything was stored and
    #: drop the one message the server refused — which is the failure this
    #: whole project is built to avoid. Opting in is a promise to read them.
    partial: bool = False


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    device_id: uuid.UUID
    sender: str
    body: str
    received_at: UtcDatetime
    created_at: UtcDatetime


class MessageListResponse(BaseModel):
    total: int
    limit: int
    offset: int
    messages: list[MessageOut]


class MessageWaitResponse(BaseModel):
    messages: list[MessageOut]


#: What became of one message in a batch.
MessageStatus = Literal["created", "duplicate", "rejected"]


class MessageResult(BaseModel):
    """The fate of a single message, by its position in the request."""

    index: int
    #: Absent when the id itself was unreadable.
    id: uuid.UUID | None = None
    status: MessageStatus
    #: Why it was refused, worded as the whole-batch rejection would have been.
    error: str | None = None


class MessageBatchResponse(BaseModel):
    accepted: int
    created: int
    duplicates: int
    #: Always 0 unless the request opted in to partial acceptance.
    rejected: int = 0
    #: Present only for a partial request. Null means every message was stored
    #: or already present — the same guarantee a 200 carried before.
    results: list[MessageResult] | None = None


# --- webhooks -------------------------------------------------------------


#: What a webhook can subscribe to. Short on purpose: the bus also carries
#: per-pass sync chatter and the internal event log, neither of which is worth
#: waking somebody's server for.
WebhookEvent = Literal["message.new", "device.status"]


class WebhookCreateRequest(BaseModel):
    url: str = Field(min_length=8, max_length=2048)
    description: str | None = Field(default=None, max_length=120)
    events: list[WebhookEvent] = Field(default=["message.new"], min_length=1)

    @field_validator("url")
    @classmethod
    def _must_be_http(cls, value: str) -> str:
        # Only the scheme is checked. Which hosts are reachable is the
        # operator's business on a server they run themselves, and refusing
        # loopback would break the most common integration there is: a script
        # on the same box.
        if not value.startswith(("http://", "https://")):
            raise ValueError("must be an http:// or https:// URL")
        return value


class WebhookOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    url: str
    description: str | None
    events: list[str]
    enabled: bool
    created_at: UtcDatetime
    disabled_at: UtcDatetime | None = None
    last_delivery_at: UtcDatetime | None = None
    last_status: int | None = None
    last_error: str | None = None
    #: Consecutive failures. Non-zero on an enabled webhook means it is failing
    #: now, not that it once did.
    failure_count: int = 0


class CreatedWebhook(WebhookOut):
    """Includes the signing secret, which is shown once and never again."""

    secret: str


class WebhookListResponse(BaseModel):
    webhooks: list[WebhookOut]


class WebhookEnabledRequest(BaseModel):
    enabled: bool


class WebhookTestResponse(BaseModel):
    """The result of a delivery the operator asked for, sent there and then."""

    delivered: bool
    status: int | None = None
    error: str | None = None


# --- api keys -------------------------------------------------------------


class ApiKeyCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    scope: Scope = "user"


class ApiKeyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    scope: str
    created_at: UtcDatetime
    revoked_at: UtcDatetime | None


class ApiKeyCreatedResponse(ApiKeyOut):
    # Returned exactly once, at creation time.
    key: str


class ApiKeyListResponse(BaseModel):
    keys: list[ApiKeyOut]


# --- events & stats -------------------------------------------------------


class EventOut(BaseModel):
    timestamp: UtcDatetime
    type: str
    level: str
    payload: dict[str, Any]


class EventListResponse(BaseModel):
    events: list[EventOut]


class AuditEventOut(BaseModel):
    """One durable audit record. Unlike a live event it carries an id and is
    read back from storage, so it has a stable identity and a real timestamp."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    type: str
    level: str
    payload: dict[str, Any]
    created_at: UtcDatetime


class AuditListResponse(BaseModel):
    total: int
    limit: int
    offset: int
    events: list[AuditEventOut]


class StatsResponse(BaseModel):
    messages_total: int
    messages_today: int
    active_devices: int
    storage_bytes: int


class VolumePoint(BaseModel):
    date: str
    count: int


class VolumeResponse(BaseModel):
    days: int
    points: list[VolumePoint]
