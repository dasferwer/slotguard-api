from typing import TYPE_CHECKING

from sqlalchemy import Boolean, CheckConstraint, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from slotguard.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from slotguard.models.booking import Booking


class Room(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "rooms"
    __table_args__ = (
        CheckConstraint("capacity > 0", name="ck_rooms_positive_capacity"),
        UniqueConstraint("name", name="rooms_name_key"),
    )

    name: Mapped[str] = mapped_column(String(100), unique=True, index=True, nullable=False)
    location: Mapped[str] = mapped_column(String(160), nullable=False)
    capacity: Mapped[int] = mapped_column(Integer, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    bookings: Mapped[list["Booking"]] = relationship(back_populates="room")
