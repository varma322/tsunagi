"""Streaming exports of stored messages.

Written as generators over chunks rather than as one rendered string: an export
is the one endpoint whose response size is bounded by the size of the database
rather than by a page limit, and holding a year of messages in memory to hand
them to the client would be a way to run a server out of it.
"""

from __future__ import annotations

import csv
import io
import json
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime

from app.models import Message

#: Rows fetched per query while streaming. Large enough that a big export is
#: not a thousand round trips, small enough that one chunk in memory is cheap.
#: Tests lower it to exercise the keyset boundary between chunks.
CHUNK = 1000

#: Column order for CSV, and the field order for JSON objects.
FIELDS = ("id", "device_id", "sender", "body", "received_at", "created_at")


def _row(message: Message) -> dict[str, str]:
    return {
        "id": str(message.id),
        "device_id": str(message.device_id),
        "sender": message.sender,
        "body": message.body,
        "received_at": _isoformat(message.received_at),
        "created_at": _isoformat(message.created_at),
    }


def _isoformat(value: datetime) -> str:
    # Stored naive in SQLite; a timestamp with no zone in an export is a
    # timestamp the reader will guess wrong about.
    return (value if value.tzinfo else value.replace(tzinfo=UTC)).isoformat()


async def as_csv(chunks: AsyncIterator[list[Message]]) -> AsyncIterator[str]:
    """CSV with a header row.

    Rendered through the csv module rather than by joining commas: message
    bodies contain commas, quotes and newlines, and a hand-rolled writer turns
    one of those into a file that silently loses columns.
    """
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=FIELDS, lineterminator="\n")
    writer.writeheader()
    yield _drain(buffer)

    async for messages in chunks:
        for message in messages:
            writer.writerow(_row(message))
        yield _drain(buffer)


async def as_json(chunks: AsyncIterator[list[Message]]) -> AsyncIterator[str]:
    """A single JSON object, streamed.

    Shaped like the list endpoint's response so the same reader handles both,
    but without `total`: counting first would mean a second full scan to tell
    the client something it learns by reading to the end.
    """
    yield '{"messages":['
    first = True
    async for messages in chunks:
        parts = []
        for message in messages:
            parts.append(("" if first else ",") + json.dumps(_row(message)))
            first = False
        if parts:
            yield "".join(parts)
    yield "]}"


def _drain(buffer: io.StringIO) -> str:
    text = buffer.getvalue()
    buffer.seek(0)
    buffer.truncate(0)
    return text


#: format name -> (renderer, media type, file extension)
FORMATS: dict[str, tuple[Callable[[AsyncIterator[list[Message]]], AsyncIterator[str]], str, str]] = {
    "csv": (as_csv, "text/csv; charset=utf-8", "csv"),
    "json": (as_json, "application/json", "json"),
}


def filename(format_: str, now: datetime | None = None) -> str:
    stamp = (now or datetime.now(UTC)).strftime("%Y%m%d-%H%M%S")
    return f"tsunagi-messages-{stamp}.{FORMATS[format_][2]}"
