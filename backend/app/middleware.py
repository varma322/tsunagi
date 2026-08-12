from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.deps import bearer_token
from app.security import hash_secret

# Probes and API documentation are exempt: rate limiting them turns a health
# check into a source of alerts without protecting anything.
EXEMPT_PATHS = frozenset({"/health", "/docs", "/redoc", "/openapi.json"})


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Applies the app's rate limiter per credential.

    WebSocket connections never reach here — Starlette routes them around HTTP
    middleware — which is intended: a long-lived socket is one request, and the
    limiter would only penalise reconnects.
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        limiter = getattr(request.app.state, "rate_limiter", None)
        if limiter is None or request.url.path in EXEMPT_PATHS:
            return await call_next(request)

        decision = await limiter.check(identify(request))

        if not decision.allowed:
            return JSONResponse(
                status_code=429,
                content={
                    "error": {
                        "code": "rate_limited",
                        "message": (
                            f"Rate limit of {decision.limit} requests per window exceeded. "
                            f"Retry in {decision.retry_after}s."
                        ),
                    }
                },
                headers={
                    "Retry-After": str(decision.retry_after),
                    "X-RateLimit-Limit": str(decision.limit),
                    "X-RateLimit-Remaining": "0",
                },
            )

        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(decision.limit)
        response.headers["X-RateLimit-Remaining"] = str(decision.remaining)
        return response


def identify(request: Request) -> str:
    """Bucket key for a request.

    Credentials are bucketed by digest rather than raw value so tokens never
    reach the limiter's storage or logs. Unauthenticated callers fall back to
    their address, which is what protects the login-shaped endpoints.
    """
    token = bearer_token(request)
    if token:
        return f"key:{hash_secret(token)[:32]}"

    client = request.client
    return f"ip:{client.host if client else 'unknown'}"
