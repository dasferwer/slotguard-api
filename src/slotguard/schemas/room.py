from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class RoomCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(min_length=2, max_length=100)
    location: str = Field(min_length=2, max_length=160)
    capacity: int = Field(ge=1, le=1000)
    description: str | None = Field(default=None, max_length=2000)


class RoomUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str | None = Field(default=None, min_length=2, max_length=100)
    location: str | None = Field(default=None, min_length=2, max_length=160)
    capacity: int | None = Field(default=None, ge=1, le=1000)
    description: str | None = Field(default=None, max_length=2000)
    is_active: bool | None = None

    @model_validator(mode="after")
    def reject_null(self) -> "RoomUpdate":
        if any(getattr(self, field) is None for field in self.model_fields_set - {"description"}):
            raise ValueError("Обязательные поля комнаты не могут быть null")
        return self


class RoomRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    location: str
    capacity: int
    description: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class RoomList(BaseModel):
    items: list[RoomRead]
    total: int
    limit: int
    offset: int
