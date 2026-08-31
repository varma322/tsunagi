"""add audit_events

A durable, append-only record of noteworthy events -- device and key lifecycle,
enrolment, capture health, webhook failures -- as opposed to the capped,
transient event log the bus keeps for the live dashboard.

Revision ID: 0006
Revises: 0005
Create Date: 2026-08-31
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "audit_events",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("type", sa.String(length=64), nullable=False),
        sa.Column("level", sa.String(length=16), nullable=False),
        sa.Column("payload", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("idx_audit_events_created_at", "audit_events", ["created_at"])
    op.create_index("idx_audit_events_type", "audit_events", ["type"])


def downgrade() -> None:
    op.drop_index("idx_audit_events_type", table_name="audit_events")
    op.drop_index("idx_audit_events_created_at", table_name="audit_events")
    op.drop_table("audit_events")
