"""Per-message batch results.

The failure these exist for: one message the server will not accept used to
reject every message it travelled with, and the response could not say which
one was at fault. The phone had to find the offender by re-uploading the batch
one message at a time.

The opt-in is as important as the feature. A client that does not read the
results would read 200 as "all stored" and drop the message the server refused,
which is the one outcome this project does not tolerate.
"""

import uuid

from tests.conftest import make_message


def bad_message(**overrides) -> dict:
    message = make_message()
    message["sender"] = ""  # rejected: the sender must not be empty
    message.update(overrides)
    return message


def upload(client, device, messages, partial=None):
    body: dict = {"messages": messages}
    if partial is not None:
        body["partial"] = partial
    return client.post("/api/v1/messages/batch", json=body, headers=device["headers"])


# --- the default is unchanged ---------------------------------------------


def test_one_bad_message_still_rejects_the_batch_by_default(client, device, user_headers):
    good = make_message(body="innocent bystander")

    response = upload(client, device, [good, bad_message()])

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"

    # Nothing was stored: an all-or-nothing rejection has to be all.
    listed = client.get(
        "/api/v1/messages", params={"device_id": device["id"]}, headers=user_headers
    )
    assert listed.json()["total"] == 0


def test_the_rejection_names_the_message_at_fault(client, device):
    response = upload(client, device, [make_message(), bad_message()])

    # Which one, and why — the old response said neither.
    assert "messages.1.sender" in response.json()["error"]["message"]


# --- opting in ------------------------------------------------------------


def test_partial_stores_the_good_and_reports_the_bad(client, device, user_headers):
    good = make_message(body="goes up regardless")

    response = upload(client, device, [good, bad_message()], partial=True)

    assert response.status_code == 200
    body = response.json()
    assert (body["accepted"], body["created"], body["rejected"]) == (2, 1, 1)

    listed = client.get(
        "/api/v1/messages", params={"device_id": device["id"]}, headers=user_headers
    )
    assert listed.json()["total"] == 1


def test_every_message_gets_a_verdict_in_request_order(client, device):
    first = make_message()
    third = make_message()

    body = upload(client, device, [first, bad_message(), third], partial=True).json()

    assert [result["index"] for result in body["results"]] == [0, 1, 2]
    assert [result["status"] for result in body["results"]] == [
        "created",
        "rejected",
        "created",
    ]
    assert body["results"][0]["id"] == first["id"]


def test_a_rejected_message_carries_its_id_so_the_phone_can_match_it(client, device):
    offender = bad_message()

    body = upload(client, device, [offender], partial=True).json()

    rejected = body["results"][0]
    assert rejected["id"] == offender["id"]
    assert "sender" in rejected["error"]


def test_an_unreadable_id_is_reported_without_one(client, device):
    """The id is what a client matches a verdict to its own row. When that is
    the broken field there is nothing to match on, and inventing one would be
    worse than saying so."""
    body = upload(client, device, [bad_message(id="not-a-uuid")], partial=True).json()

    assert body["results"][0]["id"] is None
    assert body["results"][0]["index"] == 0


def test_duplicates_are_distinguished_from_new_messages(client, device):
    shared = make_message()
    upload(client, device, [shared], partial=True)

    body = upload(client, device, [shared, make_message()], partial=True).json()

    assert [result["status"] for result in body["results"]] == ["duplicate", "created"]
    assert (body["created"], body["duplicates"], body["rejected"]) == (1, 1, 0)


def test_a_wholly_bad_batch_is_reported_rather_than_refused(client, device):
    body = upload(client, device, [bad_message(), bad_message()], partial=True).json()

    assert (body["created"], body["rejected"]) == (0, 2)
    assert all(result["status"] == "rejected" for result in body["results"])


def test_a_clean_partial_batch_reports_no_rejections(client, device):
    body = upload(client, device, [make_message(), make_message()], partial=True).json()

    assert body["rejected"] == 0
    assert all(result["status"] == "created" for result in body["results"])


# --- limits still apply ---------------------------------------------------


def test_partial_does_not_lift_the_batch_size_cap(client, device):
    response = upload(client, device, [make_message() for _ in range(501)], partial=True)

    assert response.status_code == 422


def test_partial_still_requires_at_least_one_message(client, device):
    assert upload(client, device, [], partial=True).status_code == 422


def test_a_message_that_is_not_an_object_is_rejected_not_fatal(client, device):
    body = upload(client, device, ["nonsense", make_message()], partial=True).json()

    assert body["results"][0]["status"] == "rejected"
    assert body["results"][1]["status"] == "created"


def test_partial_is_still_device_scope_only(client, device, admin_headers):
    response = client.post(
        "/api/v1/messages/batch",
        json={"messages": [make_message()], "partial": True},
        headers=admin_headers,
    )
    assert response.status_code == 403


def test_an_unknown_id_shape_does_not_leak_into_the_stored_row(client, device, user_headers):
    """A rejected message must leave nothing behind, however far it got."""
    offender = bad_message()
    upload(client, device, [offender], partial=True)

    listed = client.get(
        "/api/v1/messages", params={"device_id": device["id"]}, headers=user_headers
    )
    assert all(message["id"] != offender["id"] for message in listed.json()["messages"])
    assert uuid.UUID(offender["id"])
