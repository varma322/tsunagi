"""Authentication and shared FastAPI dependencies.

Device tokens and API keys travel in the same `Authorization: Bearer` header
and are told apart by their prefix, then matched against a stored SHA-256
digest.
"""

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db import get_session
from app.errors import ApiError, forbidden, unauthorized
from app.events import EventBus
from app.models import ApiKey, Device, EnrolmentToken, utcnow
from app.repositories import ApiKeyRepository, DeviceRepository, EnrolmentRepository
from app.security import (
    API_KEY_PREFIX,
    DEVICE_TOKEN_PREFIX,
    hash_secret,
    looks_like_enrolment_code,
    normalize_enrolment_code,
    secrets_match,
)

SessionDep = Annotated[AsyncSession, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


def get_bus(request: Request) -> EventBus:
    return request.app.state.bus


BusDep = Annotated[EventBus, Depends(get_bus)]


@dataclass(slots=True)
class Principal:
    kind: str  # "device" | "key" | "setup" | "enrolment"
    scope: str  # "device" | "user" | "admin"
    device: Device | None = None
    api_key: ApiKey | None = None
    #: Present only for kind == "enrolment". Validated here, spent by the
    #: register endpoint, so a failed registration does not burn the code.
    enrolment: EnrolmentToken | None = None

    @property
    def is_admin(self) -> bool:
        return self.scope == "admin"

    @property
    def can_read(self) -> bool:
        return self.scope in {"user", "admin"}


def bearer_token(request: Request) -> str | None:
    header = request.headers.get("authorization")
    if header:
        scheme, _, value = header.partition(" ")
        if scheme.lower() == "bearer" and value.strip():
            return value.strip()
    # Browsers cannot set headers on a WebSocket handshake.
    query_token = request.query_params.get("token")
    return query_token.strip() if query_token else None


async def resolve_principal(
    token: str | None, session: AsyncSession, settings: Settings
) -> Principal | None:
    """Map a raw credential to a principal, or None when it matches nothing."""
    if not token:
        return None

    if settings.setup_key and secrets_match(token, settings.setup_key):
        return Principal(kind="setup", scope="device")

    digest = hash_secret(token)

    if token.startswith(DEVICE_TOKEN_PREFIX):
        device = await DeviceRepository(session).get_by_token_hash(digest)
        if device is None:
            return None
        if not device.is_active:
            # Deliberately 403, not 401. The Android client treats 401 as "this
            # token is stale" and re-enrols with its stored setup key, which
            # would let a switched-off phone walk straight back in under a new
            # id. 403 is terminal on the client.
            raise ApiError(
                status.HTTP_403_FORBIDDEN,
                "device_revoked" if device.revoked_at else "device_disabled",
                "This device has been turned off by an administrator."
                if device.disabled_at
                else "This device has been revoked.",
            )
        return Principal(kind="device", scope="device", device=device)

    if token.startswith(API_KEY_PREFIX):
        api_key = await ApiKeyRepository(session).get_by_hash(digest)
        if api_key is None:
            return None
        return Principal(kind="key", scope=api_key.scope, api_key=api_key)

    if looks_like_enrolment_code(token):
        enrolment = await EnrolmentRepository(session).get_by_hash(
            hash_secret(normalize_enrolment_code(token))
        )
        if enrolment is None:
            return None
        state = enrolment.status(utcnow())
        if state != "pending":
            # Say which it is: "already used" and "expired" lead the admin to
            # different fixes, and neither reveals anything an attacker holding
            # the code does not already know.
            raise ApiError(
                status.HTTP_403_FORBIDDEN,
                f"enrolment_{state}",
                f"This enrolment code has already been {state}."
                if state != "expired"
                else "This enrolment code has expired.",
            )
        return Principal(kind="enrolment", scope="device", enrolment=enrolment)

    return None


async def current_principal(
    request: Request, session: SessionDep, settings: SettingsDep
) -> Principal:
    principal = await resolve_principal(bearer_token(request), session, settings)
    if principal is None:
        raise unauthorized()
    if principal.device is not None:
        # Every authenticated device call refreshes presence for the dashboard.
        await DeviceRepository(session).touch(principal.device)
        await session.commit()
    return principal


PrincipalDep = Annotated[Principal, Depends(current_principal)]


async def require_device(principal: PrincipalDep) -> Device:
    if principal.device is None:
        raise forbidden("This endpoint requires a device token.")
    return principal.device


async def require_reader(principal: PrincipalDep) -> Principal:
    if not principal.can_read:
        raise forbidden("This endpoint requires an API key with user or admin scope.")
    return principal


async def require_admin(principal: PrincipalDep) -> Principal:
    if not principal.is_admin:
        raise forbidden("This endpoint requires an API key with admin scope.")
    return principal


async def require_registration_credentials(principal: PrincipalDep) -> Principal:
    """Registration accepts a single-use enrolment code, an admin API key, or
    the legacy shared setup key when one is configured."""
    if principal.kind in {"enrolment", "setup"} or principal.is_admin:
        return principal
    raise forbidden(
        "Device registration requires a single-use enrolment code or an admin API key."
    )


DeviceDep = Annotated[Device, Depends(require_device)]
ReaderDep = Annotated[Principal, Depends(require_reader)]
AdminDep = Annotated[Principal, Depends(require_admin)]
RegistrationDep = Annotated[Principal, Depends(require_registration_credentials)]
