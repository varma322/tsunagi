# Changelog

All notable changes to Tsunagi. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- **Clearing a device's messages.** `DELETE /api/v1/devices/{id}/messages`
  permanently deletes every message uploaded by one device and reports how many
  it removed. Admin scope, no schema change, and the device is left registered
  and uploading. In the dashboard it is a **Clear messages** button on each
  device card.

  Irreversible by design, and the confirm dialog says so. Two things it does not
  do, both documented in `API_SPEC.md`: it does not touch the phone's own
  storage or the Android inbox, and it does not reach database dumps taken
  beforehand — including the one `deployment/update.sh` writes before every
  migration — so it is not an erasure tool.

  Recorded in the audit trail as `DEVICE_MESSAGES_CLEARED` with the device, its
  name and the count. Once the rows are gone that entry is the only remaining
  record that they existed.

## [1.2.0] — 2026-09-01

Two capabilities and two fixes. A phone can now pause uploading without losing
capture; the server keeps a durable audit trail alongside its transient event
log. Migration `0006` adds the `audit_events` table and touches nothing
existing, so upgrading a deployment is a rebuild and a restart; reinstall the
APK for the app-side changes.

### Fixed

- **The Android app no longer shows a stale "SMS permission required" prompt.**
  The card was read once when the screen was composed and refreshed only through
  the in-app request's own callback, so granting or revoking the permission from
  the system settings and returning left it wrong until the screen was rebuilt.
  It is now re-read every time the screen resumes, the way the battery-exemption
  prompt already was.

### Added

- **A durable audit trail.** The event bus keeps only a capped, in-memory log
  for the dashboard's live view, which is gone on a restart. Noteworthy events —
  device and key lifecycle, enrolment, capture health, webhook failures — are
  now also written to an append-only `audit_events` table (migration `0006`) and
  read back through `GET /api/v1/audit`, which paginates and filters by type,
  level, and time. High-frequency message and sync traffic is deliberately not
  audited: the messages table already records it, and it would bury the security
  and administrative events the trail exists for. The bus stays storage-agnostic
  — persistence is an injected sink — so the live log is unchanged.
- **A sync on/off switch in the Android app.** Turning sync off stops uploads
  while capture keeps running, so the queue holds rather than loses anything —
  messages wait on the phone until sync is turned back on. Paused, the app goes
  quiet with the server entirely (no upload and no check-in), so the dashboard
  will show the device offline until it resumes; that is the honest reading of
  an off switch.
- **An opt-in to not sync a paused session's messages.** With it on, messages
  *received* while paused are kept on the phone but never uploaded, even after
  resuming — for pausing before something private arrives. The hold-back is
  keyed on when a message was received, not on how it was captured, so one the
  live broadcast missed and the inbox sweep recovers after resume is caught by
  the same window rather than slipping out. A new `EXCLUDED` state marks these;
  they are surfaced in the app and never enter the upload queue.

## [1.1.1] — 2026-08-31

A capture-reliability patch: the one fix below, found by flooding a physical
phone with OTP traffic. Android-only — no server, schema, or API change — so
upgrading a deployment is nothing, and the APK must be reinstalled to get it.

### Fixed

- **The inbox sweep no longer drops a resend that shares its text with another
  message.** When two genuinely distinct messages with identical bodies arrived
  within ten minutes and both reached the app through the sweep rather than the
  live broadcast — the case while the app is parked, and exactly what an OTP and
  its resend look like — the second was discarded as a duplicate of the first.
  The sweep's content match now pairs each swept message with at most one stored
  row and never reuses one, so distinct messages survive while a message seen
  twice is still stored once. Found by a field test that flooded a real phone
  with OTP traffic; the loss mechanism is a candidate for the small,
  undiagnosed losses noted under Known Gaps.

## [1.1.0] — 2026-08-29

Two ways to get messages out of Tsunagi and into something else: export them, or
have the server push them as they arrive. Migration `0005` adds the `webhooks`
table; nothing existing changes, and an upgrade is a rebuild and a restart. The
Android app is unchanged — its version moves only so the four version strings
agree.

### Added

- **Message export.** `GET /api/v1/messages/export?format=csv|json` returns
  everything matching the usual filters, oldest first, with no page limit, and
  the dashboard's Messages page has CSV and JSON buttons that export exactly
  what the filter chips describe. The response is streamed in keyset-paged
  chunks, so exporting a year of messages does not mean holding a year of
  messages in memory, and CSV is rendered through the `csv` module because
  message bodies contain commas, quotes and newlines.
- **Webhooks.** Register an endpoint under `POST /api/v1/webhooks` and this
  server calls it when a message arrives or a device's status changes, so an
  integration with no browser open does not have to poll. Each delivery is
  signed with a per-webhook secret over `timestamp.body`, which is what lets a
  receiver tell a real delivery from anything else that finds the URL, and the
  timestamp is inside the signature so a captured one cannot be replayed
  forever. Retried on a `5xx` or an unreachable endpoint, never on another
  `4xx`; twenty consecutive failures switch the webhook off rather than costing
  every message a timeout. Delivered from a bounded worker pool over `urllib`,
  so a backlog upload cannot open a connection per message and no production
  deployment gains an HTTP-client dependency. The dashboard has a Webhooks page
  with a test button that reports what the endpoint actually answered.

## [1.0.2] — 2026-08-29

A phone that had stopped capturing SMS now says so, a batch upload can name the
one message it refused, and the release build is minified. No schema changes
beyond migration `0004`, which only adds nullable columns, and no configuration
changes — but the capture reporting lives in the app, so the APK must be
reinstalled for the dashboard to show anything but `unknown`.

### Added

- **A phone that has stopped capturing SMS no longer reports itself healthy.**
  `last_seen` proves the app can reach the server, which it does perfectly well
  after its SMS permission has been revoked — so a phone capturing nothing was
  indistinguishable from a phone nobody had texted. The app now reports, on
  every sync pass, whether `RECEIVE_SMS` and `READ_SMS` are still granted,
  whether the last inbox sweep could read the platform store, whether it is
  exempt from battery optimization, and when it last captured a message. The
  dashboard shows `ok`, `blocked` or `unknown` per device, with the reason, and
  `last_captured_at` distinguishes a quiet phone from a broken one.
- `POST /api/v1/devices/checkin` (device scope), and six columns on `devices`
  holding what it reports. Migration `0004`. A transition into or out of
  `blocked` raises `DEVICE_CAPTURE_BLOCKED` / `DEVICE_CAPTURE_RESTORED`; an
  unchanged report raises nothing, since a blocked phone reports every fifteen
  minutes.
- The inbox sweep now distinguishes a store it could not read from a store with
  nothing new in it. Both used to come back as an empty list, which meant a
  revoked permission looked exactly like a quiet inbox — the same conflation as
  above, one layer down.
- **A batch upload can report a verdict per message.** One message the server
  would not accept rejected every message it travelled with, and the response
  could not say which was at fault — so the phone found the offender by
  re-uploading the batch one message at a time, and until it did, nothing behind
  it moved. `POST /api/v1/messages/batch` now takes `"partial": true` and
  answers with `created` / `duplicate` / `rejected` per message, each with the
  reason it was refused. The app opts in and quarantines the named message on
  the pass that found it.

  `partial` is off by default and has to be: a client that ignored the results
  would read `200` as "all stored" and drop the message the server refused. An
  older app keeps the all-or-nothing behaviour it already survives, and the app
  keeps its isolate-one-at-a-time path for servers that answer the old way.

### Changed

- **R8 is enabled for the release build**, taking the APK from 13.4 MB to
  1.7 MB. It was off for 1.0 on the assumption that Room, Retrofit and
  kotlinx.serialization would each need hand-written keep rules; they ship their
  own, and the only rule this project needs is for something else entirely.
  Retrofit reads a suspend function's return type from the generic signature of
  the Continuation it compiles into, and R8 erases that to `Object` when the
  type argument is a response the app never reads — the call then fails at the
  first request, in the release build only. `app/proguard-rules.pro` records
  what each library covers so the rules are not re-added by hand.
- The phone's idle check-in is now `POST /api/v1/devices/checkin` rather than
  `GET /api/v1/me`, and it runs on every pass rather than only when there is
  nothing to upload: a phone can be busy draining its queue and have already
  lost the permission that fills it. Against a server too old to accept it, the
  app falls back to the old heartbeat instead of reporting a failed pass.
- A check-in that fails after messages went up no longer turns a successful
  upload into a failed pass.

## [1.0.1] — 2026-08-29

A capture-reliability release: most of what follows closes a way a received SMS
could fail to reach the server, or a way a working phone could look broken on
the dashboard. There are no schema changes, so upgrading a server is a rebuild
and a restart — but see **Changed** for one default that moves. The capture
fixes are all in the app, so the APK must be reinstalled to get them.

### Fixed

- **A missed SMS broadcast no longer loses the message.** Capture relied
  entirely on the live `SMS_RECEIVED` broadcast, which is best-effort: none is
  delivered while the app is in the stopped state — where a force-stop or a
  vendor battery manager can park it silently — and one can be lost to process
  death between delivery and the database write. Neither is visible from the
  receiver. Every sync pass now sweeps the platform SMS inbox from a stored
  watermark and stores anything missing, so a missed broadcast costs a delay
  instead of the message. A first sweep looks back one day, so installing the
  app does not upload the phone's entire history.
- **One rejected message no longer blocks the whole upload queue.** Uploads go
  up in batches of 100, and a rejection marked every message in the batch
  `FAILED` — which the next pass re-selected in the same order, with the same
  offender at its head, forever. A message the server permanently refuses is now
  isolated and quarantined, and the messages behind it go up. `attempt_count`
  had been recorded since 1.0.0 but never read; this is what it was for.
- **The same SMS seen twice is stored once.** Message ids were random per
  capture, so the duplicate check could never match — a broadcast delivered
  twice produced two rows and two uploads. Ids are now derived from the message
  itself.
- An empty originating address is treated as an unknown sender rather than
  passed through, where the server rejected it and stalled the queue.
- A message whose body decoded as empty was silently discarded; it is now
  stored.
- A message that failed to store no longer aborts the rest of its broadcast.
- **A healthy but idle phone no longer reports "Offline" forever.** `last_seen`
  advances only on an authenticated device call, and a phone with nothing to
  upload made no call at all, so a quiet device read as offline and
  `active_devices` undercounted it. A sync pass with nothing to send now checks
  in, which also lets a disabled device find that out without waiting for the
  next SMS. A `401` during a check-in re-enrols, as it does during an upload.
- **`scripts/smoke_test.py` runs against a production install.** It imported
  `httpx`, which ships only in `requirements-dev.txt`, so the verification step
  at the end of the installer died on `ModuleNotFoundError`; it is now written
  on `urllib` with no third-party imports. It also sends an explicit user agent,
  because Cloudflare's browser-integrity check rejects `Python-urllib/*` with a
  403 that reads like an auth failure. The app and dashboard were never
  affected.
- **`setup-vps.sh --skip-build` works on a fresh clone.** It looked for
  `frontend/dist`, which is gitignored and therefore cannot exist yet. Pass a
  directory or a tarball with `--dist` instead; bare `--skip-build` now explains
  how to produce one.
- **Updating a bare-metal install works.** The installer chowns the checkout to
  the service user, so the documented `git pull` failed as root with "dubious
  ownership". The directory is now declared trusted.

### Added

- An option to disable battery optimization for Tsunagi, which is what prevents
  a missed broadcast rather than recovering from it. The app shows the prompt
  only while the exemption is missing and re-checks it on return.
- `QUARANTINED` sync status, surfaced in the UI, so a message that will never be
  uploaded is visible rather than silently absent.
- `deployment/setup-vps.sh` — an installer for a VPS already serving other
  sites. It binds the Compose stack to loopback and reverse-proxies through the
  host nginx, validates the whole nginx config before reloading (unlinking its
  own site if the test fails), and adds swap first, since a one-core box
  OOM-kills the Vite build.
- `deployment/setup-vps-baremetal.sh` — a Docker-free installer for a server
  that already runs PostgreSQL and Redis. It reuses both rather than starting
  duplicates, picks an unused Redis logical database so pub/sub cannot collide
  with an existing broker, serves the dashboard as static files, and runs the
  API under systemd on loopback.
- `deployment/update.sh` — reinstalls dependencies only when requirements move,
  dumps the database before a new migration, restarts, and says plainly when the
  dashboard or the APK still needs rebuilding.
- [API_GUIDE.md](API_GUIDE.md), a task-oriented companion to `API_SPEC.md`:
  auth, filtering, both real-time options, errors, rate limits, and enrolling a
  phone.
- Receiver logging at each stage of capture — PDU count, per-part sender and
  body length, assembled and stored counts — so a missed message can be
  diagnosed. Metadata only; message contents are never logged.
- Instrumented tests against real SQLite and the real SMS provider: the Room
  queries the sweep depends on, the provider projection, and the sweep end to
  end through the repository. On an emulator holding 195 messages, a first sweep
  recovers all 195 and a second recovers none.

### Changed

- **`TSUNAGI_DEVICE_ONLINE_WINDOW_SECONDS` now defaults to `1800`, from `300`.**
  Android will not schedule periodic work more often than every 15 minutes, and
  Doze delays it further, so the old window marked a healthy phone offline
  between beats. An existing deployment that sets this explicitly in its `.env`
  keeps its own value and should raise it to at least `1800`.

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

[1.2.0]: https://github.com/you/tsunagi/releases/tag/v1.2.0
[1.1.1]: https://github.com/you/tsunagi/releases/tag/v1.1.1
[1.1.0]: https://github.com/you/tsunagi/releases/tag/v1.1.0
[1.0.2]: https://github.com/you/tsunagi/releases/tag/v1.0.2
[1.0.1]: https://github.com/you/tsunagi/releases/tag/v1.0.1
[1.0.0]: https://github.com/you/tsunagi/releases/tag/v1.0.0
