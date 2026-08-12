"""Test configuration.

Environment is set before importing the app because settings are cached and the
database engine is built from them on first use.
"""

import os
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest

ADMIN_KEY = "tsn_key_test-admin"
USER_KEY_NAME = "test-user"
SETUP_KEY = "test-setup-key"

_db_path = Path(tempfile.mkdtemp(prefix="tsunagi-test-")) / "test.db"

os.environ["TSUNAGI_DATABASE_URL"] = f"sqlite+aiosqlite:///{_db_path.as_posix()}"
os.environ["TSUNAGI_SETUP_KEY"] = SETUP_KEY
os.environ["TSUNAGI_BOOTSTRAP_API_KEY"] = ADMIN_KEY
os.environ["TSUNAGI_AUTO_CREATE_SCHEMA"] = "true"
os.environ.pop("TSUNAGI_REDIS_URL", None)

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(scope="session")
def admin_headers():
    return {"Authorization": f"Bearer {ADMIN_KEY}"}


@pytest.fixture(scope="session")
def setup_headers():
    return {"Authorization": f"Bearer {SETUP_KEY}"}


@pytest.fixture(scope="session")
def user_headers(client, admin_headers):
    response = client.post(
        "/api/v1/keys", json={"name": USER_KEY_NAME, "scope": "user"}, headers=admin_headers
    )
    assert response.status_code == 201, response.text
    return {"Authorization": f"Bearer {response.json()['key']}"}


@pytest.fixture
def device(client, setup_headers):
    """A freshly registered device and its auth headers."""
    response = client.post(
        "/api/v1/devices/register",
        json={"device_name": f"Test Phone {uuid.uuid4().hex[:6]}"},
        headers=setup_headers,
    )
    assert response.status_code == 201, response.text
    body = response.json()
    return {
        "id": body["device_id"],
        "token": body["token"],
        "headers": {"Authorization": f"Bearer {body['token']}"},
    }


def make_message(sender: str = "+15551234567", body: str = "hello") -> dict:
    return {
        "id": str(uuid.uuid4()),
        "sender": sender,
        "body": body,
        "received_at": datetime.now(UTC).isoformat(),
    }
