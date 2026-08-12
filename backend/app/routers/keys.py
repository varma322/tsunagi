import uuid

from fastapi import APIRouter, status

from app.deps import AdminDep, BusDep, SessionDep
from app.errors import not_found
from app.repositories import ApiKeyRepository
from app.schemas import (
    ApiKeyCreatedResponse,
    ApiKeyCreateRequest,
    ApiKeyListResponse,
    ApiKeyOut,
)
from app.services import ApiKeyService

router = APIRouter(prefix="/api/v1/keys", tags=["api-keys"])


@router.post(
    "",
    response_model=ApiKeyCreatedResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create an API key (returned in full exactly once)",
)
async def create_key(
    payload: ApiKeyCreateRequest,
    _principal: AdminDep,
    session: SessionDep,
    bus: BusDep,
) -> ApiKeyCreatedResponse:
    api_key, raw = await ApiKeyService(session, bus).create(payload.name, payload.scope)
    return ApiKeyCreatedResponse(
        id=api_key.id,
        name=api_key.name,
        scope=api_key.scope,
        created_at=api_key.created_at,
        revoked_at=api_key.revoked_at,
        key=raw,
    )


@router.get("", response_model=ApiKeyListResponse, summary="List API keys")
async def list_keys(
    _principal: AdminDep,
    session: SessionDep,
    bus: BusDep,
) -> ApiKeyListResponse:
    keys = await ApiKeyService(session, bus).list_keys()
    return ApiKeyListResponse(keys=[ApiKeyOut.model_validate(key) for key in keys])


@router.delete(
    "/{key_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Revoke an API key",
)
async def revoke_key(
    key_id: uuid.UUID,
    _principal: AdminDep,
    session: SessionDep,
    bus: BusDep,
) -> None:
    api_key = await ApiKeyRepository(session).get(key_id)
    if api_key is None or api_key.revoked_at is not None:
        raise not_found("API key not found.")
    await ApiKeyService(session, bus).revoke(api_key)
