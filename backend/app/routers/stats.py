from fastapi import APIRouter, Query

from app.deps import BusDep, ReaderDep, SessionDep, SettingsDep
from app.schemas import StatsResponse, VolumePoint, VolumeResponse
from app.services import MessageService

router = APIRouter(prefix="/api/v1/stats", tags=["stats"])


@router.get("", response_model=StatsResponse, summary="Deployment statistics")
async def get_stats(
    _principal: ReaderDep,
    session: SessionDep,
    bus: BusDep,
    settings: SettingsDep,
) -> StatsResponse:
    return StatsResponse(**await MessageService(session, bus, settings).stats())


@router.get(
    "/volume",
    response_model=VolumeResponse,
    summary="Daily message counts for charting",
)
async def get_volume(
    _principal: ReaderDep,
    session: SessionDep,
    bus: BusDep,
    settings: SettingsDep,
    days: int = Query(default=7, ge=1, le=90),
) -> VolumeResponse:
    points = await MessageService(session, bus, settings).volume(days)
    return VolumeResponse(days=days, points=[VolumePoint(**point) for point in points])
