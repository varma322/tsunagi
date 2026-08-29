"""add webhooks

An HTTP endpoint told about events as they happen, for integrations that have no
browser to hold a WebSocket open and no reason to poll.

Revision ID: 0005
Revises: 0004
Create Date: 2026-08-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "webhooks",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("url", sa.String(length=2048), nullable=False),
        sa.Column("description", sa.String(length=120), nullable=True),
        sa.Column("secret", sa.String(length=128), nullable=False),
        sa.Column("events", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_delivery_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_status", sa.Integer(), nullable=True),
        sa.Column("last_error", sa.String(length=500), nullable=True),
        sa.Column("failure_count", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_table("webhooks")
