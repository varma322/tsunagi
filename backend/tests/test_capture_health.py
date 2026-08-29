"""Capture health: whether a device can still receive SMS, not just reach us.

The distinction these cover is the one the dashboard could not previously make.
A phone whose SMS permission has been revoked keeps answering the heartbeat and
keeps reporting last_seen, so before the check-in it was indistinguishable from
a phone nobody had texted.
"""

from datetime import UTC, datetime, timedelta


def report(**overrides) -> dict:
    body = {
        "capture_permitted": True,
        "inbox_readable": True,
        "battery_exempt": True,
        "last_captured_at": datetime.now(UTC).isoformat(),
        "last_swept_at": datetime.now(UTC).isoformat(),
    }
    body.update(overrides)
    return body


def find(client, headers, device_id):
    devices = client.get("/api/v1/devices", headers=headers).json()["devices"]
    return next(d for d in devices if d["id"] == device_id)


# --- reporting ------------------------------------------------------------


def test_a_device_that_never_reported_is_unknown(client, device, admin_headers):
    row = find(client, admin_headers, device["id"])
    assert row["capture"] == "unknown"
    assert row["capture_reported_at"] is None


def test_check_in_records_a_healthy_device(client, device, admin_headers):
    response = client.post(
        "/api/v1/devices/checkin", json=report(), headers=device["headers"]
    )
    assert response.status_code == 200, response.text
    assert response.json()["capture"] == "ok"

    row = find(client, admin_headers, device["id"])
    assert row["capture"] == "ok"
    assert row["capture_permitted"] is True
    assert row["battery_exempt"] is True
    assert row["capture_reported_at"] is not None


def test_revoked_sms_permission_blocks_capture(client, device, admin_headers):
    client.post(
        "/api/v1/devices/checkin",
        json=report(capture_permitted=False),
        headers=device["headers"],
    )
    row = find(client, admin_headers, device["id"])
    assert row["capture"] == "blocked"
    assert row["capture_permitted"] is False


def test_an_unreadable_inbox_blocks_capture(client, device, admin_headers):
    """The sweep is the only defence against a missed broadcast. One that
    cannot read the provider is a broken safety net, not a quiet one."""
    client.post(
        "/api/v1/devices/checkin",
        json=report(inbox_readable=False),
        headers=device["headers"],
    )
    assert find(client, admin_headers, device["id"])["capture"] == "blocked"


def test_a_quiet_device_is_still_healthy(client, device, admin_headers):
    """The case that must not read as broken: capture works, nothing arrived."""
    long_ago = (datetime.now(UTC) - timedelta(days=30)).isoformat()
    client.post(
        "/api/v1/devices/checkin",
        json=report(last_captured_at=long_ago),
        headers=device["headers"],
    )
    row = find(client, admin_headers, device["id"])
    assert row["capture"] == "ok"
    assert row["last_captured_at"].startswith(long_ago[:10])


def test_a_device_with_no_messages_yet_may_report_no_capture_time(client, device):
    response = client.post(
        "/api/v1/devices/checkin",
        json=report(last_captured_at=None, last_swept_at=None),
        headers=device["headers"],
    )
    assert response.status_code == 200
    body = response.json()
    assert body["capture"] == "ok"
    assert body["last_captured_at"] is None


def test_recovery_is_reported(client, device, admin_headers):
    client.post(
        "/api/v1/devices/checkin",
        json=report(capture_permitted=False),
        headers=device["headers"],
    )
    client.post("/api/v1/devices/checkin", json=report(), headers=device["headers"])
    assert find(client, admin_headers, device["id"])["capture"] == "ok"


# --- events ---------------------------------------------------------------


def test_blocking_raises_an_event(client, device, admin_headers):
    client.post(
        "/api/v1/devices/checkin",
        json=report(capture_permitted=False),
        headers=device["headers"],
    )
    events = client.get("/api/v1/events", headers=admin_headers).json()["events"]
    blocked = [
        event
        for event in events
        if event["type"] == "DEVICE_CAPTURE_BLOCKED"
        and event["payload"]["device_id"] == device["id"]
    ]
    assert len(blocked) == 1
    assert blocked[0]["level"] == "error"
    assert "permission" in blocked[0]["payload"]["reason"]


def test_an_unchanged_report_is_not_announced_twice(client, device, admin_headers):
    """A blocked phone checks in every fifteen minutes. One event per pass would
    bury the transition in a log of identical lines."""
    for _ in range(3):
        client.post(
            "/api/v1/devices/checkin",
            json=report(capture_permitted=False),
            headers=device["headers"],
        )
    events = client.get("/api/v1/events", headers=admin_headers).json()["events"]
    blocked = [
        event
        for event in events
        if event["type"] == "DEVICE_CAPTURE_BLOCKED"
        and event["payload"]["device_id"] == device["id"]
    ]
    assert len(blocked) == 1


def test_upgrading_an_old_app_is_not_announced(client, device, admin_headers):
    """unknown -> ok is an app gaining the feature, not a device recovering."""
    client.post("/api/v1/devices/checkin", json=report(), headers=device["headers"])
    events = client.get("/api/v1/events", headers=admin_headers).json()["events"]
    assert not [
        event
        for event in events
        if event["type"] == "DEVICE_CAPTURE_RESTORED"
        and event["payload"]["device_id"] == device["id"]
    ]


# --- authorization --------------------------------------------------------


def test_check_in_requires_a_device_token(client, admin_headers):
    response = client.post("/api/v1/devices/checkin", json=report(), headers=admin_headers)
    assert response.status_code == 403


def test_check_in_rejects_an_incomplete_report(client, device):
    response = client.post(
        "/api/v1/devices/checkin", json={"battery_exempt": True}, headers=device["headers"]
    )
    assert response.status_code == 422
