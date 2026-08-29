"""add capture health columns to devices

A device's last_seen proves it can reach the server, not that it can still
receive SMS, so a phone whose permission was revoked reported healthy. These
columns hold what the phone says about its own capture path.

Nullable with no server default on purpose: an older app never reports them,
and "has not said" must stay distinguishable from "said no".

Revision ID: 0004
Revises: 0003
Create Date: 2026-08-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_COLUMNS = (
    sa.Column("capture_reported_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column("capture_permitted", sa.Boolean(), nullable=True),
    sa.Column("inbox_readable", sa.Boolean(), nullable=True),
    sa.Column("battery_exempt", sa.Boolean(), nullable=True),
    sa.Column("last_captured_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column("last_swept_at", sa.DateTime(timezone=True), nullable=True),
)


def upgrade() -> None:
    for column in _COLUMNS:
        op.add_column("devices", column)


def downgrade() -> None:
    for column in reversed(_COLUMNS):
        op.drop_column("devices", column.name)
