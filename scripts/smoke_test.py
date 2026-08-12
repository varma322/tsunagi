#!/usr/bin/env python3
"""End-to-end check against a running Tsunagi server.

Walks the same path the Android app takes -- register a device, upload a batch,
read it back -- so a deployment can be verified without a phone.

    python scripts/smoke_test.py --url http://127.0.0.1:8000 --api-key <admin key>
"""

from __future__ import annotations

import argparse
import sys
import uuid
from datetime import UTC, datetime, timedelta

import httpx

PASS = "PASS"
FAIL = "FAIL"


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
    parser.add_argument("--timeout", type=float, default=15.0)
    args = parser.parse_args()

    base = args.url.rstrip("/")
    checks = Checks()

    with httpx.Client(base_url=base, timeout=args.timeout) as client:
        health = client.get("/health")
        checks.record("health", health.status_code == 200, f"HTTP {health.status_code}")
        if health.status_code != 200:
            print("\nServer is not reachable; aborting.")
            return 1

        reader = {"Authorization": f"Bearer {args.api_key}"}

        if args.setup_key:
            enrolment_credential = args.setup_key
            enrolment_id = None
        else:
            issued = client.post(
                "/api/v1/enrolments", headers=reader, json={"label": "smoke-test"}
            )
            checks.record(
                "issue enrolment code", issued.status_code == 201, f"HTTP {issued.status_code}"
            )
            if issued.status_code != 201:
                print("\nAn admin API key is required to issue enrolment codes.")
                return 1
            enrolment_credential = issued.json()["code"]
            enrolment_id = issued.json()["id"]

        registration = client.post(
            "/api/v1/devices/register",
            headers={"Authorization": f"Bearer {enrolment_credential}"},
            json={"device_name": f"smoke-test-{uuid.uuid4().hex[:6]}"},
        )
        checks.record(
            "register device",
            registration.status_code == 201,
            f"HTTP {registration.status_code}",
        )
        if registration.status_code != 201:
            return 1

        if enrolment_id is not None:
            replay = client.post(
                "/api/v1/devices/register",
                headers={"Authorization": f"Bearer {enrolment_credential}"},
                json={"device_name": "should-not-exist"},
            )
            checks.record(
                "enrolment code cannot be reused",
                replay.status_code == 403,
                f"HTTP {replay.status_code}",
            )

        device = registration.json()
        device_headers = {"Authorization": f"Bearer {device['token']}"}
        checks.record("device token format", device["token"].startswith("tsn_dev_"))

        needle = f"smoke-{uuid.uuid4().hex[:10]}"
        sent_at = datetime.now(UTC) - timedelta(seconds=5)
        payload = [
            {
                "id": str(uuid.uuid4()),
                "sender": "+15550001111",
                "body": f"verification {needle}",
                "received_at": sent_at.isoformat(),
            },
            {
                "id": str(uuid.uuid4()),
                "sender": "+15550002222",
                "body": "second message",
                "received_at": sent_at.isoformat(),
            },
        ]

        batch = client.post(
            "/api/v1/messages/batch", headers=device_headers, json={"messages": payload}
        )
        checks.record("batch upload", batch.status_code == 200, f"HTTP {batch.status_code}")
        if batch.status_code == 200:
            body = batch.json()
            checks.record("batch created both messages", body.get("created") == 2, str(body))

        replay = client.post(
            "/api/v1/messages/batch", headers=device_headers, json={"messages": payload}
        )
        checks.record(
            "replayed batch is deduplicated",
            replay.status_code == 200 and replay.json().get("duplicates") == 2,
            str(replay.json() if replay.status_code == 200 else replay.status_code),
        )

        listing = client.get(
            "/api/v1/messages", headers=reader, params={"device_id": device["device_id"]}
        )
        checks.record(
            "list messages for device",
            listing.status_code == 200 and listing.json().get("total") == 2,
            f"HTTP {listing.status_code}",
        )

        search = client.get("/api/v1/messages/search", headers=reader, params={"query": needle})
        checks.record(
            "search finds uploaded message",
            search.status_code == 200 and search.json().get("total") == 1,
            f"HTTP {search.status_code}",
        )

        devices = client.get("/api/v1/devices", headers=reader)
        online = False
        if devices.status_code == 200:
            entry = next(
                (d for d in devices.json()["devices"] if d["id"] == device["device_id"]), None
            )
            online = bool(entry and entry["status"])
        checks.record("device reports online", online, f"HTTP {devices.status_code}")

        events = client.get("/api/v1/events", headers=reader, params={"type": "MSG_RECV"})
        checks.record(
            "events recorded ingestion",
            events.status_code == 200 and len(events.json()["events"]) >= 2,
            f"HTTP {events.status_code}",
        )

        stats = client.get("/api/v1/stats", headers=reader)
        checks.record(
            "stats reachable",
            stats.status_code == 200 and stats.json()["messages_total"] >= 2,
            f"HTTP {stats.status_code}",
        )

        unauthorized = client.get("/api/v1/messages")
        checks.record("unauthenticated read is rejected", unauthorized.status_code == 401)

        wrong_scope = client.get("/api/v1/messages", headers=device_headers)
        checks.record("device token cannot read messages", wrong_scope.status_code == 403)

    print()
    if checks.failures:
        print(f"{checks.failures} check(s) failed.")
        return 1
    print("All checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
