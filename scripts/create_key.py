#!/usr/bin/env python3
"""Mint an API key directly against the configured database.

The startup key is shown once and only its hash is stored, so there is no way
to read it back if it was lost. This is the recovery path: run it on the server
host, where filesystem access already implies full control.

    python scripts/create_key.py --name laptop --scope admin

Reads the same TSUNAGI_* settings as the app, including backend/.env.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
# Works both from a checkout (scripts/ beside backend/) and inside the API
# image, where scripts/ sits next to app/ in the working directory.
BACKEND = next(
    (
        candidate
        for candidate in (_HERE.parent / "backend", _HERE.parent, Path.cwd())
        if (candidate / "app").is_dir()
    ),
    None,
)
if BACKEND is None:  # pragma: no cover - misconfigured invocation
    sys.exit("Could not locate the backend package (no app/ directory found).")

# Settings and the default SQLite URL are both relative to the backend
# directory, so run from there no matter where this was invoked.
os.chdir(BACKEND)
sys.path.insert(0, str(BACKEND))

from app.config import get_settings  # noqa: E402
from app.db import dispose_engine, ensure_schema, get_session_factory  # noqa: E402
from app.events import EventBus  # noqa: E402
from app.services import ApiKeyService  # noqa: E402


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", default="recovered-admin", help="Label for the key")
    parser.add_argument("--scope", default="admin", choices=["user", "admin"])
    parser.add_argument(
        "--revoke-existing",
        action="store_true",
        help="Revoke every other active key, e.g. when the old one may be compromised",
    )
    args = parser.parse_args()

    settings = get_settings()
    print(f"database: {settings.database_url}")

    if settings.auto_create_schema:
        await ensure_schema()

    async with get_session_factory()() as session:
        service = ApiKeyService(session, EventBus())

        if args.revoke_existing:
            for existing in await service.list_keys():
                if existing.revoked_at is None:
                    await service.revoke(existing)
                    print(f"revoked {existing.name!r}")

        _record, raw = await service.create(args.name, args.scope)

    await dispose_engine()

    print()
    print(f"Created {args.scope} key {args.name!r}. Copy it now — it is not stored:")
    print()
    print(f"    {raw}")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
