from datetime import UTC, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from slotguard.models.enums import BookingStatus


def _validate_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must include a timezone")


class BookingCreate(BaseModel):
    room_id: UUID
    starts_at: datetime
    ends_at: datetime
    purpose: str = Field(min_length=3, max_length=500)

    @model_validator(mode="after")
    def validate_period(self) -> "BookingCreate":
        _validate_aware(self.starts_at, "starts_at")
        _validate_aware(self.ends_at, "ends_at")
        if self.ends_at <= self.starts_at:
            raise ValueError("ends_at must be later than starts_at")
        if self.starts_at <= datetime.now(UTC):
            raise ValueError("starts_at must be in the future")
        return self


class BookingUpdate(BaseModel):
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    purpose: str | None = Field(default=None, min_length=3, max_length=500)

    @model_validator(mode="after")
    def validate_timezone(self) -> "BookingUpdate":
        if self.starts_at is not None:
            _validate_aware(self.starts_at, "starts_at")
        if self.ends_at is not None:
            _validate_aware(self.ends_at, "ends_at")
        if (
            self.starts_at is not None
            and self.ends_at is not None
            and self.ends_at <= self.starts_at
        ):
            raise ValueError("ends_at must be later than starts_at")
        return self


class BookingRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    room_id: UUID
    user_id: UUID
    starts_at: datetime
    ends_at: datetime
    purpose: str
    status: BookingStatus
    created_at: datetime
    updated_at: datetime


class BookingList(BaseModel):
    items: list[BookingRead]
    total: int
    limit: int
    offset: int
