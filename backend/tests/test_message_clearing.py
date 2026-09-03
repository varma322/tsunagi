"""Clearing a device's messages: permanent, scoped, and recorded."""

import uuid

from tests.conftest import make_message


def upload(client, device, count=1, sender="+15559990000", body="clearable"):
    for index in range(count):
        payload = make_message(sender=sender, body=f"{body}-{index}")
        response = client.post("/api/v1/messages", json=payload, headers=device["headers"])
        assert response.status_code == 201, response.text


def clear(client, device_id, headers):
    return client.delete(f"/api/v1/devices/{device_id}/messages", headers=headers)


def listed(client, headers, device_id):
    response = client.get(
        "/api/v1/messages", params={"device_id": device_id}, headers=headers
    )
    assert response.status_code == 200, response.text
    return response.json()["total"]


def test_clearing_deletes_the_devices_messages(client, device, admin_headers):
    upload(client, device, count=3)
    assert listed(client, admin_headers, device["id"]) == 3

    response = clear(client, device["id"], admin_headers)
    assert response.status_code == 200, response.text
    assert response.json() == {"deleted": 3}
    assert listed(client, admin_headers, device["id"]) == 0


def test_clearing_one_device_leaves_another_alone(client, device, admin_headers, setup_headers):
    other = client.post(
        "/api/v1/devices/register",
        json={"device_name": f"Other {uuid.uuid4().hex[:6]}"},
        headers=setup_headers,
    ).json()
    other_device = {
        "id": other["device_id"],
        "headers": {"Authorization": f"Bearer {other['token']}"},
    }

    upload(client, device, count=2)
    upload(client, other_device, count=3)

    clear(client, device["id"], admin_headers)

    assert listed(client, admin_headers, device["id"]) == 0
    assert listed(client, admin_headers, other_device["id"]) == 3


def test_clearing_drops_the_messages_from_the_statistics(client, device, admin_headers):
    def stats():
        return client.get("/api/v1/stats", headers=admin_headers).json()

    before = stats()
    upload(client, device, count=4)
    assert stats()["messages_total"] == before["messages_total"] + 4

    clear(client, device["id"], admin_headers)
    after = stats()
    assert after["messages_total"] == before["messages_total"]
    assert after["storage_bytes"] == before["storage_bytes"]


def test_clearing_twice_reports_nothing_the_second_time(client, device, admin_headers):
    upload(client, device, count=2)
    assert clear(client, device["id"], admin_headers).json() == {"deleted": 2}
    assert clear(client, device["id"], admin_headers).json() == {"deleted": 0}


def test_a_cleared_message_uploads_again_as_new(client, device, admin_headers):
    """Documents a real consequence of deleting rather than marking.

    Dedup matches uploads against stored ids, so once a message is deleted the
    server has no memory of it. A phone that re-uploads -- after a reinstall
    resets its inbox-sweep watermark, say -- stores it again as a fresh message
    rather than recognising it as one already seen and cleared.
    """
    payload = make_message(body="resent-after-clearing")
    first = client.post("/api/v1/messages", json=payload, headers=device["headers"])
    assert first.status_code == 201, first.text

    clear(client, device["id"], admin_headers)
    assert listed(client, admin_headers, device["id"]) == 0

    again = client.post("/api/v1/messages", json=payload, headers=device["headers"])
    assert again.status_code == 201, again.text
    assert listed(client, admin_headers, device["id"]) == 1


def test_clearing_requires_an_admin(client, device, user_headers):
    upload(client, device, count=1)
    assert clear(client, device["id"], user_headers).status_code == 403


def test_clearing_an_unknown_device_is_not_found(client, admin_headers):
    assert clear(client, uuid.uuid4(), admin_headers).status_code == 404


def test_a_revoked_device_can_still_have_its_messages_cleared(client, device, admin_headers):
    """Retiring a phone and then clearing its messages is the ordinary case, so
    this deliberately does not reuse the revoked-device guard the other device
    endpoints apply."""
    upload(client, device, count=2)
    revoked = client.delete(f"/api/v1/devices/{device['id']}", headers=admin_headers)
    assert revoked.status_code == 204, revoked.text

    response = clear(client, device["id"], admin_headers)
    assert response.status_code == 200, response.text
    assert response.json() == {"deleted": 2}


def test_clearing_is_recorded_in_the_audit_trail(client, device, admin_headers):
    """The trail is what survives the messages.

    Nothing else records that they existed once the rows are gone, which is why
    this is the one assertion here that would matter most if it broke.
    """
    upload(client, device, count=2)
    clear(client, device["id"], admin_headers)

    response = client.get(
        "/api/v1/audit",
        params={"type": "DEVICE_MESSAGES_CLEARED", "limit": 500},
        headers=admin_headers,
    )
    assert response.status_code == 200, response.text
    entries = [
        event
        for event in response.json()["events"]
        if event["payload"].get("device_id") == device["id"]
    ]
    assert len(entries) == 1
    assert entries[0]["level"] == "warn"
    assert entries[0]["payload"]["count"] == 2
    # The name is recorded alongside the id: an id alone identifies a device
    # row that a later revocation may well have made meaningless.
    assert entries[0]["payload"]["name"]
