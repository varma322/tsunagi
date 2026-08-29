import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Query, Response, status

from app.deps import BusDep, DeviceDep, ReaderDep, SessionDep, SettingsDep
from app.errors import ApiError
from app.schemas import (
    MessageBatchCreate,
    MessageBatchResponse,
    MessageCreate,
    MessageListResponse,
    MessageOut,
    MessageResult,
    MessageWaitResponse,
)
from app.services import MessageService

router = APIRouter(prefix="/api/v1/messages", tags=["messages"])


@router.post(
    "",
    response_model=MessageOut,
    status_code=status.HTTP_201_CREATED,
    summary="Upload a message (idempotent by client-generated id)",
)
async def upload_message(
    payload: MessageCreate,
    device: DeviceDep,
    response: Response,
    session: SessionDep,
    bus: BusDep,
    settings: SettingsDep,
) -> MessageOut:
    message, created = await MessageService(session, bus, settings).ingest(device, payload)
    if not created:
        response.status_code = status.HTTP_200_OK
    return MessageOut.model_validate(message)


@router.post(
    "/batch",
    response_model=MessageBatchResponse,
    summary="Upload a batch of messages",
)
async def upload_batch(
    payload: MessageBatchCreate,
    device: DeviceDep,
    session: SessionDep,
    bus: BusDep,
    settings: SettingsDep,
) -> MessageBatchResponse:
    """Upload a batch, either whole or message by message.

    By default one unacceptable message rejects the request, as it always has.
    A client that sets `partial` gets the acceptable ones stored and a verdict
    per message, which is what lets it quarantine the offender without having
    to find it by re-uploading the batch one message at a time.
    """
    service = MessageService(session, bus, settings)
    accepted = len(payload.messages)
    valid, rejected = service.parse_batch(payload.messages)

    if rejected and not payload.partial:
        # The caller has not promised to read per-message results, so telling
        # it "200, mostly" would invite it to drop the message named below.
        raise ApiError(422, "validation_error", rejected[0].error or "Invalid message.")

    created, duplicates, created_flags = await service.ingest_batch(
        device, [message for _, message in valid]
    )

    if not payload.partial:
        return MessageBatchResponse(accepted=accepted, created=created, duplicates=duplicates)

    results = rejected + [
        MessageResult(
            index=index,
            id=message.id,
            status="created" if was_created else "duplicate",
        )
        for (index, message), was_created in zip(valid, created_flags, strict=True)
    ]
    results.sort(key=lambda result: result.index)

    return MessageBatchResponse(
        accepted=accepted,
        created=created,
        duplicates=duplicates,
        rejected=len(rejected),
        results=results,
    )


@router.get("", response_model=MessageListResponse, summary="List messages")
async def list_messages(
    _principal: ReaderDep,
    session: SessionDep,
    bus: BusDep,
    settings: SettingsDep,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    sender: str | None = None,
    device_id: uuid.UUID | None = None,
    after: datetime | None = None,
    before: datetime | None = None,
) -> MessageListResponse:
    total, messages = await MessageService(session, bus, settings).list(
        limit=limit,
        offset=offset,
        sender=sender,
        device_id=device_id,
        after=after,
        before=before,
    )
    return MessageListResponse(
        total=total,
        limit=limit,
        offset=offset,
        messages=[MessageOut.model_validate(message) for message in messages],
    )


@router.get("/search", response_model=MessageListResponse, summary="Full-text search messages")
async def search_messages(
    _principal: ReaderDep,
    session: SessionDep,
    bus: BusDep,
    settings: SettingsDep,
    query: str = Query(min_length=1),
    sender: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> MessageListResponse:
    total, messages = await MessageService(session, bus, settings).list(
        limit=limit, offset=offset, sender=sender, query=query
    )
    return MessageListResponse(
        total=total,
        limit=limit,
        offset=offset,
        messages=[MessageOut.model_validate(message) for message in messages],
    )


@router.get(
    "/wait",
    response_model=MessageWaitResponse,
    summary="Long-poll for newly stored messages",
)
async def wait_for_messages(
    _principal: ReaderDep,
    session: SessionDep,
    bus: BusDep,
    settings: SettingsDep,
    since: datetime | None = None,
    timeout: int = Query(default=30, ge=1),
    sender: str | None = None,
) -> MessageWaitResponse:
    # `since` compares against server storage time, which is monotonic for a
    # poller; a device's own received_at can arrive out of order after a
    # backlog upload.
    cursor = since or datetime.now(UTC)
    if cursor.tzinfo is None:
        cursor = cursor.replace(tzinfo=UTC)
    messages = await MessageService(session, bus, settings).wait_for_new(
        since=cursor,
        timeout=min(timeout, settings.max_wait_timeout_seconds),
        sender=sender,
    )
    return MessageWaitResponse(messages=[MessageOut.model_validate(m) for m in messages])
