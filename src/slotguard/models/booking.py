from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from slotguard.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from slotguard.models.enums import BookingStatus

if TYPE_CHECKING:
    from slotguard.models.room import Room
    from slotguard.models.user import User


class Booking(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "bookings"
    __table_args__ = (
        CheckConstraint("ends_at > starts_at", name="ck_bookings_valid_period"),
        CheckConstraint(
            "status IN ('active', 'cancelled')",
            name="ck_bookings_valid_status",
        ),
        Index("ix_bookings_room_period", "room_id", "starts_at", "ends_at"),
        Index("ix_bookings_user_created", "user_id", "created_at"),
    )

    room_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("rooms.id", ondelete="RESTRICT"),
        nullable=False,
    )
    user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    purpose: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[BookingStatus] = mapped_column(
        String(20),
        default=BookingStatus.ACTIVE,
        nullable=False,
    )

    room: Mapped["Room"] = relationship(back_populates="bookings")
    user: Mapped["User"] = relationship(back_populates="bookings")
