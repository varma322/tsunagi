import json
import uuid
from datetime import datetime

from fastapi import APIRouter, Query

from app.deps import AdminDep, SessionDep
from app.repositories import AuditRepository
from app.schemas import AuditEventOut, AuditListResponse

router = APIRouter(prefix="/api/v1/audit", tags=["audit"])


@router.get("", response_model=AuditListResponse, summary="Durable audit trail")
async def list_audit_events(
    # Admin-only: the trail names devices and keys and records administrative
    # actions, the same reason the live event feed is admin-only.
    _principal: AdminDep,
    session: SessionDep,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    level: str | None = Query(default=None, pattern="^(info|warn|error)$"),
    type: str | None = None,
    after: datetime | None = None,
    before: datetime | None = None,
) -> AuditListResponse:
    """Noteworthy events as they were persisted, newest first.

    Unlike ``GET /events``, which serves the capped in-memory log the dashboard
    streams, this reads the durable table: it survives a restart, is not capped,
    and paginates so a long history can be walked.
    """
    total, events = await AuditRepository(session).list(
        limit=limit, offset=offset, level=level, type_=type, after=after, before=before
    )
    return AuditListResponse(
        total=total,
        limit=limit,
        offset=offset,
        events=[
            AuditEventOut(
                id=event.id,
                type=event.type,
                level=event.level,
                payload=_decode(event.payload),
                created_at=event.created_at,
            )
            for event in events
        ],
    )


def _decode(payload: str) -> dict:
    try:
        value = json.loads(payload)
        return value if isinstance(value, dict) else {"value": value}
    except (ValueError, TypeError):
        return {}
