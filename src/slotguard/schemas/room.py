from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class RoomCreate(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    location: str = Field(min_length=2, max_length=160)
    capacity: int = Field(ge=1, le=1000)
    description: str | None = Field(default=None, max_length=2000)


class RoomUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=100)
    location: str | None = Field(default=None, min_length=2, max_length=160)
    capacity: int | None = Field(default=None, ge=1, le=1000)
    description: str | None = Field(default=None, max_length=2000)
    is_active: bool | None = None


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
