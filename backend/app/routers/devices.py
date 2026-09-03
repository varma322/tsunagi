import uuid

from fastapi import APIRouter, status

from app.deps import (
    AdminDep,
    BusDep,
    DeviceDep,
    ReaderDep,
    RegistrationDep,
    SessionDep,
    SettingsDep,
)
from app.errors import not_found
from app.repositories import DeviceRepository
from app.schemas import (
    DeviceCheckInRequest,
    DeviceEnabledRequest,
    DeviceListResponse,
    DeviceOut,
    DeviceRegisterRequest,
    DeviceRegisterResponse,
    MessagesClearedResponse,
)
from app.services import DeviceService

router = APIRouter(prefix="/api/v1/devices", tags=["devices"])


@router.post(
    "/register",
    response_model=DeviceRegisterResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a device and issue its token",
)
async def register_device(
    payload: DeviceRegisterRequest,
    principal: RegistrationDep,
    session: SessionDep,
    bus: BusDep,
    settings: SettingsDep,
) -> DeviceRegisterResponse:
    device, token = await DeviceService(session, bus, settings).register(
        payload.device_name, enrolment=principal.enrolment
    )
    return DeviceRegisterResponse(device_id=device.id, token=token)


@router.get("", response_model=DeviceListResponse, summary="List registered devices")
async def list_devices(
    _principal: ReaderDep,
    session: SessionDep,
    bus: BusDep,
    settings: SettingsDep,
) -> DeviceListResponse:
    service = DeviceService(session, bus, settings)
    devices = await service.list_devices()
    return DeviceListResponse(devices=[service.to_out(device) for device in devices])


@router.post(
    "/checkin",
    response_model=DeviceOut,
    summary="Report this device's capture health",
)
async def check_in(
    payload: DeviceCheckInRequest,
    device: DeviceDep,
    session: SessionDep,
    bus: BusDep,
    settings: SettingsDep,
) -> DeviceOut:
    """Called by the phone on every sync pass, with or without messages.

    The presence half of this is free — any authenticated device call refreshes
    last_seen. The body is the part the server cannot work out for itself:
    whether the phone can still be handed an SMS at all.
    """
    service = DeviceService(session, bus, settings)
    await service.record_check_in(device, payload)
    return service.to_out(device)


@router.post(
    "/{device_id}/enabled",
    response_model=DeviceOut,
    summary="Turn a device on or off (reversible)",
)
async def set_device_enabled(
    device_id: uuid.UUID,
    payload: DeviceEnabledRequest,
    _principal: AdminDep,
    session: SessionDep,
    bus: BusDep,
    settings: SettingsDep,
) -> DeviceOut:
    device = await DeviceRepository(session).get(device_id)
    if device is None or device.revoked_at is not None:
        raise not_found("Device not found.")

    service = DeviceService(session, bus, settings)
    await service.set_enabled(device, payload.enabled)

    return service.to_out(device)


@router.delete(
    "/{device_id}/messages",
    response_model=MessagesClearedResponse,
    summary="Permanently delete this device's messages",
)
async def clear_device_messages(
    device_id: uuid.UUID,
    _principal: AdminDep,
    session: SessionDep,
    bus: BusDep,
    settings: SettingsDep,
) -> MessagesClearedResponse:
    """Delete every message uploaded by one device. **Not reversible.**

    Accepts a revoked device, unlike the other device endpoints: clearing a
    retired phone's messages is the ordinary reason to call this.

    Note that this empties the table, not the deployment. Database dumps taken
    before now -- including the one deployment/update.sh writes before every
    migration -- still contain these messages.
    """
    device = await DeviceRepository(session).get(device_id)
    if device is None:
        raise not_found("Device not found.")
    deleted = await DeviceService(session, bus, settings).clear_messages(device)
    return MessagesClearedResponse(deleted=deleted)


@router.delete(
    "/{device_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Revoke a device token",
)
async def revoke_device(
    device_id: uuid.UUID,
    _principal: AdminDep,
    session: SessionDep,
    bus: BusDep,
    settings: SettingsDep,
) -> None:
    device = await DeviceRepository(session).get(device_id)
    if device is None or device.revoked_at is not None:
        raise not_found("Device not found.")
    await DeviceService(session, bus, settings).revoke(device)
