# Tsunagi — DATABASE_SCHEMA.md

Storage design for both sides of the sync: **PostgreSQL** on the server
(source of truth, managed with SQLAlchemy + Alembic migrations) and **Room**
on the Android device (local capture buffer and sync queue).

Related docs: [ARCHITECTURE.md](ARCHITECTURE.md) · [API_SPEC.md](API_SPEC.md)

---

## PostgreSQL (server — source of truth)

### Entity Relationship

```text
devices 1 ──── * messages

api_keys   (standalone; authenticates dashboard/API users)
```

### `devices`

One row per registered Android device.

```sql
CREATE TABLE devices (
    id          UUID PRIMARY KEY,
    name        VARCHAR(120)  NOT NULL,
    token_hash  VARCHAR(128)  NOT NULL UNIQUE,   -- SHA-256 of the device token
    created_at  TIMESTAMPTZ   NOT NULL,
    last_seen   TIMESTAMPTZ,
    disabled_at TIMESTAMPTZ,                     -- NULL = switched on
    revoked_at  TIMESTAMPTZ                      -- NULL = not revoked
);
```

| Column        | Notes                                                        |
|---------------|--------------------------------------------------------------|
| `token_hash`  | Raw device tokens are never stored — only a hash for lookup. |
| `last_seen`   | Updated on every authenticated request from the device.      |
| `disabled_at` | Reversible off switch an admin toggles. The device keeps its token and resumes when re-enabled. |
| `revoked_at`  | Permanent. The device disappears from listings; its messages are retained. |

Two separate columns rather than one status field: an admin pausing a phone and
an admin retiring one for good are different intentions, and collapsing them
would make "turn it back on" ambiguous.

The online/offline flag the API returns is **derived**, not stored: a device
counts as online when `last_seen` falls within
`TSUNAGI_DEVICE_ONLINE_WINDOW_SECONDS` (default 1800 — the phone checks in every
15 minutes at best, so the window allows one missed beat). Persisting it would mean
every device silently going stale needed a background job to flip the column.

Indexes:

```sql
CREATE INDEX idx_devices_last_seen ON devices (last_seen DESC);
```

### `messages`

One row per synchronized SMS. The primary key is the **client-generated UUID**,
which makes ingestion idempotent (retried uploads upsert onto the same row).

```sql
CREATE TABLE messages (
    id           UUID PRIMARY KEY,           -- generated on the device
    device_id    UUID        NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
    sender       TEXT        NOT NULL,
    body         TEXT        NOT NULL,
    received_at  TIMESTAMPTZ NOT NULL,       -- when the SMS hit the phone
    created_at   TIMESTAMPTZ NOT NULL        -- when the server stored it
);
```

Ingestion inserts inside a savepoint and treats a unique-violation as "already
stored", which is dialect-agnostic and makes a retried upload resolve to the
existing row.

Indexes (driven by the query patterns in [API_SPEC.md](API_SPEC.md)):

```sql
-- List/paginate newest-first, per device or globally
CREATE INDEX idx_messages_received_at ON messages (received_at DESC);
CREATE INDEX idx_messages_device_received ON messages (device_id, received_at DESC);

-- Sender filter
CREATE INDEX idx_messages_sender ON messages (sender);

-- Full-text search over bodies (GET /messages/search)
CREATE INDEX idx_messages_body_fts
    ON messages USING GIN (to_tsvector('simple', body));
```

### `enrolment_tokens`

Single-use codes authorizing one device registration each.

```sql
CREATE TABLE enrolment_tokens (
    id                UUID PRIMARY KEY,
    code_hash         VARCHAR(128) NOT NULL UNIQUE,  -- SHA-256; code shown once
    label             VARCHAR(120),
    created_at        TIMESTAMPTZ  NOT NULL,
    expires_at        TIMESTAMPTZ  NOT NULL,
    used_at           TIMESTAMPTZ,                   -- NULL = not yet spent
    cancelled_at      TIMESTAMPTZ,
    created_by_key_id UUID REFERENCES api_keys(id) ON DELETE SET NULL,
    used_by_device_id UUID REFERENCES devices(id)  ON DELETE SET NULL
);
```

Status is derived rather than stored: `used` → `cancelled` → past `expires_at`
→ otherwise `pending`. Storing it would need a job to flip codes to `expired` on
schedule.

`created_by_key_id` and `used_by_device_id` are the audit trail — which admin
issued a code, and which device it produced.

Spending a code is a conditional `UPDATE` (`WHERE used_at IS NULL AND
cancelled_at IS NULL AND expires_at > now()`) rather than a `SELECT` followed by
a write, so concurrent registrations cannot both consume the same code: exactly
one statement matches a row.

### `api_keys`

Credentials for dashboard users and third-party integrations.

```sql
CREATE TABLE api_keys (
    id          UUID PRIMARY KEY,
    name        TEXT         NOT NULL,
    key_hash    VARCHAR(128) NOT NULL UNIQUE,   -- SHA-256; raw key shown once
    scope       VARCHAR(16)  NOT NULL DEFAULT 'user',  -- 'user' | 'admin'
    created_at  TIMESTAMPTZ  NOT NULL,
    revoked_at  TIMESTAMPTZ                     -- NULL = active
);
```

Revocation is a soft delete (`revoked_at` set) so key usage history remains
auditable.

### Migrations

All schema changes go through **Alembic**:

```bash
alembic revision --autogenerate -m "describe change"
alembic upgrade head
```

Never edit the schema out-of-band; the Alembic history is the schema's record
of truth.

---

## Redis (server — transient only)

Redis holds **no durable data**. Losing it loses events in flight, never
messages — PostgreSQL remains the source of truth.

| Key / channel               | Type    | Purpose                                            |
|-----------------------------|---------|----------------------------------------------------|
| `messages:new`              | pub/sub | New-message events → WebSocket + `/wait`           |
| `devices:status`            | pub/sub | Device online/offline transitions                  |
| `ws:subscriptions:<conn>`   | hash    | Active WebSocket subscription state                |
| `events:log`                | stream  | System event log (`MSG_RECV`, `SYNC_OK`, `AUTH_FAIL`, …), capped at 1000 entries (`XADD … MAXLEN ~1000`); backs `GET /api/v1/events` and the dashboard's Events page |

---

## Room (Android — local buffer & sync queue)

Package `com.vce.tsunagi.data.local`. Mirrors the server model plus sync
bookkeeping.

Server URL, device name, and setup key live in app-private `SharedPreferences`
rather than Room: they are configuration, not relational data, and keeping them
out of the database lets the sync worker read them without opening it.

### `DeviceEntity` — table `device`

This device's identity after registration. At most one row exists; a fixed
primary key makes re-registration replace it rather than accumulate rows.

| Column        | Kotlin type | Notes                                     |
|---------------|-------------|-------------------------------------------|
| `row_id`      | `Int` PK    | Always `1` — enforces the single row      |
| `device_id`   | `String`    | UUID assigned by the server               |
| `device_name` | `String`    | User-chosen name                          |
| `token`       | `String`    | Device bearer token (app-private storage) |
| `created_at`  | `Long`      | Epoch millis                              |

### `MessageEntity` — table `messages`

Every captured SMS, with its synchronization state.

| Column          | Kotlin type  | Notes                                        |
|-----------------|--------------|----------------------------------------------|
| `id`            | `String` PK  | UUIDv5-style, derived from the message itself |
| `sender`        | `String`     |                                              |
| `body`          | `String`     |                                              |
| `received_at`   | `Long`       | Epoch millis, from the SMS PDU               |
| `sync_status`   | `SyncStatus` | `PENDING` · `UPLOADING` · `SYNCED` · `FAILED` · `QUARANTINED` |
| `synced_at`     | `Long?`      | Set when the server confirms the upload      |
| `attempt_count` | `Int`        | Upload attempts so far; surfaces stuck rows  |
| `last_error`    | `String?`    | Reason the last attempt failed               |

```kotlin
@Entity(
    tableName = "messages",
    indices = [Index("sync_status"), Index("received_at")],
)
data class MessageEntity(
    @PrimaryKey val id: String,
    @ColumnInfo(name = "sender") val sender: String,
    @ColumnInfo(name = "body") val body: String,
    @ColumnInfo(name = "received_at") val receivedAt: Long,
    @ColumnInfo(name = "sync_status") val syncStatus: SyncStatus = SyncStatus.PENDING,
    @ColumnInfo(name = "synced_at") val syncedAt: Long? = null,
    @ColumnInfo(name = "attempt_count") val attemptCount: Int = 0,
    @ColumnInfo(name = "last_error") val lastError: String? = null,
)
```

### Sync state machine

```text
PENDING ──▶ UPLOADING ──▶ SYNCED        (2xx from server)
                │
                ├───────▶ FAILED ──▶ PENDING   (WorkManager retry w/ backoff)
                │
                └───────▶ QUARANTINED          (server refuses it permanently)
```

- The `sync_status` index lets the sync worker cheaply select the upload queue
  (`WHERE sync_status IN ('PENDING', 'FAILED')`).
- `QUARANTINED` is the queue's only permanent exit. Uploads go up in batches, so
  a message the server will never accept — one whose `sender` the server rejects,
  say — fails the whole batch, and would be re-selected with the same batch
  forever, blocking every message behind it. On a rejection that blames the
  content (a 4xx that is not 401, 403, 408 or 429), the pass narrows to one
  message at a time to find the offender, sets that one aside, and carries on.
  The row is kept, and the count is surfaced in the UI, so a message that will
  never be uploaded is visible rather than silently absent.
- A process killed mid-upload leaves rows in `UPLOADING`. Every sync pass starts
  by returning those to `PENDING`, so an interrupted upload cannot strand a
  message permanently.
- Every sync pass prunes `SYNCED` rows whose `synced_at` is older than the
  configured retention window (default 30 days; `0` keeps them forever). Only
  server-confirmed rows are eligible, so pruning can never drop a message that
  exists nowhere else.
- Because the message `id` is the primary key on **both** sides, a retry after
  a lost response is harmless — the server resolves it to the existing row.
- The `id` is derived from `sender`, `body` and `received_at` rather than drawn
  at random, so the same SMS always produces the same id. That is what lets a
  broadcast delivered twice, and the inbox sweep re-reading a message the
  broadcast already captured, collapse onto one row instead of uploading twice.

---

## ID & Time Conventions

- **UUIDs everywhere** (v4). Message IDs originate on the device; device and
  API-key IDs originate on the server.
- **Server timestamps** are `TIMESTAMPTZ` (UTC). **Room timestamps** are epoch
  millis (`Long`), converted to ISO 8601 at the API boundary.
- `received_at` = when the phone received the SMS; `created_at` = when the
  server persisted it. Both are kept — the gap between them measures sync lag.
