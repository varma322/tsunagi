#!/usr/bin/env python3
"""End-to-end check against a running Tsunagi server.

Walks the same path the Android app takes -- register a device, upload a batch,
read it back -- so a deployment can be verified without a phone.

    python scripts/smoke_test.py --url http://127.0.0.1:8000 --api-key <admin key>

Deliberately uses only the standard library: this runs on freshly provisioned
servers where the virtualenv holds production dependencies and nothing else.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import UTC, datetime, timedelta

PASS = "PASS"
FAIL = "FAIL"

# Identify the tool explicitly. urllib's default User-Agent is "Python-urllib/x.y",
# which Cloudflare's browser-integrity check rejects outright with error 1010 —
# so against a proxied domain every request would 403 before reaching the server.
USER_AGENT = "Tsunagi-SmokeTest/1.0.0"


def request(
    method: str,
    url: str,
    headers: dict[str, str] | None = None,
    payload: object | None = None,
    timeout: float = 20.0,
    raw: bool = False,
) -> tuple[int, object]:
    """Returns (status, parsed body). Status 0 means the server was unreachable.

    `raw` returns the body as text instead of parsing it, for the endpoints that
    do not answer in JSON — the CSV export being the only one today.
    """
    body = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=body, method=method)
    req.add_header("Content-Type", "application/json")
    req.add_header("User-Agent", USER_AGENT)
    for key, value in (headers or {}).items():
        req.add_header(key, value)

    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            text = response.read().decode("utf-8")
            if raw:
                return response.status, text
            return response.status, (json.loads(text) if text else None)
    except urllib.error.HTTPError as error:
        text = error.read().decode("utf-8", "replace")
        try:
            return error.code, (json.loads(text) if text else None)
        except ValueError:
            return error.code, text
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        return 0, str(error)


def query(base: str, path: str, params: dict[str, object] | None = None) -> str:
    url = f"{base}{path}"
    if params:
        clean = {k: str(v) for k, v in params.items() if v is not None}
        if clean:
            url = f"{url}?{urllib.parse.urlencode(clean)}"
    return url


class Checks:
    def __init__(self) -> None:
        self.failures = 0

    def record(self, name: str, ok: bool, detail: str = "") -> None:
        status = PASS if ok else FAIL
        suffix = f" - {detail}" if detail else ""
        print(f"[{status}] {name}{suffix}")
        if not ok:
            self.failures += 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8000", help="Base server URL")
    parser.add_argument("--api-key", required=True, help="API key with admin scope")
    parser.add_argument(
        "--setup-key",
        help="Legacy TSUNAGI_SETUP_KEY. Omit it and the script issues a single-use "
        "enrolment code instead, which is the default enrolment path.",
    )
    parser.add_argument("--timeout", type=float, default=20.0)
    args = parser.parse_args()

    base = args.url.rstrip("/")
    checks = Checks()
    reader = {"Authorization": f"Bearer {args.api_key}"}

    status, body = request("GET", f"{base}/health", timeout=args.timeout)
    checks.record("health", status == 200, f"HTTP {status}" if status else str(body))
    if status != 200:
        print("\nServer is not reachable; aborting.")
        return 1

    # --- enrolment --------------------------------------------------------
    if args.setup_key:
        credential, enrolment_id = args.setup_key, None
    else:
        status, body = request(
            "POST", f"{base}/api/v1/enrolments", reader, {"label": "smoke-test"}
        )
        checks.record("issue enrolment code", status == 201, f"HTTP {status}")
        if status != 201:
            print("\nAn admin API key is required to issue enrolment codes.")
            return 1
        credential, enrolment_id = body["code"], body["id"]

    device_auth = {"Authorization": f"Bearer {credential}"}
    status, device = request(
        "POST",
        f"{base}/api/v1/devices/register",
        device_auth,
        {"device_name": f"smoke-test-{uuid.uuid4().hex[:6]}"},
    )
    checks.record("register device", status == 201, f"HTTP {status}")
    if status != 201:
        return 1

    checks.record("device token format", str(device["token"]).startswith("tsn_dev_"))

    if enrolment_id is not None:
        status, _ = request(
            "POST",
            f"{base}/api/v1/devices/register",
            device_auth,
            {"device_name": "should-not-exist"},
        )
        checks.record("enrolment code cannot be reused", status == 403, f"HTTP {status}")

    device_headers = {"Authorization": f"Bearer {device['token']}"}

    # --- ingestion --------------------------------------------------------
    needle = f"smoke-{uuid.uuid4().hex[:10]}"
    sent_at = (datetime.now(UTC) - timedelta(seconds=5)).isoformat()
    messages = [
        {
            "id": str(uuid.uuid4()),
            "sender": "+15550001111",
            "body": f"verification {needle}",
            "received_at": sent_at,
        },
        {
            "id": str(uuid.uuid4()),
            "sender": "+15550002222",
            "body": "second message",
            "received_at": sent_at,
        },
    ]

    status, body = request(
        "POST", f"{base}/api/v1/messages/batch", device_headers, {"messages": messages}
    )
    checks.record("batch upload", status == 200, f"HTTP {status}")
    if status == 200:
        checks.record("batch created both messages", body.get("created") == 2, str(body))

    status, body = request(
        "POST", f"{base}/api/v1/messages/batch", device_headers, {"messages": messages}
    )
    checks.record(
        "replayed batch is deduplicated",
        status == 200 and body.get("duplicates") == 2,
        str(body if status == 200 else status),
    )

    # --- reading ----------------------------------------------------------
    status, body = request(
        "GET", query(base, "/api/v1/messages", {"device_id": device["device_id"]}), reader
    )
    checks.record(
        "list messages for device",
        status == 200 and body.get("total") == 2,
        f"HTTP {status}",
    )

    status, body = request("GET", query(base, "/api/v1/messages/search", {"query": needle}), reader)
    checks.record(
        "search finds uploaded message",
        status == 200 and body.get("total") == 1,
        f"HTTP {status}",
    )

    status, body = request("GET", f"{base}/api/v1/devices", reader)
    online = False
    if status == 200:
        entry = next((d for d in body["devices"] if d["id"] == device["device_id"]), None)
        online = bool(entry and entry["status"])
    checks.record("device reports online", online, f"HTTP {status}")

    # --- partial batches --------------------------------------------------
    # One unacceptable message used to reject every message it travelled with.
    # Sent the way the phone sends it, so a rename on either side shows up here
    # rather than on someone's phone.
    good = {
        "id": str(uuid.uuid4()),
        "sender": "+15550003333",
        "body": "survives a bad neighbour",
        "received_at": sent_at,
    }
    offender = {"id": str(uuid.uuid4()), "sender": "", "body": "no sender", "received_at": sent_at}

    status, body = request(
        "POST",
        f"{base}/api/v1/messages/batch",
        device_headers,
        {"messages": [good, offender], "partial": True},
    )
    results = body.get("results") or [] if status == 200 else []
    checks.record(
        "a batch with one bad message stores the good one",
        status == 200 and body.get("created") == 1 and body.get("rejected") == 1,
        f"HTTP {status}: {body}",
    )
    checks.record(
        "the refused message is named",
        len(results) == 2
        and results[0]["status"] == "created"
        and results[1]["status"] == "rejected"
        and results[1]["id"] == offender["id"],
        str(results),
    )

    status, body = request(
        "POST",
        f"{base}/api/v1/messages/batch",
        device_headers,
        {"messages": [{**good, "id": str(uuid.uuid4())}, offender]},
    )
    checks.record(
        "without opting in, one bad message still rejects the batch",
        status == 422,
        f"HTTP {status}",
    )

    # --- export -----------------------------------------------------------
    # Worth checking through a real deployment rather than only in tests: the
    # export streams, and a reverse proxy sits between it and the client.
    status, body = request(
        "GET",
        query(base, "/api/v1/messages/export", {"device_id": device["device_id"]}),
        reader,
        raw=True,
    )
    lines = [line for line in (body or "").splitlines() if line.strip()]
    checks.record(
        "csv export returns a header and every message",
        status == 200 and lines and lines[0].startswith("id,device_id,sender") and len(lines) >= 3,
        f"HTTP {status}, {len(lines)} line(s)",
    )

    status, body = request(
        "GET",
        query(base, "/api/v1/messages/export", {"device_id": device["device_id"], "format": "json"}),
        reader,
    )
    checks.record(
        "json export parses",
        status == 200 and isinstance(body.get("messages"), list) and len(body["messages"]) >= 2,
        f"HTTP {status}",
    )

    # --- capture health ---------------------------------------------------
    # Sent exactly as the phone sends it. A field renamed on one side and not
    # the other is a 422 that would otherwise only appear on someone's phone.
    status, _ = request(
        "POST",
        f"{base}/api/v1/devices/checkin",
        device_headers,
        {
            "capture_permitted": True,
            "inbox_readable": True,
            "battery_exempt": False,
            "last_captured_at": sent_at,
            "last_swept_at": sent_at,
        },
    )
    checks.record("device reports capture health", status == 200, f"HTTP {status}")

    status, body = request("GET", f"{base}/api/v1/devices", reader)
    entry = None
    if status == 200:
        entry = next((d for d in body["devices"] if d["id"] == device["device_id"]), None)
    checks.record(
        "a healthy phone reads as capturing",
        bool(entry and entry.get("capture") == "ok"),
        str(entry.get("capture") if entry else f"HTTP {status}"),
    )

    status, _ = request(
        "POST",
        f"{base}/api/v1/devices/checkin",
        device_headers,
        {
            "capture_permitted": False,
            "inbox_readable": True,
            "battery_exempt": False,
            "last_captured_at": sent_at,
            "last_swept_at": sent_at,
        },
    )
    entry = None
    if status == 200:
        _, body = request("GET", f"{base}/api/v1/devices", reader)
        entry = next((d for d in body["devices"] if d["id"] == device["device_id"]), None)
    checks.record(
        "a phone that lost SMS permission reads as blocked",
        bool(entry and entry.get("capture") == "blocked"),
        str(entry.get("capture") if entry else f"HTTP {status}"),
    )

    status, body = request("GET", query(base, "/api/v1/events", {"type": "MSG_RECV"}), reader)
    checks.record(
        "events recorded ingestion",
        status == 200 and len(body["events"]) >= 2,
        f"HTTP {status}",
    )

    status, body = request("GET", f"{base}/api/v1/stats", reader)
    checks.record(
        "stats reachable",
        status == 200 and body.get("messages_total", 0) >= 2,
        f"HTTP {status}",
    )

    # --- webhooks ---------------------------------------------------------
    # Pointed at the deployment's own nginx, which answers POST /health with a
    # 405. That is the point: a status back means a real request left this
    # server and reached another one, which no unit test can show.
    status, created = request(
        "POST",
        f"{base}/api/v1/webhooks",
        reader,
        {"url": "http://nginx/health", "description": "smoke test", "events": ["message.new"]},
    )
    checks.record("register a webhook", status == 201, f"HTTP {status}")
    checks.record(
        "the signing secret is revealed once",
        status == 201 and bool(created.get("secret")),
        # The detail prints on a pass too, so it has to read as a fact rather
        # than as the complaint it would be on a failure.
        f"HTTP {status}",
    )

    if status == 201:
        hook_id = created["id"]
        status, listed = request("GET", f"{base}/api/v1/webhooks", reader)
        mine = next(
            (w for w in (listed or {}).get("webhooks", []) if w["id"] == hook_id), None
        )
        checks.record(
            "the secret is not listed afterwards",
            mine is not None and "secret" not in mine,
            str(mine),
        )

        status, result = request("POST", f"{base}/api/v1/webhooks/{hook_id}/test", reader)
        checks.record(
            "a test delivery reaches a real endpoint",
            status == 200 and result.get("status") is not None,
            f"HTTP {status}: {result}",
        )

        status, _ = request("DELETE", f"{base}/api/v1/webhooks/{hook_id}", reader)
        checks.record("delete a webhook", status == 204, f"HTTP {status}")

    # --- authorization ----------------------------------------------------
    status, _ = request("GET", f"{base}/api/v1/messages")
    checks.record("unauthenticated read is rejected", status == 401, f"HTTP {status}")

    status, _ = request("GET", f"{base}/api/v1/messages", device_headers)
    checks.record("device token cannot read messages", status == 403, f"HTTP {status}")

    print()
    if checks.failures:
        print(f"{checks.failures} check(s) failed.")
        return 1
    print("All checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
