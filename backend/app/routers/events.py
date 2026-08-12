from fastapi import APIRouter, Query

from app.deps import AdminDep, BusDep
from app.schemas import EventListResponse, EventOut

router = APIRouter(prefix="/api/v1/events", tags=["events"])


@router.get("", response_model=EventListResponse, summary="Recent system events")
async def list_events(
    # Admin-only: events name devices and keys, and record failed auth attempts.
    _principal: AdminDep,
    bus: BusDep,
    limit: int = Query(default=100, ge=1, le=1000),
    level: str | None = Query(default=None, pattern="^(info|warn|error)$"),
    type: str | None = None,
) -> EventListResponse:
    events = await bus.recent(limit=limit, level=level, type_=type)
    return EventListResponse(
        events=[
            EventOut(
                timestamp=event.timestamp,
                type=event.type,
                level=event.level,
                payload=event.payload,
            )
            for event in events
        ]
    )
