# Tsunagi — ROADMAP.md

Tsunagi is an open-source, self-hosted SMS synchronization platform. This roadmap
tracks the path to a complete v1.0 release and beyond. See
[Tsunagi_IMPLEMENTATION.md](Tsunagi_IMPLEMENTATION.md) for the original design,
[ARCHITECTURE.md](ARCHITECTURE.md) for system structure,
[API_SPEC.md](API_SPEC.md) for the API contract, and
[DATABASE_SCHEMA.md](DATABASE_SCHEMA.md) for storage design.

---

## Current Status

**v1.0.0 is released.** All five milestones are complete: an SMS captured on an
Android device is stored locally, uploaded to the server, persisted, and visible
in the web dashboard in real time — over TLS, with rate limiting, a local
retention policy, admin/read-only roles, and single-use device enrolment.

- [x] Android app: SMS capture, Room storage, WorkManager sync, settings UI
- [x] Backend: FastAPI + SQLAlchemy + Alembic, all v1 endpoints, WebSocket
- [x] React dashboard: all seven screens, live updates, responsive
- [x] Docker Compose deployment (nginx, frontend, api, postgres, redis)
- [x] Frontend design mockups in [tmp/frontend/](tmp/frontend/), built on the
      Tsunagi Core design system
      ([DESIGN.md](tmp/frontend/tsunagi_core/DESIGN.md))
- [x] TLS guide, CONTRIBUTING, and v1.0 release

Since v1.0, capture has been reworked so a message the SMS broadcast never
delivers is recovered rather than lost — see the unreleased section of
[CHANGELOG.md](CHANGELOG.md) and **Capture reliability** under Known Gaps.

Verification currently in place: 79 backend tests (`cd backend && pytest`),
36 Android unit tests (`gradlew :app:testDebugUnitTest`), a frontend typecheck
(`npm run typecheck`), and [scripts/smoke_test.py](scripts/smoke_test.py), which
walks the full register → upload → read path against any running server.
[scripts/seed_demo.py](scripts/seed_demo.py) populates a throwaway database for
exercising the dashboard.

---

## Phase 1 — MVP (v1.0)

### Milestone 1 — Foundations ✅

**Android**
- [x] `RECEIVE_SMS` / `READ_SMS` permissions with an in-app request flow
- [x] SMS `BroadcastReceiver` capturing sender, body, and received-at, with
      multipart SMS reassembly
- [x] Room database: `DeviceEntity`, `MessageEntity` with `sync_status`
- [x] Repository layer over Room (MVVM + repository pattern)

**Backend**
- [x] FastAPI skeleton with Pydantic schemas and auto-generated OpenAPI docs
- [x] Async SQLAlchemy over PostgreSQL, with SQLite for local development
- [x] Alembic migration `0001` creating `devices`, `messages`, `api_keys`

### Milestone 2 — Synchronization ✅

**Android**
- [x] Retrofit client with a user-configurable server URL
- [x] WorkManager sync engine: batched upload, exponential backoff, network
      constraint, periodic safety-net pass, recovery of interrupted uploads
- [x] Settings screen: server URL, device name, setup key, sync status, last
      sync time, live captured/synced/pending/failed counts

**Backend**
- [x] `POST /api/v1/devices/register` issuing device tokens
- [x] `POST /api/v1/messages` and `/messages/batch`, idempotent by client UUID
- [x] Bearer-token authentication with device / user / admin scopes
- [x] `last_seen` tracking and derived online status

### Milestone 3 — Read APIs & Inbox ✅

**Backend**
- [x] `GET /api/v1/messages` with `limit`, `offset`, `sender`, `device_id`,
      `after`, `before`
- [x] `GET /api/v1/messages/search` (PostgreSQL full-text, `LIKE` on SQLite)
- [x] API key management: create, list, revoke

**Frontend**
- [x] React + Vite + Tailwind v4, with Tsunagi Core as theme tokens
- [x] Landing page and an API-key Connect screen
- [x] Messages page: debounced full-text search, sender and device filters,
      filter chips, pagination
- [x] API key management UI: create with scope, reveal once, revoke

### Milestone 4 — Real-Time Delivery ✅

**Backend**
- [x] Event bus with Redis pub/sub, falling back to in-process for single-worker
      deployments
- [x] `GET /api/v1/messages/wait` long-polling
- [x] `/ws/messages` WebSocket: `message.new`, `device.status`, `sync.event`,
      `system.event`
- [x] `GET /api/v1/events` backlog for the dashboard's Events page
- [x] `GET /api/v1/stats/volume` daily counts for the dashboard chart

**Frontend**
- [x] Live dashboard updates over a reconnecting WebSocket
- [x] Devices page with derived online status and revocation
- [x] Dashboard overview: stat tiles, volume chart, recent messages, devices
- [x] Events page: live log with level filter, pause, and clear
- [x] Responsive layouts — sidebar on desktop, bottom navigation on mobile

### Milestone 5 — Multi-Device & Release ✅

- [x] Multiple registered devices per server; per-device API filtering
- [x] Aggregated multi-device inbox with a per-device filter
- [x] Docker Compose deployment: `nginx`, `frontend`, `api`, `postgres`, `redis`
- [x] HTTPS/TLS setup guide and compose overlay
      ([deployment/TLS.md](deployment/TLS.md))
- [x] [CONTRIBUTING.md](CONTRIBUTING.md)
- [x] Rate limiting on the API
- [x] Retention policy for locally stored messages on the phone
- [x] Single-use enrolment codes replacing the shared setup key
- [x] Admin / read-only roles enforced server-side and reflected in the dashboard
- [x] **Release v1.0** 🎉

### v1.0 Success Criteria

1. ✅ An Android device can capture SMS and store them locally.
2. ✅ Messages synchronize reliably to the server.
3. ✅ Messages are persisted in PostgreSQL.
4. ✅ APIs return synchronized messages (list, search, wait).
5. ✅ The dashboard displays messages in real time.
6. ✅ Docker deployment works end-to-end.
7. ✅ Documentation is complete.

**All seven criteria are met. v1.0.0 is released** — see
[CHANGELOG.md](CHANGELOG.md), and [RELEASING.md](RELEASING.md) for how to cut
the next one.

---

## Known Gaps

Things that work but are not yet production-hardened.

### Capture reliability

The first principle below is "never lose a message", and until recently the app
did not meet it. Capture depended entirely on the live `SMS_RECEIVED` broadcast,
which the platform does not guarantee: none is delivered while the app sits in
the stopped state — where a force-stop or a vendor battery manager can park it,
with no callback and nothing in the log — and one can be lost to process death
between delivery and the database write. Neither is detectable from inside the
receiver, so a missed message left no trace anywhere.

Every sync pass now sweeps the platform SMS inbox and stores what is missing,
which turns any missed broadcast into a delay rather than a loss, and the app
offers to exempt itself from battery optimization to prevent the miss in the
first place. What remains open:

- **The sweep has not been verified against a real SMS provider.** Its logic is
  unit-tested against a fake inbox; the `ContentResolver` query itself has only
  been exercised by hand.
- **A phone that has stopped capturing still reports healthy.** The heartbeat
  proves the app can reach the server, not that it can still receive SMS, so a
  permanently broken device looks identical to a quiet one on the dashboard.
- **Batch upload is all-or-nothing server-side.** One message that fails
  validation rejects the whole request. The Android client isolates and
  quarantines the offender so this no longer blocks the queue, but the endpoint
  could report per-message results instead.

### Testing

- **No automated end-to-end test of the Android app against a live server.**
  The sync engine is unit-tested with fakes and verified by hand on a device;
  an instrumented test would close the gap. `app/src/androidTest/` currently
  holds only the generated example, so the Room queries added for the inbox
  sweep have never run against real SQLite.
- **`GET /api/v1/me` has no backend test.** It is what lets an idle device
  report that it is still alive, and nothing under `backend/tests/` exercises
  it.

### Everything else

- **Event log is capped and transient.** Suitable for the dashboard's live view,
  not for auditing. Deliberate — durable audit logging is a Phase 2 feature.
- **Rate limiting uses a fixed window.** A client can send up to double the
  limit across a window boundary. Acceptable for bounding abuse; a sliding
  window would be needed for precise traffic shaping.
- **Enrolment codes are ~39 bits.** Safe because they are single-use and expire
  in minutes, and the API is rate limited — but they would be weak as a
  long-lived credential, so do not extend their TTL to days.
- **R8/minification is disabled for the Android release build**
  (`app/build.gradle.kts`). Enabling it needs keep rules for the Retrofit and
  kotlinx-serialization models.

The v1.0 hardening items are closed: rate limiting
([`app/ratelimit.py`](backend/app/ratelimit.py)), local retention on the phone,
TLS deployment ([deployment/TLS.md](deployment/TLS.md)), and the shared setup
key, now replaced by single-use enrolment codes.

---

## Phase 2 — Post-v1.0 (candidates, unscheduled)

Explicit **non-goals for the MVP**, revisited after v1.0:

- MMS support
- Message **sending** from the dashboard/API
- Desktop client, browser extension
- Multi-user organizations / role-based access
- Contact synchronization
- End-to-end encryption of message bodies at rest
- Webhooks for third-party integrations
- Export / backup tooling (JSON, CSV)

---

## Guiding Principles

- **Reliability over features** — the MVP does one thing well: never lose a message.
- **Self-hosting first** — everything runs from a single `docker compose up`.
- **PostgreSQL is the source of truth** — Redis is transient (events only).
- **Open APIs** — every dashboard feature is available through a documented,
  token-authenticated HTTP API.
