import uuid
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field


def _ensure_utc(value: Any) -> Any:
    if isinstance(value, datetime) and value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


UtcDatetime = Annotated[datetime, BeforeValidator(_ensure_utc)]

Scope = Literal["user", "admin"]


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


class DeviceListResponse(BaseModel):
    devices: list[DeviceOut]


class DeviceEnabledRequest(BaseModel):
    enabled: bool


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
    messages: list[MessageCreate] = Field(min_length=1, max_length=500)


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


class MessageBatchResponse(BaseModel):
    accepted: int
    created: int
    duplicates: int


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
