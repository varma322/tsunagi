# Tsunagi — ARCHITECTURE.md

Tsunagi is an open-source, self-hosted SMS synchronization platform. It captures
SMS messages on Android devices, synchronizes them to a central server, and
exposes them through secure APIs, a WebSocket layer, and a web dashboard.

Related docs: [ROADMAP.md](ROADMAP.md) · [API_SPEC.md](API_SPEC.md) ·
[DATABASE_SCHEMA.md](DATABASE_SCHEMA.md) ·
[Tsunagi_IMPLEMENTATION.md](Tsunagi_IMPLEMENTATION.md)

---

## System Overview

```text
┌──────────────────┐
│  Android Device  │  (one or more)
│  ──────────────  │
│  SMS Receiver    │
│  Room DB         │
│  Sync Engine     │
└────────┬─────────┘
         │ HTTPS (Bearer token)
         v
┌──────────────────┐        ┌──────────────┐
│  FastAPI Backend │───────▶│  PostgreSQL  │  source of truth
│  ──────────────  │        └──────────────┘
│  REST API        │        ┌──────────────┐
│  WebSocket (/ws) │───────▶│    Redis     │  pub/sub, events only
└────────┬─────────┘        └──────────────┘
         │ HTTPS / WSS
         v
┌──────────────────┐
│  React Dashboard │  inbox · devices · API keys · statistics
└──────────────────┘
```

## Repository Layout

```text
Tsunagi/
├── app/                  Android application (Kotlin, Compose)
├── backend/              FastAPI service, Alembic migrations, tests
├── frontend/             React dashboard (Vite, Tailwind v4)
├── deployment/           docker-compose stack and nginx config
├── scripts/              smoke_test.py, seed_demo.py
├── tmp/frontend/         Dashboard design mockups + Tsunagi Core design system
└── *.md                  Architecture, API, schema, and roadmap docs
```

The Android project sits at the repository root as `app/` rather than in an
`android-app/` directory, because that is where the Gradle wrapper and Android
Studio project files already point.

Design invariants:

- **PostgreSQL is the source of truth.** Redis holds only transient real-time
  state (pub/sub channels, active subscriptions, WebSocket delivery). Losing
  Redis loses no data.
- **The client owns message IDs.** The Android app generates a UUID per message
  so uploads are idempotent and retries are safe.
- **Everything self-hosts.** The whole stack ships as Docker containers behind
  nginx: `api`, `postgres`, `redis`, `frontend`, `nginx`.

---

## Component 1 — Android Application

Located in this repository (`app/`, package `com.vce.tsunagi`).

### Technology

| Concern        | Choice                          |
|----------------|---------------------------------|
| Language       | Kotlin                          |
| UI             | Jetpack Compose (Material 3)    |
| Local storage  | Room                            |
| Networking     | Retrofit                        |
| Background sync| WorkManager                     |
| Architecture   | MVVM + Repository pattern + DI  |
| SDK            | minSdk 26, targetSdk 36         |

### Modules

```text
com.vce.tsunagi
├── TsunagiApplication.kt   Application + AppContainer (manual DI)
├── MainActivity.kt         Compose host
├── data/
│   ├── local/              Room entities, DAOs, database
│   ├── remote/             Retrofit API, DTOs, client factory
│   ├── SettingsStore.kt    Server URL, device name, setup key, sync state
│   └── TsunagiRepository.kt  Capture + sync logic
├── sms/SmsReceiver.kt      SMS BroadcastReceiver
├── sync/                   SyncWorker, SyncScheduler
└── ui/                     HomeScreen, MainViewModel, theme/
```

The dependency graph is small enough that a DI framework would cost more than it
saves, so `AppContainer` is constructed by hand and reachable from a bare
`Context` — which the broadcast receiver and worker both need.

#### SMS Receiver (`sms/`)

- Listens for incoming SMS via a `BroadcastReceiver` (`RECEIVE_SMS`).
- Reassembles multipart SMS, which arrive as several PDUs in one broadcast.
- Parses metadata into `{ id (uuid), sender, body, received_at }`.
- Persists to Room with `sync_status = PENDING` and enqueues a sync.
- Does the database write inside `goAsync()`, since `onReceive` runs on the main
  thread with a short lifetime.
- Reads the platform SMS inbox (`READ_SMS`) as a second, slower path. The
  broadcast alone is not enough to be reliable: none is delivered while the app
  sits in the stopped state — where a force-stop or a vendor battery manager can
  park it, with no callback and nothing in the log to say so — and one can be
  lost to process death between delivery and the write. Every sync pass sweeps
  the inbox from a stored watermark and stores whatever is missing, so a missed
  broadcast costs a delay rather than the message. The first sweep only looks
  back a day, so installing the app does not upload the phone's whole history.
- The app also offers to disable battery optimization for itself, which is what
  prevents the miss rather than recovering from it.

#### Local Storage (`data/local/`)

Room entities mirror the server model (see
[DATABASE_SCHEMA.md](DATABASE_SCHEMA.md)):

- `DeviceEntity` — this device's identity and server token.
- `MessageEntity` — captured messages plus a `sync_status` state machine:
  `PENDING → UPLOADING → SYNCED` (with `FAILED` re-queued for retry, and
  `QUARANTINED` for a message the server refuses permanently).

#### Sync Engine (`sync/`)

- WorkManager job with a network-connected constraint.
- Registers the device on first run, then uploads all `PENDING`/`FAILED`
  messages in batches of 100 and marks them `SYNCED` on success.
- A rejection that blames the batch's contents narrows the pass to one message
  at a time, then quarantines the offender. Without that, a single message the
  server will never accept fails its whole batch on every pass and blocks every
  message behind it indefinitely.
- Exponential backoff on failure; a periodic 15-minute pass catches messages
  captured while offline.
- Distinguishes retryable failures (network errors, 5xx, 429) from permanent
  ones (bad credentials, malformed configuration) so WorkManager does not burn
  retries on a problem only the user can fix.
- A 401 during upload means the device token was revoked server-side, so the
  stored registration is dropped and the next pass registers again.
- Never deletes local data on failure — sync is at-least-once, and the server
  deduplicates by message UUID.
- Prunes messages the server has confirmed once they pass the retention window
  (default 30 days, configurable in the app; `0` keeps everything). Only
  `SYNCED` rows are eligible, so a message that exists nowhere else is never
  dropped.

#### Settings Screen (`ui/`)

Server URL, device name, setup key, current sync status, last-sync timestamp,
and live captured/synced/pending/failed counts.

---

## Component 2 — Backend

### Technology

FastAPI · SQLAlchemy · Alembic · PostgreSQL · Redis.

### Layering

```text
routers/  →  services.py  →  repositories.py  →  SQLAlchemy / Redis
    │
    └── schemas.py (typed request/response, OpenAPI auto-docs)
```

- **Routers** handle HTTP concerns only (auth, validation, status codes).
- **Services** hold business logic (registration, ingestion, dedup, events) and
  own the transaction boundary.
- **Repositories** isolate persistence; nothing above them issues SQL.

Dialect differences are confined to the repository layer: full-text search uses
a PostgreSQL GIN index on `to_tsvector`, and falls back to a `LIKE` scan on
SQLite so local development needs no database server.

### Ingestion Flow

1. Device POSTs a message with its own UUID (Bearer device token).
2. Service inserts by UUID into `messages`; an id already present resolves to
   the stored row instead of creating a duplicate.
3. The transaction commits, **then** the event is published. Publishing before
   commit would wake a long-poller that then queries and finds nothing.
4. WebSocket connections and `/messages/wait` long-pollers subscribed to the
   event bus deliver the message in real time.
5. Device `last_seen` is updated on every authenticated request.

### Real-Time Layer

- **Redis pub/sub** fans out new-message, device-status, and system events.
  When `TSUNAGI_REDIS_URL` is unset an in-process bus is used instead, which is
  correct for a single worker; more than one worker requires Redis.
- With Redis enabled, frames reach local subscribers *only* through the pub/sub
  reader, never directly, so each subscriber sees a publish exactly once no
  matter which worker produced it.
- **`/ws/messages`** pushes new messages, device status, sync events, and system
  events.
- **`GET /api/v1/messages/wait`** offers long-polling for clients that cannot
  hold a WebSocket. It subscribes before its first read so a message arriving in
  between is not missed.

---

## Component 3 — Frontend Dashboard

React + Vite + Tailwind CSS v4, in [frontend/](frontend/). Talks to the backend
exclusively through the public API (API-key auth) and the WebSocket for live
updates — it has no privileged back channel.

```text
frontend/src/
├── App.tsx            Routes and the auth gate
├── lib/
│   ├── api.ts         Typed client mirroring backend/app/schemas.py
│   ├── auth.tsx       API key in localStorage; 401/403 signs the user out
│   ├── hooks.ts       useApi, useLiveFrames (reconnecting WebSocket), usePolling
│   └── format.ts      Relative time, byte sizes, number formatting
├── components/        Layout, shared UI primitives, volume chart
└── pages/             Landing, Connect, Dashboard, Messages, Devices, Keys,
                       Events, Settings
```

The API key is entered once on the Connect screen, verified against
`/api/v1/stats` before it is stored, and kept in `localStorage`. Fonts are
bundled rather than loaded from a CDN, so a self-hosted install has no external
dependencies at runtime.

High-fidelity design mockups live in [tmp/frontend/](tmp/frontend/) — one
folder per screen (`code.html` + `screen.png`), each in desktop and mobile
variants, built on the **Tsunagi Core** design system
([tmp/frontend/tsunagi_core/DESIGN.md](tmp/frontend/tsunagi_core/DESIGN.md)):
a dark zinc/indigo palette with emerald/amber status accents, Geist for
headings and labels, Inter for body/data, and JetBrains Mono for API keys,
phone numbers, and log payloads.

Screens:

- **Landing** — public entry page.
- **Connect** — API key entry, verified before it is stored.
- **Dashboard** — stat tiles (total messages, active devices, messages today,
  storage), 7-day message-volume chart, recent messages, device panel. New
  messages arrive over the WebSocket without a refresh.
- **Messages** — searchable, filterable inbox with debounced full-text search,
  sender and device filters, and pagination.
- **Devices** — online/offline status, last seen, registration time, revoke.
- **API Keys** — create with scope, reveal once, revoke.
- **Events** — live-streaming system log with level filter, pause, and clear;
  seeded from `GET /api/v1/events` and appended from the WebSocket.
- **Settings** — connection details and sign-out.

Layout is responsive: a fixed glassmorphic sidebar on desktop collapsing to
bottom navigation on mobile.

Where the mockups implied data the backend does not track — device uptime,
sync-health percentages, per-key "last used" — the UI omits it rather than
displaying a fabricated number.

---

## Security Model

| Layer      | Mechanism                                        |
|------------|--------------------------------------------------|
| Transport  | HTTPS only; TLS terminated at nginx              |
| Devices    | Per-device bearer tokens issued at registration  |
| Users/apps | API keys (create/revoke via API and dashboard)   |
| Enrolment  | A single-use code (or an admin API key) authorizes one registration |
| Scopes     | Device (upload own messages) · User (read messages, devices, stats) · Admin (also manage devices, keys, and events) |

The dashboard reads `GET /api/v1/me` at sign-in and hides what the credential
cannot do, so a `user` key never sees the API Keys or Events pages and gets no
device controls. That is presentation only — every endpoint enforces its own
scope, so a hand-typed URL or a raw `curl` gains nothing.

Both credential types travel in the same `Authorization: Bearer` header and are
told apart by prefix — `tsn_dev_` for device tokens, `tsn_key_` for API keys.
Only a SHA-256 digest is stored, so a database leak does not yield usable
credentials, and raw values are shown exactly once at creation.

**Enrolment** is single-use. An admin generates a short code on the dashboard,
it registers exactly one phone, and it is spent — consumed in the same
transaction as the device row, with the eligibility conditions inside the
`UPDATE` so two phones racing on one code cannot both succeed. The app discards
the code once redeemed, leaving only its device token behind. That is what makes
the off switch below meaningful: a phone that is turned off cannot re-enrol
itself, because it no longer holds anything that would let it.

Devices have two off states. **Disabling** (`disabled_at`) is a reversible
switch an admin flips from the dashboard; **revoking** (`revoked_at`) is
permanent. Both are soft deletes, which keeps usage history auditable, and
neither touches messages that have already synchronized. API keys have only the
permanent form.

A switched-off device is refused with **403**, never 401. This matters because
the Android client treats 401 as a stale token and re-enrols with its stored
setup key — answering 401 would let a disabled phone re-register under a new id
and quietly defeat the off switch. 403 is terminal on the client, which reports
that an administrator turned it off and stops trying.

**Rate limiting** ([`app/ratelimit.py`](backend/app/ratelimit.py)) counts
requests in a fixed window keyed by credential digest, falling back to client
address when unauthenticated. Counters live in Redis when it is configured so
replicas share one budget, and in process memory otherwise. A limiter outage
fails open — a rate limiter that can take the API down with it is worse than the
abuse it prevents.

The Android app keeps its device token in app-private storage and refuses
cleartext HTTP except to loopback addresses, so a mistyped `http://` production
URL fails loudly rather than shipping SMS contents in the clear.

---

## Deployment

Docker Compose ([deployment/docker-compose.yml](deployment/docker-compose.yml)):

```text
nginx     — reverse proxy and TLS termination; the only published port
frontend  — React build served by its own nginx, proxied at /
api       — FastAPI (uvicorn); runs `alembic upgrade head` on startup
postgres  — persistent volume, source of truth
redis     — ephemeral, events only
```

Serving the dashboard and API from one origin means the browser needs no CORS
grant and the WebSocket inherits the page's scheme, so a TLS deployment works
without reconfiguring the client.

Docker is not required. [deployment/BAREMETAL.md](deployment/BAREMETAL.md)
covers the systemd + nginx + PostgreSQL equivalent, where nginx serves the
dashboard build straight off disk and proxies to uvicorn on localhost.

**Either way, more than one API worker requires Redis.** The event bus and rate
limiter fall back to per-process state without it, so a WebSocket client on one
worker would never see a message ingested by another.

Only nginx is exposed publicly. Backups target the PostgreSQL volume alone,
since Redis holds nothing durable.

The API container forces `TSUNAGI_AUTO_CREATE_SCHEMA=false` so Alembic remains
the single source of truth for the deployed schema; the app's `create_all` path
exists only for local development.

nginx raises `proxy_read_timeout` on `/api/` because `GET /api/v1/messages/wait`
holds its connection open by design, and enables HTTP/1.1 upgrade on `/ws/`.
