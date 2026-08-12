# Contributing to Tsunagi

Thanks for your interest. Tsunagi is a self-hosted SMS synchronization platform;
its one promise is that a message captured on a phone reaches your server and is
never silently lost. That promise shapes most of the guidance below.

---

## Getting set up

The repository holds three independent components. You only need the toolchain
for whichever one you are touching.

### Backend (Python 3.11+)

```bash
cd backend
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements-dev.txt   # Windows
# .venv/bin/pip install -r requirements-dev.txt               # macOS/Linux

cp .env.example .env
.venv/Scripts/python -m uvicorn app.main:app --reload
.venv/Scripts/python -m pytest
```

Development defaults to SQLite, so no database server is required. If you change
anything schema-related, run against PostgreSQL too — the two dialects differ
where it matters (see [Dialect differences](#dialect-differences)).

**Mind the Python version gap.** The container runs Python 3.12 while your local
interpreter may be newer, and 3.14 evaluates annotations lazily. Code that
imports fine locally can fail at import time in the image. Before releasing,
bring the stack up for real:

```bash
cd deployment && cp .env.example .env
docker compose up -d --build && docker compose ps
```

### Dashboard (Node 20+)

```bash
cd frontend
npm install
npm run dev          # proxies /api to localhost:8000
npm run typecheck
npm run build
```

### Android app (JDK 17+, Android SDK 37)

```bash
./gradlew :app:assembleDebug
./gradlew :app:testDebugUnitTest
```

Android Studio will offer to install the SDK platform if it is missing.

---

## Before you open a pull request

Run whatever applies to what you changed:

```bash
cd backend && .venv/Scripts/python -m pytest
cd frontend && npm run typecheck && npm run build
./gradlew :app:testDebugUnitTest
```

If you touched the API contract or the deployment, also run the end-to-end check
against a live server:

```bash
python scripts/smoke_test.py --url http://127.0.0.1:8000 \
    --setup-key <TSUNAGI_SETUP_KEY> --api-key <admin key>
```

---

## What we look for

**Match the surrounding code.** Each component has settled conventions — the
backend's router → service → repository layering, the Android app's MVVM and
manual DI container, the dashboard's typed API client. New code should look like
it belongs, not like it arrived from a different project.

**Keep documentation truthful.** [ARCHITECTURE.md](ARCHITECTURE.md),
[API_SPEC.md](API_SPEC.md), and [DATABASE_SCHEMA.md](DATABASE_SCHEMA.md)
describe what the code actually does. If your change makes one of them wrong,
fix it in the same pull request. A stale spec is worse than none.

**Test the failure, not just the success.** The interesting behaviour in this
codebase is what happens when things go wrong: a lost response, a revoked token,
a phone offline for a week. A test that only proves the happy path usually is
not proving much.

**Never display data you do not have.** The dashboard deliberately omits fields
the backend does not track rather than showing a plausible placeholder. A number
on screen is a claim about reality.

---

## Conventions that are not obvious

### Sync is at-least-once, deduplicated by client id

Message UUIDs are generated on the phone, not the server. That is what makes a
retry after a lost response safe: the server resolves the id to the existing row
instead of storing a duplicate. Do not move id generation server-side, and do
not add a code path that deletes a local message before the server confirms it.

### Commit before you publish

Services commit their transaction and *then* publish to the event bus. Publish
first and a long-poller woken by the event will query, find nothing, and go back
to sleep having consumed its wake-up. See `MessageService.ingest`.

### PostgreSQL is the source of truth; Redis is not

Redis carries pub/sub frames and a capped event log. Losing it must never lose a
message. If you find yourself wanting to store something durable there, it
belongs in PostgreSQL.

### Dialect differences

Full-text search uses a PostgreSQL GIN index over `to_tsvector`, with a `LIKE`
fallback on SQLite so development needs no database server. Dialect branching
lives in `repositories.py` and should stay there.

### Credentials are stored hashed

Device tokens and API keys are persisted as SHA-256 digests and shown in full
exactly once. Anything that would let a key be read back after creation is a bug,
not a convenience.

### Schema changes go through Alembic

```bash
cd backend
.venv/Scripts/python -m alembic revision --autogenerate -m "describe change"
.venv/Scripts/python -m alembic upgrade head
```

Check the generated migration by hand — autogenerate misses index and constraint
details — and verify it downgrades cleanly.

**Test the upgrade path, not just a fresh database.** `TSUNAGI_AUTO_CREATE_SCHEMA`
makes the app create-and-stamp a new database or migrate an existing one, so a
migration that only ever runs against an empty file can still be wrong. Point a
populated database at your branch before merging.

### Room schema changes need a migration too

Bump the version in `TsunagiDatabase` and supply a migration. Room's exported
schema JSON in `app/schemas/` is committed so changes are reviewable. Do not
reach for `fallbackToDestructiveMigration` — on this app that means deleting
messages that may not have synced yet.

---

## Reporting bugs

Include the component (backend / dashboard / Android), what you expected, what
happened, and how to reproduce it. For sync problems the Android logcat tag
`SyncWorker` and the server's Events page are usually the fastest evidence.

**Never paste real message contents, device tokens, or API keys into an issue.**
Redact them, or reproduce with the demo data:

```bash
python scripts/seed_demo.py --url http://127.0.0.1:8000 \
    --setup-key <setup key> --api-key <admin key>
```

Point that at a throwaway database — it writes real rows and has no undo.

---

## Security issues

Do not open a public issue for a vulnerability. Report it privately to the
maintainers first so a fix can ship before the details are public.

---

## Scope

Tsunagi aims to do one thing well: reliably synchronize received SMS. MMS,
sending messages, contact sync, and multi-user organizations are explicit
non-goals for v1.0 — see [ROADMAP.md](ROADMAP.md). Proposals in those areas are
welcome as discussion issues, but pull requests implementing them are likely to
sit unmerged until the core is finished.
