"""single-use enrolment tokens

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "enrolment_tokens",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("code_hash", sa.String(length=128), nullable=False),
        sa.Column("label", sa.String(length=120), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_key_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("used_by_device_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.UniqueConstraint("code_hash", name="uq_enrolment_tokens_code_hash"),
        sa.ForeignKeyConstraint(
            ["created_by_key_id"],
            ["api_keys.id"],
            name="fk_enrolment_tokens_created_by_key_id",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["used_by_device_id"],
            ["devices.id"],
            name="fk_enrolment_tokens_used_by_device_id",
            ondelete="SET NULL",
        ),
    )
    op.create_index("ix_enrolment_tokens_code_hash", "enrolment_tokens", ["code_hash"])
    op.create_index(
        "idx_enrolment_tokens_created_at", "enrolment_tokens", [sa.text("created_at DESC")]
    )


def downgrade() -> None:
    op.drop_index("idx_enrolment_tokens_created_at", table_name="enrolment_tokens")
    op.drop_index("ix_enrolment_tokens_code_hash", table_name="enrolment_tokens")
    op.drop_table("enrolment_tokens")
