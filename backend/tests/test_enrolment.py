"""Single-use enrolment codes."""

import uuid

import pytest

from tests.conftest import ADMIN_KEY, SETUP_KEY


def issue(client, admin_headers, **payload):
    response = client.post("/api/v1/enrolments", json=payload, headers=admin_headers)
    assert response.status_code == 201, response.text
    return response.json()


def register_with(client, code, name="Enrolled Phone"):
    return client.post(
        "/api/v1/devices/register",
        json={"device_name": name},
        headers={"Authorization": f"Bearer {code}"},
    )


# --- issuing --------------------------------------------------------------


def test_issued_code_is_short_and_typeable(client, admin_headers):
    body = issue(client, admin_headers, label="Arun's Pixel")

    code = body["code"]
    assert len(code) == 9 and code[4] == "-", "expected ABCD-EFGH"
    # Characters that are misread when typed off a screen are excluded.
    assert not set(code.replace("-", "")) & set("ILOU01")
    assert body["status"] == "pending"
    assert body["label"] == "Arun's Pixel"


def test_listing_never_returns_the_code(client, admin_headers):
    created = issue(client, admin_headers, label="listed")

    listed = client.get("/api/v1/enrolments", headers=admin_headers).json()["enrolments"]
    entry = next(item for item in listed if item["id"] == created["id"])
    assert "code" not in entry


def test_only_admins_can_issue_codes(client, user_headers):
    assert client.post("/api/v1/enrolments", json={}, headers=user_headers).status_code == 403
    assert client.get("/api/v1/enrolments", headers=user_headers).status_code == 403


# --- redeeming ------------------------------------------------------------


def test_a_code_registers_one_device(client, admin_headers):
    code = issue(client, admin_headers)["code"]

    response = register_with(client, code)

    assert response.status_code == 201
    assert response.json()["token"].startswith("tsn_dev_")


def test_a_code_cannot_be_used_twice(client, admin_headers):
    code = issue(client, admin_headers)["code"]

    assert register_with(client, code, "First").status_code == 201
    second = register_with(client, code, "Second")

    assert second.status_code == 403
    assert second.json()["error"]["code"] == "enrolment_used"


def test_using_a_code_records_which_device_it_produced(client, admin_headers):
    created = issue(client, admin_headers)
    device_id = register_with(client, created["code"]).json()["device_id"]

    listed = client.get("/api/v1/enrolments", headers=admin_headers).json()["enrolments"]
    entry = next(item for item in listed if item["id"] == created["id"])

    assert entry["status"] == "used"
    assert entry["used_by_device_id"] == device_id
    assert entry["used_at"] is not None


@pytest.mark.parametrize(
    "typed",
    ["{code}", "{lower}", "{nodash}", " {code} "],
    ids=["as-shown", "lowercase", "without-dash", "with-spaces"],
)
def test_codes_are_accepted_however_they_are_typed(client, admin_headers, typed):
    code = issue(client, admin_headers)["code"]
    candidate = typed.format(code=code, lower=code.lower(), nodash=code.replace("-", ""))

    assert register_with(client, candidate).status_code == 201


def test_an_unknown_code_is_rejected(client):
    # Well-formed but never issued.
    assert register_with(client, "ABCD-EFGH").status_code == 401


def test_an_expired_code_is_refused(client, admin_headers):
    code = issue(client, admin_headers, ttl_seconds=60)["code"]

    # Rewind the clock past the expiry rather than sleeping through it.
    import asyncio
    from datetime import UTC, datetime, timedelta

    from app.db import get_session_factory
    from app.models import EnrolmentToken
    from sqlalchemy import update

    async def expire():
        async with get_session_factory()() as session:
            await session.execute(
                update(EnrolmentToken).values(
                    expires_at=datetime.now(UTC) - timedelta(minutes=1)
                )
            )
            await session.commit()

    asyncio.run(expire())

    response = register_with(client, code)
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "enrolment_expired"


# --- cancelling -----------------------------------------------------------


def test_cancelling_a_code_prevents_its_use(client, admin_headers):
    created = issue(client, admin_headers)

    assert (
        client.delete(f"/api/v1/enrolments/{created['id']}", headers=admin_headers).status_code
        == 204
    )

    response = register_with(client, created["code"])
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "enrolment_cancelled"


def test_a_spent_code_cannot_be_cancelled(client, admin_headers):
    created = issue(client, admin_headers)
    register_with(client, created["code"])

    response = client.delete(f"/api/v1/enrolments/{created['id']}", headers=admin_headers)
    assert response.status_code == 409


def test_cancelling_an_unknown_code_is_404(client, admin_headers):
    assert (
        client.delete(f"/api/v1/enrolments/{uuid.uuid4()}", headers=admin_headers).status_code
        == 404
    )


# --- the other registration credentials still work ------------------------


def test_admin_key_can_still_register_directly(client, admin_headers):
    response = client.post(
        "/api/v1/devices/register", json={"device_name": "Admin Added"}, headers=admin_headers
    )
    assert response.status_code == 201


def test_legacy_setup_key_still_works_when_configured(client):
    response = client.post(
        "/api/v1/devices/register",
        json={"device_name": "Legacy"},
        headers={"Authorization": f"Bearer {SETUP_KEY}"},
    )
    assert response.status_code == 201


def test_an_enrolment_code_grants_nothing_else(client, admin_headers):
    """A code authorizes registration and nothing more."""
    code = issue(client, admin_headers)["code"]
    headers = {"Authorization": f"Bearer {code}"}

    assert client.get("/api/v1/messages", headers=headers).status_code == 403
    assert client.get("/api/v1/enrolments", headers=headers).status_code == 403
    assert client.get("/api/v1/me", headers=headers).json()["scope"] == "device"


def test_device_token_cannot_issue_codes(client, device):
    assert (
        client.post("/api/v1/enrolments", json={}, headers=device["headers"]).status_code == 403
    )


def test_events_record_the_enrolment_lifecycle(client, admin_headers):
    created = issue(client, admin_headers, label="audited")
    register_with(client, created["code"])

    events = client.get(
        "/api/v1/events", params={"limit": 200}, headers={"Authorization": f"Bearer {ADMIN_KEY}"}
    ).json()["events"]
    types = {event["type"] for event in events}

    assert {"ENROLMENT_CREATED", "ENROLMENT_USED", "DEVICE_REGISTERED"} <= types
