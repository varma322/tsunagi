import hashlib
import secrets
from datetime import UTC, datetime

DEVICE_TOKEN_PREFIX = "tsn_dev_"
API_KEY_PREFIX = "tsn_key_"

# Enrolment codes get typed by hand off a screen, so the alphabet drops every
# character that is misread in that situation: I/1, L, O/0, U/V confusion.
ENROLMENT_ALPHABET = "ABCDEFGHJKMNPQRSTWXYZ23456789"
ENROLMENT_CODE_LENGTH = 8


def generate_device_token() -> str:
    return DEVICE_TOKEN_PREFIX + secrets.token_urlsafe(32)


def generate_api_key() -> str:
    return API_KEY_PREFIX + secrets.token_urlsafe(32)


def generate_enrolment_code() -> str:
    """A short, hand-typeable code, shown grouped as ABCD-EFGH.

    Short by design: ~39 bits is weak for a permanent credential but ample for
    one that is single-use and expires in minutes, and the alternative is a
    32-character string nobody will type correctly.
    """
    raw = "".join(secrets.choice(ENROLMENT_ALPHABET) for _ in range(ENROLMENT_CODE_LENGTH))
    return f"{raw[:4]}-{raw[4:]}"


def normalize_enrolment_code(value: str) -> str:
    """Accept whatever the user typed: spaces, dashes, lower case."""
    return "".join(character for character in value.upper() if character.isalnum())


def looks_like_enrolment_code(value: str) -> bool:
    """Cheap guard so an arbitrary bearer token does not hit the database."""
    normalized = normalize_enrolment_code(value)
    return len(normalized) == ENROLMENT_CODE_LENGTH and all(
        character in ENROLMENT_ALPHABET for character in normalized
    )


def hash_secret(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def secrets_match(candidate: str, expected: str) -> bool:
    return secrets.compare_digest(candidate, expected)


def as_utc(value: datetime | None) -> datetime | None:
    """SQLite drops tzinfo on round-trip; timestamps are always stored as UTC,
    so re-attach it before the value reaches a response model."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
