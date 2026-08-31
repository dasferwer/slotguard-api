from enum import StrEnum


class UserRole(StrEnum):
    USER = "user"
    ADMIN = "admin"


class BookingStatus(StrEnum):
    ACTIVE = "active"
    CANCELLED = "cancelled"
