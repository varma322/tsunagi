# Tsunagi

Open-source, self-hosted SMS synchronization for Android.

Tsunagi captures SMS on your phone, synchronizes them to a server you control,
and exposes them through a documented HTTP API, a WebSocket stream, and a web
dashboard. It is built for people who want their messages archived, searchable,
and available to their own scripts — without handing them to a third party.

> **v1.0.0** — Android app, backend, and dashboard work end to end, with TLS,
> rate limiting, local retention, admin/read-only roles, and single-use device
> enrolment. See [CHANGELOG.md](CHANGELOG.md) and [ROADMAP.md](ROADMAP.md).

---

## How it works

```text
Android device  ──HTTPS──▶  FastAPI backend  ──▶  PostgreSQL   (source of truth)
                                    │
                                    └──────────▶  Redis        (real-time events)
                                    │
                            REST + WebSocket  ──▶  Dashboard / your scripts
```

Messages are given a UUID on the phone, so an upload retried after a lost
response resolves to the same record instead of duplicating it. Nothing is
deleted locally until the server confirms receipt.

---

## Quick start

### 1. Run the backend

```bash
cd backend
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements-dev.txt   # Windows
# .venv/bin/pip install -r requirements-dev.txt               # macOS/Linux

cp .env.example .env          # set TSUNAGI_SETUP_KEY
.venv/Scripts/python -m uvicorn app.main:app --reload
```

Defaults to SQLite, so no database server is needed to try it. Interactive API
docs are at http://127.0.0.1:8000/docs. On first start the server logs an admin
API key — save it.

For a real deployment:

```bash
cd deployment
cp .env.example .env          # set POSTGRES_PASSWORD and TSUNAGI_SETUP_KEY
docker compose up -d          # nginx + dashboard + api + postgres + redis
```

The dashboard is then at http://localhost:8080 — open it and paste an API key.
An `admin` key manages devices, keys, and events; a `user` key is read-only and
the dashboard hides what it cannot do.
To serve it over HTTPS (which the Android app requires for any non-loopback
address), follow [deployment/TLS.md](deployment/TLS.md).

### 2. Verify it

```bash
python scripts/smoke_test.py --url http://127.0.0.1:8000 \
    --setup-key <TSUNAGI_SETUP_KEY> --api-key <admin key>
```

This walks the same path the phone takes: register a device, upload a batch,
read it back, and confirm auth scopes are enforced.

### 3. Run the dashboard (development)

```bash
cd frontend
npm install
npm run dev        # http://localhost:5173, proxies /api to port 8000
```

Paste an API key on the Connect screen. To explore the layouts without waiting
for real traffic, seed a throwaway database first:

```bash
python scripts/seed_demo.py --url http://127.0.0.1:8000 \
    --setup-key <TSUNAGI_SETUP_KEY> --api-key <admin key>
```

### 4. Build the Android app

```bash
./gradlew :app:assembleDebug
```

Install it and grant SMS permission. In the dashboard, open **Devices → Add a
device** and generate an enrolment code, then enter your server URL, a device
name, and that code in the app. It registers itself, discards the code, and
begins syncing. Incoming messages upload immediately; anything captured while
offline goes out on the next pass.

Codes are single-use and expire in 15 minutes, so a phone that an admin later
turns off cannot re-enrol itself.

When testing against a backend on your development machine, use
`http://10.0.2.2:8000` from the emulator — cleartext HTTP is permitted only for
loopback addresses, so a mistyped production URL fails instead of sending
messages in the clear.

---

## Tests

```bash
cd backend && .venv/Scripts/python -m pytest    # 79 backend tests
./gradlew :app:testDebugUnitTest                # 18 Android tests
cd frontend && npm run typecheck                # dashboard types
```

The backend suite covers auth scopes, idempotent ingestion, filtering, search,
long-polling, and the WebSocket. The Android suite covers the sync state
machine: registration, batching, deduplication, and how each class of failure is
classified as retryable or permanent.

---

## Documentation

| Document | Contents |
|----------|----------|
| [ARCHITECTURE.md](ARCHITECTURE.md) | System structure, components, security model, deployment |
| [API_SPEC.md](API_SPEC.md) | Full REST and WebSocket contract |
| [DATABASE_SCHEMA.md](DATABASE_SCHEMA.md) | PostgreSQL, Redis, and Room schemas |
| [ROADMAP.md](ROADMAP.md) | Milestones, current status, known gaps |
| [CHANGELOG.md](CHANGELOG.md) | What changed in each release |
| [RELEASING.md](RELEASING.md) | Cutting a release: versions, signing, verification |
| [backend/README.md](backend/README.md) | Backend development guide |
| [deployment/VPS.md](deployment/VPS.md) | Deploying on a VPS with Docker and your own domain |
| [deployment/BAREMETAL.md](deployment/BAREMETAL.md) | Deploying without Docker — systemd, nginx, PostgreSQL |
| [deployment/TLS.md](deployment/TLS.md) | Serving over HTTPS — Let's Encrypt, private CA, or an existing terminator |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Development setup and project conventions |
| [Tsunagi_IMPLEMENTATION.md](Tsunagi_IMPLEMENTATION.md) | Original design document |

---

## Layout

```text
app/            Android application (Kotlin, Jetpack Compose, Room, WorkManager)
backend/        FastAPI service, Alembic migrations, tests
frontend/       React dashboard (Vite, Tailwind v4)
deployment/     docker-compose stack and nginx configuration
scripts/        smoke_test.py (verify a deployment), seed_demo.py (demo data)
tmp/frontend/   Dashboard mockups and the Tsunagi Core design system
```

---

## Non-goals

Deliberately out of scope for v1.0: MMS, sending messages, contact sync, desktop
clients, and multi-user organizations. Tsunagi aims to do one thing well —
reliably synchronize received SMS.
