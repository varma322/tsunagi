"""Durable audit logging.

The event bus keeps a capped, transient log; this trail is the opposite --
persisted, uncapped, and readable after a restart. These cover what that
implies: administrative and security events land in it, high-frequency message
traffic deliberately does not, and it is admin-only and paginated.
"""

import uuid
from datetime import UTC, datetime

from tests.conftest import make_message


def audit(client, headers, **params):
    return client.get("/api/v1/audit", params=params, headers=headers)


def types_in(client, headers, **params) -> list[str]:
    body = audit(client, headers, **params).json()
    return [event["type"] for event in body["events"]]


# --- what is and isn't recorded ------------------------------------------


def test_registering_a_device_is_audited(client, admin_headers, setup_headers):
    response = client.post(
        "/api/v1/devices/register",
        json={"device_name": f"Audited {uuid.uuid4().hex[:6]}"},
        headers=setup_headers,
    )
    device_id = response.json()["device_id"]

    events = audit(client, admin_headers, type="DEVICE_REGISTERED").json()["events"]
    mine = [e for e in events if e["payload"].get("device_id") == device_id]
    assert len(mine) == 1
    assert mine[0]["level"] == "info"
    assert mine[0]["id"]
    assert mine[0]["created_at"]


def test_message_traffic_is_not_audited(client, admin_headers, device):
    client.post("/api/v1/messages", json=make_message(), headers=device["headers"])
    client.post(
        "/api/v1/messages/batch",
        json={"messages": [make_message(), make_message()]},
        headers=device["headers"],
    )

    all_types = types_in(client, admin_headers, limit=500)
    assert "MSG_RECV" not in all_types, "per-message events would bury the trail"
    assert "SYNC_OK" not in all_types, "per-sync events would bury the trail"


def test_a_blocked_capture_is_audited_with_its_reason(client, admin_headers, device):
    client.post(
        "/api/v1/devices/checkin",
        json={
            "capture_permitted": False,
            "inbox_readable": True,
            "battery_exempt": True,
        },
        headers=device["headers"],
    )

    events = audit(client, admin_headers, type="DEVICE_CAPTURE_BLOCKED").json()["events"]
    mine = [e for e in events if e["payload"].get("device_id") == device["id"]]
    assert len(mine) == 1
    assert mine[0]["level"] == "error"
    assert "permission" in mine[0]["payload"]["reason"]


# --- durability / identity -----------------------------------------------


def test_an_audited_event_has_a_stable_id_and_reads_back_the_same(client, admin_headers, device):
    """Unlike a live event, a durable one has an id and survives a re-read."""
    first = audit(client, admin_headers, type="DEVICE_REGISTERED").json()["events"]
    again = audit(client, admin_headers, type="DEVICE_REGISTERED").json()["events"]

    assert first, "the device fixture registered, so there is at least one"
    assert [e["id"] for e in first] == [e["id"] for e in again]


# --- querying ------------------------------------------------------------


def test_filtering_by_type_returns_only_that_type(client, admin_headers, device):
    body = audit(client, admin_headers, type="DEVICE_REGISTERED").json()
    assert body["events"]
    assert {e["type"] for e in body["events"]} == {"DEVICE_REGISTERED"}


def test_filtering_by_level_returns_only_that_level(client, admin_headers, device, setup_headers):
    # Disabling a device is a warn-level event.
    client.post(
        f"/api/v1/devices/{device['id']}/enabled",
        json={"enabled": False},
        headers=admin_headers,
    )
    body = audit(client, admin_headers, level="warn", limit=500).json()
    assert body["events"]
    assert all(e["level"] == "warn" for e in body["events"])


def test_the_trail_is_newest_first(client, admin_headers):
    events = audit(client, admin_headers, limit=500).json()["events"]
    stamps = [e["created_at"] for e in events]
    assert stamps == sorted(stamps, reverse=True)


def test_it_paginates(client, admin_headers):
    page = audit(client, admin_headers, limit=2, offset=0).json()
    assert page["limit"] == 2 and page["offset"] == 0
    assert len(page["events"]) <= 2
    assert page["total"] >= len(page["events"])

    if page["total"] > 2:
        second = audit(client, admin_headers, limit=2, offset=2).json()
        assert {e["id"] for e in second["events"]}.isdisjoint({e["id"] for e in page["events"]})


def test_a_time_window_applies(client, admin_headers):
    future = datetime(2100, 1, 1, tzinfo=UTC).isoformat()
    assert audit(client, admin_headers, after=future).json()["events"] == []


# --- authorization -------------------------------------------------------


def test_audit_is_admin_only(client, user_headers, device):
    assert client.get("/api/v1/audit", headers=user_headers).status_code == 403
    assert client.get("/api/v1/audit", headers=device["headers"]).status_code == 403


def test_audit_requires_a_credential(client):
    assert client.get("/api/v1/audit").status_code == 401
