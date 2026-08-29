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
