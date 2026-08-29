"""Message export.

An export is the one response whose size is bounded by the database rather than
by a page limit, so these cover what that implies: it streams, it takes the same
filters as the list endpoint but no limit, and it survives message bodies that
contain the characters CSV is made of.
"""

import csv
import io
import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app import export as export_module
from tests.conftest import make_message


@pytest.fixture
def loaded(client, device):
    """A device with three messages, uploaded oldest first."""
    base = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)
    sent = []
    for index in range(3):
        message = make_message(sender=f"+1555000000{index}", body=f"export probe {index}")
        message["received_at"] = (base + timedelta(minutes=index)).isoformat()
        response = client.post("/api/v1/messages", json=message, headers=device["headers"])
        assert response.status_code == 201, response.text
        sent.append(message)
    return {"device": device, "messages": sent}


def rows(response) -> list[dict]:
    return list(csv.DictReader(io.StringIO(response.text)))


def export(client, headers, **params):
    return client.get("/api/v1/messages/export", params=params, headers=headers)


# --- csv ------------------------------------------------------------------


def test_csv_is_the_default_format(client, loaded, user_headers):
    response = export(client, user_headers, device_id=loaded["device"]["id"])

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert "attachment" in response.headers["content-disposition"]
    assert ".csv" in response.headers["content-disposition"]


def test_csv_carries_every_matching_message(client, loaded, user_headers):
    exported = rows(export(client, user_headers, device_id=loaded["device"]["id"]))

    assert [row["body"] for row in exported] == [
        "export probe 0",
        "export probe 1",
        "export probe 2",
    ]
    assert exported[0]["sender"] == "+15550000000"
    assert exported[0]["device_id"] == loaded["device"]["id"]


def test_export_is_oldest_first(client, loaded, user_headers):
    """The opposite of the list endpoint, and deliberately: a file is read from
    the top, and a backup that starts at the newest message reads backwards."""
    exported = rows(export(client, user_headers, device_id=loaded["device"]["id"]))
    stamps = [row["received_at"] for row in exported]

    assert stamps == sorted(stamps)


def test_a_body_full_of_csv_characters_survives(client, device, user_headers):
    """The reason this goes through the csv module. A body like this splits into
    extra columns under any hand-rolled writer, and the export loses data
    without failing."""
    nasty = 'comma, "quoted", and\na newline'
    message = make_message(body=nasty)
    client.post("/api/v1/messages", json=message, headers=device["headers"])

    exported = rows(export(client, user_headers, device_id=device["id"]))

    assert len(exported) == 1
    assert exported[0]["body"] == nasty


def test_an_empty_export_is_a_header_and_nothing_else(client, device, user_headers):
    response = export(client, user_headers, device_id=device["id"])

    assert response.status_code == 200
    assert response.text.strip() == "id,device_id,sender,body,received_at,created_at"


# --- json -----------------------------------------------------------------


def test_json_export_parses(client, loaded, user_headers):
    response = export(client, user_headers, format="json", device_id=loaded["device"]["id"])

    assert response.headers["content-type"].startswith("application/json")
    body = json.loads(response.text)
    assert [message["body"] for message in body["messages"]] == [
        "export probe 0",
        "export probe 1",
        "export probe 2",
    ]


def test_an_empty_json_export_is_still_valid_json(client, device, user_headers):
    body = json.loads(export(client, user_headers, format="json", device_id=device["id"]).text)

    assert body == {"messages": []}


def test_json_timestamps_carry_a_zone(client, loaded, user_headers):
    """A timestamp with no zone in an export is one the reader guesses about."""
    body = json.loads(
        export(client, user_headers, format="json", device_id=loaded["device"]["id"]).text
    )

    assert body["messages"][0]["received_at"].endswith("+00:00")


def test_an_unknown_format_is_refused(client, user_headers):
    assert export(client, user_headers, format="xlsx").status_code == 422


# --- filters --------------------------------------------------------------


def test_the_sender_filter_applies(client, loaded, user_headers):
    # Scoped to this device as well: the test database is shared for the
    # session, so every other test using this fixture has left a message from
    # the same sender behind.
    exported = rows(
        export(
            client,
            user_headers,
            device_id=loaded["device"]["id"],
            sender="+15550000001",
        )
    )

    assert [row["body"] for row in exported] == ["export probe 1"]


def test_the_time_window_applies(client, loaded, user_headers):
    exported = rows(
        export(
            client,
            user_headers,
            device_id=loaded["device"]["id"],
            after="2026-03-01T12:00:30+00:00",
        )
    )

    assert [row["body"] for row in exported] == ["export probe 1", "export probe 2"]


def test_the_search_filter_applies(client, loaded, user_headers):
    exported = rows(
        export(client, user_headers, device_id=loaded["device"]["id"], query="probe 2")
    )

    assert [row["body"] for row in exported] == ["export probe 2"]


def test_an_unknown_device_exports_nothing_rather_than_everything(client, loaded, user_headers):
    exported = rows(export(client, user_headers, device_id=str(uuid.uuid4())))

    assert exported == []


# --- streaming ------------------------------------------------------------


def test_every_message_survives_the_chunk_boundary(client, device, user_headers, monkeypatch):
    """The export pages by keyset, so a row landing exactly on a boundary is
    where it would be skipped or sent twice. Five messages over chunks of two
    crosses two boundaries."""
    monkeypatch.setattr(export_module, "CHUNK", 2)
    base = datetime(2026, 4, 1, 9, 0, tzinfo=UTC)
    for index in range(5):
        message = make_message(body=f"chunked {index}")
        message["received_at"] = (base + timedelta(seconds=index)).isoformat()
        client.post("/api/v1/messages", json=message, headers=device["headers"])

    exported = rows(export(client, user_headers, device_id=device["id"]))

    assert [row["body"] for row in exported] == [f"chunked {index}" for index in range(5)]


def test_messages_sharing_a_timestamp_are_not_lost_at_a_boundary(
    client, device, user_headers, monkeypatch
):
    """The keyset is (received_at, id) rather than received_at alone. With a
    timestamp shared across the boundary, comparing on time only would drop
    every row that shares it with the last one sent."""
    monkeypatch.setattr(export_module, "CHUNK", 2)
    same = datetime(2026, 4, 2, 9, 0, tzinfo=UTC).isoformat()
    for index in range(5):
        message = make_message(body=f"tied {index}")
        message["received_at"] = same
        client.post("/api/v1/messages", json=message, headers=device["headers"])

    exported = rows(export(client, user_headers, device_id=device["id"]))

    assert sorted(row["body"] for row in exported) == [f"tied {index}" for index in range(5)]


# --- authorization --------------------------------------------------------


def test_export_requires_a_reader(client):
    assert client.get("/api/v1/messages/export").status_code == 401


def test_a_device_cannot_export(client, device):
    """A phone uploads; it has no business reading the whole archive back."""
    assert export(client, device["headers"]).status_code == 403
