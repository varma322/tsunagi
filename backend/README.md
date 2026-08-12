# Tsunagi Backend

FastAPI service that ingests SMS from registered Android devices, stores them in
PostgreSQL, and serves them over REST and WebSocket. See
[../API_SPEC.md](../API_SPEC.md) for the full contract and
[../ARCHITECTURE.md](../ARCHITECTURE.md) for how it fits together.

## Run locally

```bash
cd backend
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements-dev.txt   # Windows
# .venv/bin/pip install -r requirements-dev.txt               # macOS/Linux

cp .env.example .env
.venv/Scripts/python -m uvicorn app.main:app --reload
```

Defaults to SQLite, so no database server is needed for development. Interactive
docs are at http://127.0.0.1:8000/docs.

On first start with an empty database the service mints an admin API key and
logs it once:

```
No API keys existed, so an admin key was generated. Store it now,
it will not be shown again: tsn_key_...
```

Set `TSUNAGI_BOOTSTRAP_API_KEY` to pin that key instead of reading it from logs.

## Try it

```bash
KEY=tsn_key_...            # admin key from the startup log
SETUP=change-me            # TSUNAGI_SETUP_KEY from .env

# Register a device (returns a device token)
curl -X POST localhost:8000/api/v1/devices/register \
  -H "Authorization: Bearer $SETUP" -H 'Content-Type: application/json' \
  -d '{"device_name":"Office Phone"}'

# Upload a message as that device
curl -X POST localhost:8000/api/v1/messages \
  -H "Authorization: Bearer tsn_dev_..." -H 'Content-Type: application/json' \
  -d '{"id":"b3d0aef2-91a4-4a8f-8f2e-77f0c9e1a5b6","sender":"+15551234567",
       "body":"Your code is 482913","received_at":"2026-08-12T09:27:03Z"}'

# Read it back
curl localhost:8000/api/v1/messages -H "Authorization: Bearer $KEY"
```

## Tests

```bash
.venv/Scripts/python -m pytest
```

The suite runs against a temporary SQLite database and covers auth scopes,
idempotent ingestion, filtering, search, long-polling, and the WebSocket.

## Layout

```text
app/
├── main.py          FastAPI app, lifespan, router registration
├── config.py        Settings (TSUNAGI_* environment variables)
├── db.py            Async engine and session factory
├── models.py        SQLAlchemy ORM: Device, Message, ApiKey
├── schemas.py       Pydantic request/response models
├── security.py      Token generation and hashing
├── deps.py          Bearer auth, scope enforcement
├── middleware.py    Rate limit middleware
├── ratelimit.py     Fixed-window limiter (in-process or Redis)
├── repositories.py  All SQL lives here
├── services.py      Business logic; owns commit-then-publish ordering
├── events.py        In-process and Redis-backed event bus
├── errors.py        {"error": {...}} response envelope
└── routers/         devices, messages, keys, events, stats, ws
```

## Notes

- **Redis is optional.** Without `TSUNAGI_REDIS_URL` an in-process bus is used,
  which works for a single worker. Run more than one uvicorn worker and Redis
  becomes required for `/ws/messages` and `/messages/wait` to see events from
  sibling workers.
- **Full-text search** uses a PostgreSQL GIN index on `to_tsvector`. On SQLite
  the repository falls back to a `LIKE` scan, which is fine for development but
  not for production volumes.
- **Migrations** are the schema's source of truth: `alembic upgrade head`. With
  `TSUNAGI_AUTO_CREATE_SCHEMA=true` the app manages this itself at startup — a
  brand-new database is created and stamped at head, and an existing one is
  migrated forward. The Docker entrypoint runs Alembic explicitly and forces the
  flag off.

  Startup **refuses** a database that has Tsunagi tables but no
  `alembic_version`, which is what an early build's `create_all` produced.
  `create_all` never alters an existing table, so such a database silently lacks
  every column added since and fails at request time rather than startup. To
  reconcile one: back it up, `alembic stamp <the revision its schema matches>`,
  drop any table a later migration creates, then `alembic upgrade head`.
