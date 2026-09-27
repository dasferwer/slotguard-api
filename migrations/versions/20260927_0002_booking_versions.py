"""Добавить версии броней и сохранённые ответы на повторные запросы."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260927_0002"
down_revision = "20260831_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "bookings", sa.Column("version", sa.Integer(), server_default="1", nullable=False)
    )
    op.create_check_constraint("ck_bookings_positive_version", "bookings", "version > 0")
    op.create_table(
        "booking_requests",
        sa.Column(
            "user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), primary_key=True
        ),
        sa.Column("key", sa.String(128), primary_key=True),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("response", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )


def downgrade() -> None:
    op.drop_table("booking_requests")
    op.drop_constraint("ck_bookings_positive_version", "bookings")
    op.drop_column("bookings", "version")
