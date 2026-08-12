"""initial schema: devices, messages, api_keys

Revision ID: 0001
Revises:
Create Date: 2026-08-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

FTS_INDEX = "idx_messages_body_fts"


def upgrade() -> None:
    op.create_table(
        "devices",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("token_hash", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("token_hash", name="uq_devices_token_hash"),
    )
    op.create_index("ix_devices_token_hash", "devices", ["token_hash"])
    op.create_index("idx_devices_last_seen", "devices", [sa.text("last_seen DESC")])

    op.create_table(
        "messages",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("device_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("sender", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["device_id"], ["devices.id"], name="fk_messages_device_id", ondelete="CASCADE"
        ),
    )
    op.create_index("idx_messages_received_at", "messages", [sa.text("received_at DESC")])
    op.create_index(
        "idx_messages_device_received", "messages", ["device_id", sa.text("received_at DESC")]
    )
    op.create_index("idx_messages_sender", "messages", ["sender"])

    op.create_table(
        "api_keys",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("key_hash", sa.String(length=128), nullable=False),
        sa.Column("scope", sa.String(length=16), nullable=False, server_default="user"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("key_hash", name="uq_api_keys_key_hash"),
    )
    op.create_index("ix_api_keys_key_hash", "api_keys", ["key_hash"])

    # Full-text search index. Other dialects fall back to a LIKE scan in the
    # repository layer, so the index is PostgreSQL-only by design.
    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            f"CREATE INDEX {FTS_INDEX} ON messages "
            "USING GIN (to_tsvector('simple', body))"
        )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(f"DROP INDEX IF EXISTS {FTS_INDEX}")

    op.drop_index("ix_api_keys_key_hash", table_name="api_keys")
    op.drop_table("api_keys")

    op.drop_index("idx_messages_sender", table_name="messages")
    op.drop_index("idx_messages_device_received", table_name="messages")
    op.drop_index("idx_messages_received_at", table_name="messages")
    op.drop_table("messages")

    op.drop_index("idx_devices_last_seen", table_name="devices")
    op.drop_index("ix_devices_token_hash", table_name="devices")
    op.drop_table("devices")
