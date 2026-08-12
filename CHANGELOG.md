# Changelog

All notable changes to Tsunagi. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow
[Semantic Versioning](https://semver.org/).

## [1.0.0] — 2026-08-12

First stable release. An SMS captured on an Android phone is stored locally,
synchronized to a server you control, and readable in a web dashboard in real
time — over TLS, with role-based access and single-use device enrolment.

### Android app

- SMS capture via `BroadcastReceiver`, including reassembly of multipart
  messages that arrive as several PDUs in one broadcast.
- Room storage with a `PENDING → UPLOADING → SYNCED/FAILED` state machine.
  Messages stranded in `UPLOADING` by a process death are requeued on the next
  pass, so an interrupted upload can never lose a message.
- WorkManager sync engine: batched uploads (100 per request), exponential
  backoff, a network constraint, and a 15-minute periodic pass that catches
  anything captured while offline.
- Retryable failures (network errors, 5xx, 429) are distinguished from permanent
  ones (bad credentials, misconfiguration), so retries are not burned on a
  problem only the user can fix.
- Local retention: messages the server has confirmed are pruned after a
  configurable window (default 30 days; `0` keeps everything). Only `SYNCED`
  rows are eligible.
- Compose UI carrying the Tsunagi Core design system, with live
  captured/synced/pending/failed counts.
- Cleartext HTTP is refused for any non-loopback address, so a mistyped
  `http://` production URL fails instead of shipping messages in the clear.

### Backend

- FastAPI over async SQLAlchemy, layered as routers → services → repositories.
  PostgreSQL in production, SQLite for local development.
- Idempotent ingestion: message IDs are generated on the phone, so an upload
  retried after a lost response resolves to the existing row.
- Full-text search using a PostgreSQL GIN index over `to_tsvector`, falling back
  to `LIKE` on SQLite.
- Real-time delivery through `/ws/messages` and `GET /messages/wait`
  long-polling, backed by an event bus that uses Redis when configured and an
  in-process bus otherwise.
- Alembic migrations own the schema. Startup creates and stamps a fresh
  database, migrates a tracked one, and refuses an untracked but populated one
  rather than silently running against a stale schema.
- Rate limiting per credential (or per address when unauthenticated), counted in
  Redis when available. Fails open if the limiter backend is down.

### Dashboard

- React + Vite + Tailwind v4 implementing Tsunagi Core, with fonts bundled so a
  self-hosted install has no external runtime dependencies.
- Landing, Connect, Dashboard, Messages, Devices, API Keys, Events, and Settings
  screens; responsive from a fixed sidebar down to bottom navigation.
- Live updates over a reconnecting WebSocket; message-volume chart backed by a
  real `/stats/volume` endpoint rather than synthesised data.

### Security

- Credentials are stored as SHA-256 digests and shown in full exactly once.
- Three scopes: `device` (upload only), `user` (read), `admin` (manage devices,
  keys, and events). The dashboard hides what a credential cannot do; the server
  enforces every scope independently.
- **Single-use enrolment codes** replace a shared setup key. A code registers one
  phone, expires in 15 minutes, and is consumed in the same transaction as the
  device row — so two phones racing on one code cannot both succeed. The app
  discards the code once redeemed.
- Devices have a reversible **off switch** distinct from permanent revocation.
  A switched-off device is refused with `403`, never `401`, because the client
  treats `401` as a stale token and re-enrols — answering `401` would let a
  disabled phone walk back in under a new ID.
- TLS deployment via a Compose overlay with automatic certificate renewal, plus
  documented paths for a private CA or an existing terminator.

### Deployment

- Docker Compose stack: nginx, dashboard, API, PostgreSQL, Redis. Only nginx
  publishes ports.
- Bare-metal path with a systemd unit and nginx site for running without Docker.
- `scripts/smoke_test.py` verifies a deployment end to end;
  `scripts/seed_demo.py` populates a throwaway database;
  `scripts/create_key.py` mints or rotates an admin key.

### Known limitations

- Receiving only — Tsunagi does not send SMS, and MMS is out of scope.
- Messages are stored in plaintext on the server; there is no end-to-end
  encryption.
- The event log is capped and transient, suitable for the live view rather than
  auditing.
- R8/minification is disabled for the Android release build.
- No instrumented end-to-end test of the Android app against a live server.

[1.0.0]: https://github.com/you/tsunagi/releases/tag/v1.0.0
