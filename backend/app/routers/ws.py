import asyncio
import contextlib
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.config import get_settings
from app.db import get_session_factory
from app.deps import resolve_principal
from app.errors import ApiError

logger = logging.getLogger(__name__)

router = APIRouter(tags=["websocket"])

POLICY_VIOLATION = 1008


def _websocket_token(websocket: WebSocket) -> str | None:
    header = websocket.headers.get("authorization")
    if header:
        scheme, _, value = header.partition(" ")
        if scheme.lower() == "bearer" and value.strip():
            return value.strip()
    token = websocket.query_params.get("token")
    return token.strip() if token else None


@router.websocket("/ws/messages")
async def messages_socket(websocket: WebSocket) -> None:
    settings = get_settings()
    try:
        async with get_session_factory()() as session:
            principal = await resolve_principal(_websocket_token(websocket), session, settings)
    except ApiError:
        # A disabled or revoked device: same outcome as any other rejected
        # credential, since a socket has no response body to explain itself.
        principal = None

    if principal is None or not principal.can_read:
        await websocket.close(code=POLICY_VIOLATION)
        return

    await websocket.accept()
    bus = websocket.app.state.bus

    async with bus.subscribe() as queue:

        async def pump_events() -> None:
            while True:
                frame = await queue.get()
                await websocket.send_json(frame)

        async def pump_client() -> None:
            while True:
                message = await websocket.receive_json()
                if message.get("type") == "ping":
                    await websocket.send_json({"type": "pong"})

        sender = asyncio.create_task(pump_events())
        receiver = asyncio.create_task(pump_client())
        try:
            done, pending = await asyncio.wait(
                {sender, receiver}, return_when=asyncio.FIRST_COMPLETED
            )
            for task in pending:
                task.cancel()
            for task in done:
                # Surface anything other than a normal client disconnect.
                with contextlib.suppress(WebSocketDisconnect, asyncio.CancelledError):
                    task.result()
        except WebSocketDisconnect:
            pass
        finally:
            for task in (sender, receiver):
                task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await asyncio.gather(sender, receiver, return_exceptions=True)
