"""Admin vs. user authorization, and the device on/off switch."""

from tests.conftest import make_message


def set_enabled(client, device_id, enabled, headers):
    return client.post(
        f"/api/v1/devices/{device_id}/enabled", json={"enabled": enabled}, headers=headers
    )


# --- identity -------------------------------------------------------------


def test_me_reports_admin_scope(client, admin_headers):
    body = client.get("/api/v1/me", headers=admin_headers).json()
    assert body["kind"] == "key"
    assert body["scope"] == "admin"
    assert body["name"] == "bootstrap-admin"


def test_me_reports_user_scope(client, user_headers):
    body = client.get("/api/v1/me", headers=user_headers).json()
    assert body["scope"] == "user"


def test_me_reports_device_scope(client, device):
    body = client.get("/api/v1/me", headers=device["headers"]).json()
    assert body["kind"] == "device"
    assert body["scope"] == "device"


def test_me_requires_a_credential(client):
    assert client.get("/api/v1/me").status_code == 401


# --- scope boundaries -----------------------------------------------------


def test_user_can_read_messages_and_devices(client, user_headers):
    assert client.get("/api/v1/messages", headers=user_headers).status_code == 200
    assert client.get("/api/v1/devices", headers=user_headers).status_code == 200
    assert client.get("/api/v1/stats", headers=user_headers).status_code == 200


def test_user_cannot_reach_admin_surfaces(client, user_headers, device):
    assert client.get("/api/v1/keys", headers=user_headers).status_code == 403
    assert client.get("/api/v1/events", headers=user_headers).status_code == 403
    assert set_enabled(client, device["id"], False, user_headers).status_code == 403
    assert client.delete(f"/api/v1/devices/{device['id']}", headers=user_headers).status_code == 403


def test_admin_can_read_events(client, admin_headers):
    assert client.get("/api/v1/events", headers=admin_headers).status_code == 200


# --- the on/off switch ----------------------------------------------------


def test_disabling_a_device_blocks_uploads(client, device, admin_headers):
    assert client.post(
        "/api/v1/messages", json=make_message(), headers=device["headers"]
    ).status_code == 201

    assert set_enabled(client, device["id"], False, admin_headers).status_code == 200

    blocked = client.post("/api/v1/messages", json=make_message(), headers=device["headers"])
    assert blocked.status_code == 403
    assert blocked.json()["error"]["code"] == "device_disabled"


def test_disabled_device_gets_403_not_401(client, device, admin_headers):
    """The phone re-enrols on 401, so a disabled device must never see one.

    Answering 401 here would let a switched-off phone register again with its
    stored setup key and keep uploading under a new id.
    """
    set_enabled(client, device["id"], False, admin_headers)

    response = client.post("/api/v1/messages", json=make_message(), headers=device["headers"])
    assert response.status_code == 403, "401 would trigger client-side re-enrolment"


def test_re_enabling_restores_uploads(client, device, admin_headers):
    set_enabled(client, device["id"], False, admin_headers)
    assert set_enabled(client, device["id"], True, admin_headers).status_code == 200

    assert client.post(
        "/api/v1/messages", json=make_message(), headers=device["headers"]
    ).status_code == 201


def test_disabled_device_is_listed_as_disabled_and_offline(client, device, admin_headers):
    client.post("/api/v1/messages", json=make_message(), headers=device["headers"])
    set_enabled(client, device["id"], False, admin_headers)

    entry = next(
        d
        for d in client.get("/api/v1/devices", headers=admin_headers).json()["devices"]
        if d["id"] == device["id"]
    )
    assert entry["enabled"] is False
    assert entry["status"] is False, "a switched-off device is never online"
    assert entry["disabled_at"] is not None


def test_disabled_device_is_excluded_from_active_count(client, device, admin_headers):
    client.post("/api/v1/messages", json=make_message(), headers=device["headers"])
    before = client.get("/api/v1/stats", headers=admin_headers).json()["active_devices"]

    set_enabled(client, device["id"], False, admin_headers)
    after = client.get("/api/v1/stats", headers=admin_headers).json()["active_devices"]

    assert after == before - 1


def test_revoked_device_reports_revoked(client, device, admin_headers):
    client.delete(f"/api/v1/devices/{device['id']}", headers=admin_headers)

    response = client.post("/api/v1/messages", json=make_message(), headers=device["headers"])
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "device_revoked"


def test_unknown_device_token_is_still_401(client):
    """Only known-but-switched-off devices get 403; an unrecognised token is
    genuinely unauthorized."""
    response = client.post(
        "/api/v1/messages",
        json=make_message(),
        headers={"Authorization": "Bearer tsn_dev_not-a-real-token"},
    )
    assert response.status_code == 401


def test_toggling_an_unknown_device_is_404(client, admin_headers):
    import uuid

    assert set_enabled(client, uuid.uuid4(), False, admin_headers).status_code == 404


def test_disabled_device_cannot_open_a_websocket(client, device, admin_headers):
    import pytest
    from starlette.websockets import WebSocketDisconnect

    set_enabled(client, device["id"], False, admin_headers)

    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(f"/ws/messages?token={device['token']}") as websocket:
            websocket.receive_json()
