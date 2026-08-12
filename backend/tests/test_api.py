import threading
import time
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from starlette.websockets import WebSocketDisconnect

from tests.conftest import ADMIN_KEY, make_message


def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


# --- authentication -------------------------------------------------------


def test_unauthenticated_request_is_rejected(client):
    response = client.get("/api/v1/messages")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


def test_unknown_token_is_rejected(client):
    response = client.get(
        "/api/v1/messages", headers={"Authorization": "Bearer tsn_key_not-a-real-key"}
    )
    assert response.status_code == 401


def test_device_token_cannot_read_messages(client, device):
    response = client.get("/api/v1/messages", headers=device["headers"])
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden"


def test_user_key_cannot_manage_keys(client, user_headers):
    response = client.get("/api/v1/keys", headers=user_headers)
    assert response.status_code == 403


def test_registration_requires_setup_or_admin(client, user_headers):
    response = client.post(
        "/api/v1/devices/register", json={"device_name": "Nope"}, headers=user_headers
    )
    assert response.status_code == 403


# --- devices --------------------------------------------------------------


def test_register_device_returns_token(client, setup_headers):
    response = client.post(
        "/api/v1/devices/register", json={"device_name": "Office Phone"}, headers=setup_headers
    )
    assert response.status_code == 201
    body = response.json()
    assert body["token"].startswith("tsn_dev_")
    uuid.UUID(body["device_id"])


def test_device_appears_online_after_upload(client, device, user_headers):
    client.post("/api/v1/messages", json=make_message(), headers=device["headers"])

    response = client.get("/api/v1/devices", headers=user_headers)
    assert response.status_code == 200
    entry = next(d for d in response.json()["devices"] if d["id"] == device["id"])
    assert entry["status"] is True
    assert entry["last_seen"] is not None


def test_revoked_device_token_stops_working(client, device, admin_headers):
    assert (
        client.delete(f"/api/v1/devices/{device['id']}", headers=admin_headers).status_code == 204
    )
    response = client.post("/api/v1/messages", json=make_message(), headers=device["headers"])
    # 403 rather than 401 on purpose: the client re-enrols on 401. See
    # tests/test_admin.py::test_disabled_device_gets_403_not_401.
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "device_revoked"


def test_revoking_unknown_device_is_404(client, admin_headers):
    response = client.delete(f"/api/v1/devices/{uuid.uuid4()}", headers=admin_headers)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


# --- message ingestion ----------------------------------------------------


def test_upload_message(client, device):
    payload = make_message(body="Your verification code is 482913")
    response = client.post("/api/v1/messages", json=payload, headers=device["headers"])
    assert response.status_code == 201
    body = response.json()
    assert body["id"] == payload["id"]
    assert body["device_id"] == device["id"]
    assert body["body"] == payload["body"]


def test_reuploading_same_id_is_idempotent(client, device, user_headers):
    payload = make_message()
    first = client.post("/api/v1/messages", json=payload, headers=device["headers"])
    second = client.post("/api/v1/messages", json=payload, headers=device["headers"])

    assert first.status_code == 201
    assert second.status_code == 200
    assert first.json()["created_at"] == second.json()["created_at"]

    listed = client.get(
        "/api/v1/messages", params={"device_id": device["id"]}, headers=user_headers
    )
    assert listed.json()["total"] == 1


def test_batch_upload_reports_duplicates(client, device):
    shared = make_message()
    client.post("/api/v1/messages", json=shared, headers=device["headers"])

    response = client.post(
        "/api/v1/messages/batch",
        json={"messages": [shared, make_message(), make_message()]},
        headers=device["headers"],
    )
    assert response.status_code == 200
    assert response.json() == {"accepted": 3, "created": 2, "duplicates": 1}


def test_malformed_message_is_rejected(client, device):
    response = client.post(
        "/api/v1/messages",
        json={"id": "not-a-uuid", "sender": "x", "body": "y", "received_at": "nope"},
        headers=device["headers"],
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


# --- querying -------------------------------------------------------------


def test_list_filters_and_paginates(client, device, user_headers):
    for index in range(5):
        client.post(
            "/api/v1/messages",
            json=make_message(sender="+15550000001", body=f"filter probe {index}"),
            headers=device["headers"],
        )

    response = client.get(
        "/api/v1/messages",
        params={"sender": "+15550000001", "limit": 2, "offset": 0},
        headers=user_headers,
    )
    body = response.json()
    assert body["total"] == 5
    assert len(body["messages"]) == 2
    assert body["limit"] == 2

    page_two = client.get(
        "/api/v1/messages",
        params={"sender": "+15550000001", "limit": 2, "offset": 2},
        headers=user_headers,
    ).json()
    first_ids = {m["id"] for m in body["messages"]}
    assert first_ids.isdisjoint({m["id"] for m in page_two["messages"]})


def test_list_respects_time_window(client, device, user_headers):
    client.post(
        "/api/v1/messages",
        json=make_message(sender="+15550000002", body="time probe"),
        headers=device["headers"],
    )
    future = (datetime.now(UTC) + timedelta(hours=1)).isoformat()

    response = client.get(
        "/api/v1/messages",
        params={"sender": "+15550000002", "after": future},
        headers=user_headers,
    )
    assert response.json()["total"] == 0


def test_search_matches_body(client, device, user_headers):
    needle = f"pineapple-{uuid.uuid4().hex[:8]}"
    client.post(
        "/api/v1/messages",
        json=make_message(body=f"delivery of {needle} confirmed"),
        headers=device["headers"],
    )

    response = client.get("/api/v1/messages/search", params={"query": needle}, headers=user_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert needle in body["messages"][0]["body"]


def test_search_requires_query(client, user_headers):
    assert client.get("/api/v1/messages/search", headers=user_headers).status_code == 422


# --- real time ------------------------------------------------------------


def test_wait_returns_immediately_when_backlog_exists(client, device, user_headers):
    since = datetime.now(UTC).isoformat()
    client.post("/api/v1/messages", json=make_message(body="backlog"), headers=device["headers"])

    started = time.monotonic()
    response = client.get(
        "/api/v1/messages/wait",
        params={"since": since, "timeout": 5},
        headers=user_headers,
    )
    assert response.status_code == 200
    assert len(response.json()["messages"]) >= 1
    assert time.monotonic() - started < 5


def test_wait_times_out_with_no_traffic(client, user_headers):
    response = client.get(
        "/api/v1/messages/wait",
        params={"since": datetime.now(UTC).isoformat(), "timeout": 1},
        headers=user_headers,
    )
    assert response.status_code == 200
    assert response.json()["messages"] == []


def test_wait_wakes_on_new_message(client, device, user_headers):
    since = datetime.now(UTC).isoformat()
    payload = make_message(body="woken by long poll")

    def upload_soon() -> None:
        time.sleep(0.6)
        client.post("/api/v1/messages", json=payload, headers=device["headers"])

    uploader = threading.Thread(target=upload_soon)
    uploader.start()
    try:
        response = client.get(
            "/api/v1/messages/wait",
            params={"since": since, "timeout": 15},
            headers=user_headers,
        )
    finally:
        uploader.join()

    assert response.status_code == 200
    assert payload["id"] in {m["id"] for m in response.json()["messages"]}


def test_websocket_receives_new_message(client, device):
    with client.websocket_connect(f"/ws/messages?token={ADMIN_KEY}") as websocket:
        websocket.send_json({"type": "ping"})
        assert websocket.receive_json() == {"type": "pong"}

        payload = make_message(body="pushed over websocket")
        client.post("/api/v1/messages", json=payload, headers=device["headers"])

        for _ in range(10):
            frame = websocket.receive_json()
            if frame["type"] == "message.new" and frame["data"]["id"] == payload["id"]:
                break
        else:  # pragma: no cover - fails the test with context
            raise AssertionError("message.new frame was not delivered")


def test_websocket_rejects_bad_token(client):
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws/messages?token=tsn_key_bogus") as websocket:
            websocket.receive_json()


# --- keys, events, stats --------------------------------------------------


def test_key_lifecycle(client, admin_headers):
    created = client.post(
        "/api/v1/keys", json={"name": "integration", "scope": "user"}, headers=admin_headers
    )
    assert created.status_code == 201
    key = created.json()
    assert key["key"].startswith("tsn_key_")

    headers = {"Authorization": f"Bearer {key['key']}"}
    assert client.get("/api/v1/messages", headers=headers).status_code == 200

    assert client.delete(f"/api/v1/keys/{key['id']}", headers=admin_headers).status_code == 204
    assert client.get("/api/v1/messages", headers=headers).status_code == 401

    listed = client.get("/api/v1/keys", headers=admin_headers).json()["keys"]
    entry = next(k for k in listed if k["id"] == key["id"])
    assert entry["revoked_at"] is not None
    assert "key" not in entry


def test_events_records_ingestion(client, device, admin_headers):
    client.post("/api/v1/messages", json=make_message(body="event probe"), headers=device["headers"])

    response = client.get("/api/v1/events", params={"type": "MSG_RECV"}, headers=admin_headers)
    assert response.status_code == 200
    events = response.json()["events"]
    assert events, "expected at least one MSG_RECV event"
    assert all(event["type"] == "MSG_RECV" for event in events)
    assert events[0]["payload"]["device_id"] == device["id"]


def test_events_level_filter_is_validated(client, admin_headers):
    assert (
        client.get("/api/v1/events", params={"level": "chatty"}, headers=admin_headers).status_code
        == 422
    )


def test_volume_returns_a_continuous_series(client, device, user_headers):
    client.post("/api/v1/messages", json=make_message(body="volume probe"), headers=device["headers"])

    response = client.get("/api/v1/stats/volume", params={"days": 7}, headers=user_headers)
    assert response.status_code == 200
    body = response.json()

    assert body["days"] == 7
    assert len(body["points"]) == 7, "empty days must still be present for a continuous axis"
    dates = [point["date"] for point in body["points"]]
    assert dates == sorted(dates)
    assert body["points"][-1]["date"] == datetime.now(UTC).date().isoformat()
    assert body["points"][-1]["count"] >= 1


def test_volume_rejects_out_of_range_windows(client, user_headers):
    assert (
        client.get("/api/v1/stats/volume", params={"days": 0}, headers=user_headers).status_code
        == 422
    )
    assert (
        client.get("/api/v1/stats/volume", params={"days": 500}, headers=user_headers).status_code
        == 422
    )


def test_stats_counts_messages(client, device, user_headers):
    before = client.get("/api/v1/stats", headers=user_headers).json()
    client.post("/api/v1/messages", json=make_message(body="stat probe"), headers=device["headers"])
    after = client.get("/api/v1/stats", headers=user_headers).json()

    assert after["messages_total"] == before["messages_total"] + 1
    assert after["messages_today"] >= 1
    assert after["active_devices"] >= 1
    assert after["storage_bytes"] > before["storage_bytes"]
