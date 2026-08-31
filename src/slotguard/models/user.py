from typing import TYPE_CHECKING

from sqlalchemy import Boolean, CheckConstraint, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from slotguard.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from slotguard.models.enums import UserRole

if TYPE_CHECKING:
    from slotguard.models.audit import AuditLog
    from slotguard.models.booking import Booking


class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("role IN ('user', 'admin')", name="ck_users_valid_role"),
        UniqueConstraint("email", name="users_email_key"),
    )

    email: Mapped[str] = mapped_column(String(320), unique=True, index=True, nullable=False)
    full_name: Mapped[str] = mapped_column(String(120), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[UserRole] = mapped_column(
        String(20),
        default=UserRole.USER,
        nullable=False,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    bookings: Mapped[list["Booking"]] = relationship(back_populates="user")
    audit_logs: Mapped[list["AuditLog"]] = relationship(back_populates="actor")
