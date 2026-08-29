"""Outbound webhooks.

The delivery path is exercised against a real HTTP server on loopback rather
than a stubbed transport wherever it can be. Signing, the urllib transport and
the recording of what happened are exactly the parts a fake would agree with by
construction.
"""

import asyncio
import hashlib
import hmac
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from app.webhooks import Delivery, DeliveryResult, deliver, render, sign
from tests.conftest import make_message


class Receiver:
    """A webhook endpoint that records what it was sent."""

    def __init__(self, status: int = 200) -> None:
        self.received: list[dict] = []
        self.status = status
        self._server = HTTPServer(("127.0.0.1", 0), self._handler())
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    @property
    def url(self) -> str:
        host, port = self._server.server_address[:2]
        return f"http://{host}:{port}/hook"

    def _handler(self):
        receiver = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802 - BaseHTTPRequestHandler's spelling
                length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(length)
                receiver.received.append({"headers": dict(self.headers), "body": body})
                self.send_response(receiver.status)
                self.end_headers()
                self.wfile.write(b"{}")

            def log_message(self, *args):
                return

        return Handler

    def wait_for(self, count: int = 1, timeout: float = 10.0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if len(self.received) >= count:
                return True
            time.sleep(0.05)
        return False

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()


@pytest.fixture
def receiver():
    server = Receiver()
    try:
        yield server
    finally:
        server.close()


def create(client, admin_headers, url, **body):
    return client.post(
        "/api/v1/webhooks", json={"url": url, **body}, headers=admin_headers
    )


# --- registration ---------------------------------------------------------


def test_creating_a_webhook_reveals_the_secret_once(client, admin_headers):
    response = create(client, admin_headers, "https://example.com/hook", description="ticketing")

    assert response.status_code == 201
    body = response.json()
    assert body["secret"]
    assert body["events"] == ["message.new"]
    assert body["enabled"] is True

    listed = client.get("/api/v1/webhooks", headers=admin_headers).json()["webhooks"]
    mine = next(w for w in listed if w["id"] == body["id"])
    assert "secret" not in mine, "the secret must never appear again after creation"


def test_events_can_be_chosen(client, admin_headers):
    body = create(
        client, admin_headers, "https://example.com/hook", events=["device.status"]
    ).json()

    assert body["events"] == ["device.status"]


def test_an_unknown_event_is_refused(client, admin_headers):
    response = create(client, admin_headers, "https://example.com/h", events=["sync.event"])

    assert response.status_code == 422


def test_a_url_that_is_not_http_is_refused(client, admin_headers):
    assert create(client, admin_headers, "ftp://example.com/hook").status_code == 422


def test_webhooks_are_admin_only(client, user_headers, admin_headers):
    assert create(client, user_headers, "https://example.com/hook").status_code == 403
    assert client.get("/api/v1/webhooks", headers=user_headers).status_code == 403


def test_a_webhook_can_be_switched_off_and_on(client, admin_headers):
    created = create(client, admin_headers, "https://example.com/hook").json()

    off = client.post(
        f"/api/v1/webhooks/{created['id']}/enabled",
        json={"enabled": False},
        headers=admin_headers,
    )
    assert off.status_code == 200
    assert off.json()["enabled"] is False

    on = client.post(
        f"/api/v1/webhooks/{created['id']}/enabled",
        json={"enabled": True},
        headers=admin_headers,
    )
    assert on.json()["enabled"] is True


def test_a_deleted_webhook_is_gone(client, admin_headers):
    created = create(client, admin_headers, "https://example.com/hook").json()

    assert client.delete(f"/api/v1/webhooks/{created['id']}", headers=admin_headers).status_code == 204

    listed = client.get("/api/v1/webhooks", headers=admin_headers).json()["webhooks"]
    assert all(w["id"] != created["id"] for w in listed)


# --- signing --------------------------------------------------------------


def test_the_signature_covers_the_timestamp_as_well_as_the_body():
    """Signing the body alone would let anyone who captured one delivery replay
    it forever; the timestamp is what a receiver rejects on."""
    body = b'{"event":"message.new"}'
    expected = hmac.new(b"shh", b"1700000000." + body, hashlib.sha256).hexdigest()

    assert sign("shh", "1700000000", body) == f"sha256={expected}"


def test_a_different_timestamp_changes_the_signature():
    body = b"{}"

    assert sign("shh", "1", body) != sign("shh", "2", body)


def test_the_payload_names_its_event():
    payload = json.loads(render("message.new", {"id": "abc"}))

    assert payload["event"] == "message.new"
    assert payload["data"] == {"id": "abc"}
    assert payload["delivered_at"]


# --- delivery -------------------------------------------------------------


def attempt(url, **kwargs):
    delivery = Delivery(
        webhook_id=__import__("uuid").uuid4(),
        url=url,
        secret="shh",
        event="message.new",
        data={"id": "abc"},
    )
    return asyncio.run(deliver(delivery, **kwargs))


def test_a_delivery_arrives_signed(receiver):
    result = attempt(receiver.url)

    assert result.ok and result.status == 200
    assert receiver.wait_for(1)

    sent = receiver.received[0]
    timestamp = sent["headers"]["X-Tsunagi-Timestamp"]
    assert sent["headers"]["X-Tsunagi-Event"] == "message.new"
    assert sent["headers"]["X-Tsunagi-Signature"] == sign("shh", timestamp, sent["body"])
    assert json.loads(sent["body"])["data"] == {"id": "abc"}


def test_a_refusal_is_not_retried():
    """A 4xx is the receiver saying it understood and refused. Repeating it only
    costs both sides."""
    calls = []

    async def refusing(url, body, headers):
        calls.append(url)
        return DeliveryResult(ok=False, status=400, error="HTTP 400")

    result = attempt("https://example.com/h", transport=refusing, attempts=3, backoff=0)

    assert result.ok is False
    assert len(calls) == 1


def test_a_server_error_is_retried():
    calls = []

    async def flaky(url, body, headers):
        calls.append(url)
        return DeliveryResult(ok=True, status=200) if len(calls) == 3 else DeliveryResult(
            ok=False, status=503, error="HTTP 503"
        )

    result = attempt("https://example.com/h", transport=flaky, attempts=3, backoff=0)

    assert result.ok is True
    assert len(calls) == 3


def test_an_unreachable_endpoint_reports_rather_than_raises():
    # Nothing is listening on this port; the transport must turn that into a
    # result, since a raise here would kill the worker that called it.
    result = attempt("http://127.0.0.1:9/hook", attempts=1)

    assert result.ok is False
    assert result.error


# --- the test button ------------------------------------------------------


def test_a_test_delivery_reports_what_happened(client, admin_headers, receiver):
    created = create(client, admin_headers, receiver.url).json()

    response = client.post(f"/api/v1/webhooks/{created['id']}/test", headers=admin_headers)

    assert response.status_code == 200
    assert response.json() == {"delivered": True, "status": 200, "error": None}
    assert receiver.wait_for(1)
    assert json.loads(receiver.received[0]["body"])["event"] == "webhook.test"


def test_a_failed_test_is_reported_without_disabling_the_webhook(client, admin_headers):
    created = create(client, admin_headers, "http://127.0.0.1:9/hook").json()

    response = client.post(f"/api/v1/webhooks/{created['id']}/test", headers=admin_headers)

    assert response.json()["delivered"] is False
    listed = client.get("/api/v1/webhooks", headers=admin_headers).json()["webhooks"]
    mine = next(w for w in listed if w["id"] == created["id"])
    assert mine["enabled"] is True, "a test must never be what switches a webhook off"
    assert mine["last_error"]


def test_testing_an_unknown_webhook_is_a_404(client, admin_headers):
    missing = "00000000-0000-0000-0000-000000000000"

    assert client.post(f"/api/v1/webhooks/{missing}/test", headers=admin_headers).status_code == 404


# --- dispatch -------------------------------------------------------------


def test_an_arriving_message_reaches_a_subscribed_endpoint(
    client, admin_headers, device, receiver
):
    """End to end through the dispatcher: upload an SMS, and the endpoint gets a
    signed delivery without anyone polling for it."""
    created = create(client, admin_headers, receiver.url, events=["message.new"]).json()
    try:
        client.post("/api/v1/messages", json=make_message(body="webhook probe"), headers=device["headers"])

        assert receiver.wait_for(1), "the message never reached the webhook"
        payload = json.loads(receiver.received[0]["body"])
        assert payload["event"] == "message.new"
        assert payload["data"]["body"] == "webhook probe"
    finally:
        client.delete(f"/api/v1/webhooks/{created['id']}", headers=admin_headers)


def test_a_disabled_webhook_is_not_delivered_to(client, admin_headers, device, receiver):
    created = create(client, admin_headers, receiver.url).json()
    client.post(
        f"/api/v1/webhooks/{created['id']}/enabled",
        json={"enabled": False},
        headers=admin_headers,
    )
    try:
        client.post("/api/v1/messages", json=make_message(), headers=device["headers"])
        time.sleep(0.5)

        assert receiver.received == []
    finally:
        client.delete(f"/api/v1/webhooks/{created['id']}", headers=admin_headers)


def test_a_webhook_only_gets_the_events_it_asked_for(
    client, admin_headers, device, receiver
):
    """Subscribed to device.status only, so an arriving message is not its
    business. This is what the comma-wrapped match in the query is for."""
    created = create(client, admin_headers, receiver.url, events=["device.status"]).json()
    try:
        client.post("/api/v1/messages", json=make_message(), headers=device["headers"])
        time.sleep(0.5)

        assert receiver.received == []
    finally:
        client.delete(f"/api/v1/webhooks/{created['id']}", headers=admin_headers)
