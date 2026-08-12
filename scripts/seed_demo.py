#!/usr/bin/env python3
"""Populate a Tsunagi server with plausible demo data.

Useful for exercising the dashboard layouts without waiting for a real phone to
accumulate traffic. Point it at a throwaway database, never a live one.

    python scripts/seed_demo.py --url http://127.0.0.1:8100 --api-key tsn_key_demo-admin
"""

from __future__ import annotations

import argparse
import random
import sys
import uuid
from datetime import UTC, datetime, timedelta

import httpx

SENDERS = [
    "+15550192834",
    "+447700900077",
    "+15550129981",
    "VERIFY",
    "SystemAlert",
]

BODIES = [
    "Your verification code is {code}",
    "Payment received for invoice #{code}",
    "Reminder: your appointment is at 14:30 tomorrow",
    "Server CPU usage exceeded 90% on node-{code}",
    "Your one-time passcode is {code}. Do not share it.",
    "Delivery scheduled for today between 9am and 12pm",
    "Low balance alert: your account is below the threshold",
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8100")
    parser.add_argument("--api-key", required=True, help="API key with admin scope")
    parser.add_argument("--setup-key", help="Legacy TSUNAGI_SETUP_KEY, if one is configured")
    parser.add_argument("--devices", type=int, default=2)
    parser.add_argument("--messages", type=int, default=48)
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()

    random.seed(args.seed)
    base = args.url.rstrip("/")

    with httpx.Client(base_url=base, timeout=30.0) as client:
        admin = {"Authorization": f"Bearer {args.api_key}"}

        devices = []
        for name in ("Pixel 7 Pro", "Office Phone", "Spare Handset")[: args.devices]:
            if args.setup_key:
                credential = args.setup_key
            else:
                # Default path: one single-use code per device.
                issued = client.post("/api/v1/enrolments", headers=admin, json={"label": name})
                issued.raise_for_status()
                credential = issued.json()["code"]

            response = client.post(
                "/api/v1/devices/register",
                headers={"Authorization": f"Bearer {credential}"},
                json={"device_name": name},
            )
            response.raise_for_status()
            devices.append(response.json())
            print(f"registered {name}")

        now = datetime.now(UTC)
        payloads: dict[str, list[dict]] = {device["device_id"]: [] for device in devices}

        for _ in range(args.messages):
            device = random.choice(devices)
            # Weight recent days more heavily so the volume chart has shape.
            day_offset = random.choices(
                range(args.days), weights=[i + 1 for i in range(args.days)]
            )[0]
            received = now - timedelta(
                days=args.days - 1 - day_offset,
                hours=random.randint(0, 23),
                minutes=random.randint(0, 59),
            )
            code = random.randint(100000, 999999)
            payloads[device["device_id"]].append(
                {
                    "id": str(uuid.uuid4()),
                    "sender": random.choice(SENDERS),
                    "body": random.choice(BODIES).format(code=code),
                    "received_at": received.isoformat(),
                }
            )

        for device in devices:
            batch = payloads[device["device_id"]]
            if not batch:
                continue
            response = client.post(
                "/api/v1/messages/batch",
                headers={"Authorization": f"Bearer {device['token']}"},
                json={"messages": batch},
            )
            response.raise_for_status()
            print(f"uploaded {len(batch)} messages from {device['device_id'][:8]}")

        for name, scope in (("dashboard-readonly", "user"), ("home-automation", "user")):
            client.post("/api/v1/keys", headers=admin, json={"name": name, "scope": scope})

        # A revoked key so the list shows both states.
        revoked = client.post(
            "/api/v1/keys", headers=admin, json={"name": "legacy-integration", "scope": "user"}
        ).json()
        client.delete(f"/api/v1/keys/{revoked['id']}", headers=admin)

        stats = client.get("/api/v1/stats", headers=admin).json()
        print(f"done: {stats}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
