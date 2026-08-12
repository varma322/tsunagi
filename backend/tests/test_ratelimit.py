import asyncio

import pytest

from app.ratelimit import RateLimiter

from tests.conftest import ADMIN_KEY, make_message


def run(coro):
    return asyncio.run(coro)


# --- limiter unit behaviour ----------------------------------------------


def test_allows_up_to_the_limit_then_blocks():
    limiter = RateLimiter(limit=3, window_seconds=60)

    decisions = [run(limiter.check("client")) for _ in range(4)]

    assert [d.allowed for d in decisions] == [True, True, True, False]
    assert [d.remaining for d in decisions] == [2, 1, 0, 0]
    assert decisions[-1].retry_after >= 1


def test_identities_have_separate_budgets():
    limiter = RateLimiter(limit=1, window_seconds=60)

    assert run(limiter.check("first")).allowed
    assert not run(limiter.check("first")).allowed
    assert run(limiter.check("second")).allowed, "one client must not spend another's budget"


def test_counters_reset_in_the_next_window(monkeypatch):
    limiter = RateLimiter(limit=1, window_seconds=60)
    clock = {"now": 1_000.0}
    monkeypatch.setattr("app.ratelimit.time.time", lambda: clock["now"])

    assert run(limiter.check("client")).allowed
    assert not run(limiter.check("client")).allowed

    clock["now"] += 61
    assert run(limiter.check("client")).allowed


def test_expired_windows_are_discarded(monkeypatch):
    limiter = RateLimiter(limit=10_000, window_seconds=60)
    clock = {"now": 1_000.0}
    monkeypatch.setattr("app.ratelimit.time.time", lambda: clock["now"])

    for index in range(5000):
        run(limiter.check(f"client-{index}"))
    clock["now"] += 61
    run(limiter.check("fresh"))

    assert len(limiter._counters) == 1, "stale windows must not accumulate"


# --- middleware integration ----------------------------------------------


@pytest.fixture
def strict_limit(client):
    """Swap in a limiter that trips after two requests."""
    app = client.app
    original = app.state.rate_limiter
    app.state.rate_limiter = RateLimiter(limit=2, window_seconds=60)
    yield
    app.state.rate_limiter = original


def test_exceeding_the_limit_returns_429(client, strict_limit, admin_headers):
    statuses = [
        client.get("/api/v1/messages", headers=admin_headers).status_code for _ in range(3)
    ]
    assert statuses == [200, 200, 429]

    blocked = client.get("/api/v1/messages", headers=admin_headers)
    assert blocked.json()["error"]["code"] == "rate_limited"
    assert int(blocked.headers["Retry-After"]) >= 1


def test_successful_responses_carry_budget_headers(client, strict_limit, admin_headers):
    response = client.get("/api/v1/messages", headers=admin_headers)

    assert response.headers["X-RateLimit-Limit"] == "2"
    assert response.headers["X-RateLimit-Remaining"] == "1"


def test_health_is_never_limited(client, strict_limit):
    assert all(client.get("/health").status_code == 200 for _ in range(5))


def test_credentials_have_independent_budgets(client, strict_limit, device, user_headers):
    # Spend the device's budget entirely.
    for _ in range(3):
        client.post("/api/v1/messages", json=make_message(), headers=device["headers"])

    assert client.get("/api/v1/messages", headers=user_headers).status_code == 200


def test_unauthenticated_requests_are_limited_by_address(client, strict_limit):
    statuses = [client.get("/api/v1/messages").status_code for _ in range(3)]

    # 401 still consumes budget, which is what protects credential guessing.
    assert statuses == [401, 401, 429]


def test_limiter_can_be_disabled(client, admin_headers):
    app = client.app
    original = app.state.rate_limiter
    app.state.rate_limiter = None
    try:
        statuses = [
            client.get("/api/v1/messages", headers=admin_headers).status_code for _ in range(5)
        ]
        assert statuses == [200] * 5
    finally:
        app.state.rate_limiter = original


def test_websocket_bypasses_the_limiter(client, strict_limit):
    for _ in range(4):
        with client.websocket_connect(f"/ws/messages?token={ADMIN_KEY}") as websocket:
            websocket.send_json({"type": "ping"})
            assert websocket.receive_json() == {"type": "pong"}
