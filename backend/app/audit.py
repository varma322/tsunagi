"""Durable persistence of noteworthy events.

The event bus keeps a capped, transient log for the live dashboard; this module
mirrors the events worth auditing into PostgreSQL, where they are append-only
and survive a restart. It is wired onto the bus as a sink so the bus itself
stays free of storage concerns.
"""

from __future__ import annotations

import json
import logging

from app.db import get_session_factory
from app.events import Event
from app.repositories import AuditRepository

logger = logging.getLogger("tsunagi.audit")

#: Event types deliberately not persisted. Both are high-frequency traffic that
#: the messages table already records, and auditing them would bury the security
#: and administrative events this trail exists for.
AUDIT_SKIP = frozenset({"MSG_RECV", "SYNC_OK"})


async def persist_event(event: Event) -> None:
    """Write one event to the durable audit trail, unless it is skipped.

    Best-effort by design: the business action that produced the event has
    already committed by the time it is emitted, so a failure to audit is logged
    rather than propagated -- an audit-write error must not undo a device
    registration. The failure is loud in the logs so it is not silent.
    """
    if event.type in AUDIT_SKIP:
        return
    try:
        async with get_session_factory()() as session:
            await AuditRepository(session).record(
                type_=event.type,
                level=event.level,
                payload=json.dumps(event.payload, separators=(",", ":")),
                created_at=event.timestamp,
            )
            await session.commit()
    except Exception:  # noqa: BLE001 - an audit failure must not break the request
        logger.exception("failed to persist audit event %s", event.type)
