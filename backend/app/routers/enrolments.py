import uuid

from fastapi import APIRouter, status

from app.deps import AdminDep, BusDep, SessionDep, SettingsDep
from app.errors import ApiError, not_found
from app.models import utcnow
from app.repositories import EnrolmentRepository
from app.schemas import (
    EnrolmentCreatedResponse,
    EnrolmentCreateRequest,
    EnrolmentListResponse,
    EnrolmentOut,
)
from app.services import EnrolmentService

router = APIRouter(prefix="/api/v1/enrolments", tags=["enrolment"])


def _to_out(token, now) -> EnrolmentOut:
    return EnrolmentOut(
        id=token.id,
        label=token.label,
        status=token.status(now),
        created_at=token.created_at,
        expires_at=token.expires_at,
        used_at=token.used_at,
        cancelled_at=token.cancelled_at,
        used_by_device_id=token.used_by_device_id,
    )


@router.post(
    "",
    response_model=EnrolmentCreatedResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Issue a single-use enrolment code",
)
async def create_enrolment(
    payload: EnrolmentCreateRequest,
    principal: AdminDep,
    session: SessionDep,
    bus: BusDep,
    settings: SettingsDep,
) -> EnrolmentCreatedResponse:
    token, code = await EnrolmentService(session, bus, settings).issue(
        label=payload.label,
        ttl_seconds=payload.ttl_seconds,
        created_by_key_id=principal.api_key.id if principal.api_key else None,
    )
    base = _to_out(token, utcnow())
    return EnrolmentCreatedResponse(**base.model_dump(), code=code)


@router.get("", response_model=EnrolmentListResponse, summary="List recent enrolment codes")
async def list_enrolments(
    _principal: AdminDep,
    session: SessionDep,
    bus: BusDep,
    settings: SettingsDep,
) -> EnrolmentListResponse:
    now = utcnow()
    tokens = await EnrolmentService(session, bus, settings).list_recent()
    return EnrolmentListResponse(enrolments=[_to_out(token, now) for token in tokens])


@router.delete(
    "/{enrolment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Cancel an unused enrolment code",
)
async def cancel_enrolment(
    enrolment_id: uuid.UUID,
    _principal: AdminDep,
    session: SessionDep,
    bus: BusDep,
    settings: SettingsDep,
) -> None:
    token = await EnrolmentRepository(session).get(enrolment_id)
    if token is None:
        raise not_found("Enrolment code not found.")

    if not await EnrolmentService(session, bus, settings).cancel(token):
        raise ApiError(
            status.HTTP_409_CONFLICT,
            "conflict",
            "This code has already been used and cannot be cancelled. "
            "Turn off or revoke the device instead.",
        )
