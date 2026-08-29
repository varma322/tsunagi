import uuid

from fastapi import APIRouter, Request, status

from app.deps import AdminDep, SessionDep
from app.errors import not_found
from app.repositories import WebhookRepository
from app.schemas import (
    CreatedWebhook,
    WebhookCreateRequest,
    WebhookEnabledRequest,
    WebhookListResponse,
    WebhookOut,
    WebhookTestResponse,
)
from app.webhooks import Delivery, deliver, generate_secret, send_over_http

router = APIRouter(prefix="/api/v1/webhooks", tags=["webhooks"])


def _out(webhook) -> WebhookOut:
    return WebhookOut(
        id=webhook.id,
        url=webhook.url,
        description=webhook.description,
        events=webhook.event_names,
        enabled=webhook.is_active,
        created_at=webhook.created_at,
        disabled_at=webhook.disabled_at,
        last_delivery_at=webhook.last_delivery_at,
        last_status=webhook.last_status,
        last_error=webhook.last_error,
        failure_count=webhook.failure_count,
    )


@router.post(
    "",
    response_model=CreatedWebhook,
    status_code=status.HTTP_201_CREATED,
    summary="Register a webhook endpoint",
)
async def create_webhook(
    payload: WebhookCreateRequest,
    _principal: AdminDep,
    session: SessionDep,
) -> CreatedWebhook:
    """Admin scope. The signing secret comes back once, here, and never again.

    Unlike an API key the secret is stored as issued rather than hashed — it is
    not a credential presented to us, it is one we sign outgoing deliveries
    with, so it has to remain recoverable by the server.
    """
    secret = generate_secret()
    webhook = await WebhookRepository(session).create(
        url=payload.url,
        secret=secret,
        events=list(payload.events),
        description=payload.description,
    )
    await session.commit()
    return CreatedWebhook(**_out(webhook).model_dump(), secret=secret)


@router.get("", response_model=WebhookListResponse, summary="List webhooks")
async def list_webhooks(_principal: AdminDep, session: SessionDep) -> WebhookListResponse:
    webhooks = await WebhookRepository(session).list_all()
    return WebhookListResponse(webhooks=[_out(webhook) for webhook in webhooks])


@router.post(
    "/{webhook_id}/enabled",
    response_model=WebhookOut,
    summary="Turn a webhook on or off",
)
async def set_webhook_enabled(
    webhook_id: uuid.UUID,
    payload: WebhookEnabledRequest,
    _principal: AdminDep,
    session: SessionDep,
) -> WebhookOut:
    repository = WebhookRepository(session)
    webhook = await repository.get(webhook_id)
    if webhook is None:
        raise not_found("Webhook not found.")
    await repository.set_enabled(webhook, payload.enabled)
    await session.commit()
    return _out(webhook)


@router.post(
    "/{webhook_id}/test",
    response_model=WebhookTestResponse,
    summary="Send a test delivery now",
)
async def test_webhook(
    webhook_id: uuid.UUID,
    request: Request,
    _principal: AdminDep,
    session: SessionDep,
) -> WebhookTestResponse:
    """Sends a signed delivery immediately and reports what happened.

    Inline rather than queued, and that is the point: an operator asking
    "does my endpoint work" wants the answer in the response, not in a log
    they have to go and read.
    """
    repository = WebhookRepository(session)
    webhook = await repository.get(webhook_id)
    if webhook is None:
        raise not_found("Webhook not found.")

    dispatcher = getattr(request.app.state, "webhooks", None)
    transport = dispatcher.transport if dispatcher is not None else send_over_http

    result = await deliver(
        Delivery(
            webhook_id=webhook.id,
            url=webhook.url,
            secret=webhook.secret,
            event="webhook.test",
            data={"webhook_id": str(webhook.id), "message": "Tsunagi test delivery"},
        ),
        transport=transport,
        # One attempt: a test is a question about the endpoint's current state,
        # and retrying would report the answer to a different question.
        attempts=1,
    )

    await repository.record_attempt(
        webhook,
        ok=result.ok,
        status=result.status,
        error=result.error,
        # A test must never be the thing that switches a webhook off.
        failure_limit=10**9,
    )
    await session.commit()

    return WebhookTestResponse(delivered=result.ok, status=result.status, error=result.error)


@router.delete(
    "/{webhook_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a webhook",
)
async def delete_webhook(
    webhook_id: uuid.UUID,
    _principal: AdminDep,
    session: SessionDep,
) -> None:
    repository = WebhookRepository(session)
    webhook = await repository.get(webhook_id)
    if webhook is None:
        raise not_found("Webhook not found.")
    await repository.delete(webhook)
    await session.commit()
