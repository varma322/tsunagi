from fastapi import APIRouter

from app.deps import PrincipalDep
from app.schemas import MeResponse

router = APIRouter(prefix="/api/v1/me", tags=["identity"])


@router.get("", response_model=MeResponse, summary="Describe the calling credential")
async def whoami(principal: PrincipalDep) -> MeResponse:
    if principal.api_key is not None:
        return MeResponse(
            kind="key",
            scope=principal.scope,
            name=principal.api_key.name,
            id=principal.api_key.id,
        )
    if principal.device is not None:
        return MeResponse(
            kind="device",
            scope=principal.scope,
            name=principal.device.name,
            id=principal.device.id,
        )
    return MeResponse(kind=principal.kind, scope=principal.scope)
