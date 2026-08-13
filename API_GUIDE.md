# Tsunagi API — integration guide

Practical guide for using a Tsunagi server's API. For the complete endpoint
reference see [API_SPEC.md](API_SPEC.md); this is the getting-started version,
with examples verified against a live deployment.

**Base URL:** `https://sms.allbluesourcing.com`
**Interactive docs:** `https://sms.allbluesourcing.com/docs`

---

## 1. Authentication

Every request carries an API key as a bearer token:

```
Authorization: Bearer tsn_key_xxxxxxxxxxxxxxxxxxxx
```

Confirm your key works and see what it can do:

```bash
curl -H "Authorization: Bearer $KEY" https://sms.allbluesourcing.com/api/v1/me
```

```json
{ "kind": "key", "scope": "user", "name": "friend-api", "id": "…" }
```

### ⚠️ Set a User-Agent

The domain sits behind Cloudflare, whose bot check **rejects default library
agents**. `Python-urllib/3.x` gets a hard `403` with error 1010 before the
request ever reaches the server. `curl` and `okhttp` pass.

Always send something identifiable:

```python
headers = {"Authorization": f"Bearer {KEY}", "User-Agent": "my-integration/1.0"}
```

If you see an unexplained 403 with an HTML body, this is why — not your key.

---

## 2. What a `user` key can and cannot do

| | |
|---|---|
| ✅ Read messages, search, long-poll | `/api/v1/messages*` |
| ✅ Live feed | `/ws/messages` |
| ✅ List devices | `/api/v1/devices` |
| ✅ Statistics | `/api/v1/stats`, `/api/v1/stats/volume` |
| ❌ Manage API keys | `403` |
| ❌ Read the events log | `403` |
| ❌ Enrol a phone | `403` |
| ❌ Turn devices on/off | `403` |

A `user` key reads **all messages from all devices** — there is no per-sender or
per-device restriction.

**To enrol your own phone with the Android app you need an `admin` key**, or a
single-use enrolment code from whoever runs the server.

---

## 3. Reading messages

```bash
curl -H "Authorization: Bearer $KEY" \
  "https://sms.allbluesourcing.com/api/v1/messages?limit=20"
```

```json
{
  "total": 18,
  "limit": 20,
  "offset": 0,
  "messages": [
    {
      "id": "da296111-e80e-4455-9081-f3aef7a3a7ac",
      "device_id": "ddba0e57-ec36-4a28-88bf-1ad33a527235",
      "sender": "JD-SBIUPI-S",
      "body": "Dear UPI User, your A/c XXXXXX4525-credited by Rs.14980.00 …",
      "received_at": "2026-08-13T05:05:09Z",
      "created_at": "2026-08-13T05:05:12.475412Z"
    }
  ]
}
```

Ordered newest first. `received_at` is when the phone got the SMS;
`created_at` is when the server stored it — the gap is sync lag.

### Filters

| Parameter | Meaning |
|---|---|
| `limit` | page size, 1–200 (default 50) |
| `offset` | pagination offset |
| `sender` | exact sender match, e.g. `AD-AIRINF-T` |
| `device_id` | restrict to one phone |
| `after` / `before` | ISO-8601 bounds on `received_at` |

```bash
# Everything from Airtel in the last day
curl -H "Authorization: Bearer $KEY" \
  "https://sms.allbluesourcing.com/api/v1/messages?sender=AD-AIRINF-T&after=2026-08-12T00:00:00Z"
```

### Search

Full-text over message bodies:

```bash
curl -H "Authorization: Bearer $KEY" \
  "https://sms.allbluesourcing.com/api/v1/messages/search?query=OTP&limit=10"
```

Same response shape. Add `sender=` to narrow it.

---

## 4. Getting messages in real time

Two options. Pick by whether you can hold a connection open.

### WebSocket — push, lowest latency

```
wss://sms.allbluesourcing.com/ws/messages?token=YOUR_KEY
```

The key goes in the query string because browsers cannot set headers on a
WebSocket handshake.

```python
# pip install websockets
import asyncio, json, websockets

async def main():
    url = f"wss://sms.allbluesourcing.com/ws/messages?token={KEY}"
    async with websockets.connect(url, user_agent_header="my-integration/1.0") as ws:
        async for raw in ws:
            frame = json.loads(raw)
            if frame["type"] == "message.new":
                m = frame["data"]
                print(f"{m['sender']}: {m['body']}")

asyncio.run(main())
```

Frame types: `message.new`, `device.status`, `sync.event`, `system.event`.
Send `{"type":"ping"}` and you get `{"type":"pong"}` — useful as a keepalive.

**Delivery is best-effort.** After a reconnect, reconcile with
`GET /api/v1/messages?after=<last timestamp you saw>` rather than assuming you
missed nothing.

### Long polling — simpler, no persistent connection

```bash
curl -H "Authorization: Bearer $KEY" \
  "https://sms.allbluesourcing.com/api/v1/messages/wait?since=2026-08-13T05:00:00Z&timeout=30"
```

Blocks until a message arrives or `timeout` seconds pass (max 60), then returns
`{"messages": [...]}` — possibly empty. Loop it, carrying `since` forward.

`since` compares against **`created_at`** (server storage time), not
`received_at`. Storage time only moves forward, whereas a phone uploading a
backlog produces `received_at` values that jump backwards.

---

## 5. A complete polling example

```python
import time, json, urllib.request, urllib.parse
from datetime import datetime, timezone

BASE = "https://sms.allbluesourcing.com"
KEY  = "tsn_key_..."
HEADERS = {"Authorization": f"Bearer {KEY}", "User-Agent": "my-integration/1.0"}

def get(path, **params):
    url = f"{BASE}{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=70) as r:
        return json.load(r)

cursor = datetime.now(timezone.utc).isoformat()
while True:
    try:
        result = get("/api/v1/messages/wait", since=cursor, timeout=30)
        for m in result["messages"]:
            print(f"[{m['received_at']}] {m['sender']}: {m['body']}")
            cursor = m["created_at"]      # advance past what we handled
    except Exception as error:
        print("retrying:", error)
        time.sleep(5)
```

---

## 6. Devices and statistics

```bash
curl -H "Authorization: Bearer $KEY" https://sms.allbluesourcing.com/api/v1/devices
curl -H "Authorization: Bearer $KEY" https://sms.allbluesourcing.com/api/v1/stats
curl -H "Authorization: Bearer $KEY" "https://sms.allbluesourcing.com/api/v1/stats/volume?days=7"
```

`devices` returns `status` (online within the last 30 minutes) and `enabled`
(whether an admin switched it off). `volume` returns one entry per day
including zero days, so charts get a continuous axis.

---

## 7. Errors

Every non-2xx response uses the same envelope:

```json
{ "error": { "code": "unauthorized", "message": "Invalid or expired token." } }
```

| Status | Code | Usually means |
|---|---|---|
| 401 | `unauthorized` | key missing, wrong, or revoked |
| 403 | `forbidden` | key valid but lacks the scope |
| 422 | `validation_error` | bad parameter |
| 429 | `rate_limited` | slow down — see below |

An HTML body instead of JSON means Cloudflare blocked it before it reached the
server. Check your User-Agent.

---

## 8. Rate limits

240 requests per 60 seconds per key. Every response tells you where you stand:

```
x-ratelimit-limit: 240
x-ratelimit-remaining: 228
```

A `429` includes `Retry-After` in seconds. Long-polling and WebSockets do not
burn budget while waiting — a held-open request is one request, and WebSocket
connections are not counted at all.

---

## 9. Using the Android app

The APK captures SMS on a phone and uploads them to the server.

1. Install `app-release.apk` and **open it once** — Android delivers no
   broadcasts to a freshly installed app until it is launched manually, so
   messages arriving before that first launch are missed permanently.
2. Grant the SMS permission.
3. Enter the server URL `https://sms.allbluesourcing.com/`, a device name, and
   an **enrolment code**.
4. Save. It registers, discards the code, and starts syncing.

Enrolment codes are single-use and expire in 15 minutes. Generating one needs an
`admin` key (dashboard → Devices → Add a device), so ask the server owner for a
code, or for an admin key if you will be enrolling phones regularly.

The app only captures messages that arrive **after** it is running; it does not
import existing inbox history.

---

## 10. Notes

- Everything is read-only through this API. There is no way to send an SMS.
- Message IDs are UUIDs generated on the phone, stable across retries — safe to
  use as your own deduplication key.
- Timestamps are ISO-8601 UTC with a `Z` suffix.
- Keys can be revoked instantly by the server owner, and revocation takes effect
  on the next request.
