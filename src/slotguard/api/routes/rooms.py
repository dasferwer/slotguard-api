from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Query, Response, status
from sqlalchemy import func, select

from slotguard.api.dependencies import AdminUser, CurrentUser, DbSession
from slotguard.models import Booking, BookingStatus, Room, UserRole
from slotguard.schemas.room import RoomCreate, RoomList, RoomRead, RoomUpdate
from slotguard.services.audit import add_audit_log
from slotguard.services.bookings import lock_room
from slotguard.services.transactions import integrity_errors

router = APIRouter(prefix="/rooms", tags=["rooms"])


def _get_room(db: DbSession, room_id: UUID) -> Room:
    room = db.get(Room, room_id)
    if room is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Room not found")
    return room


@router.get("", response_model=RoomList)
def list_rooms(
    db: DbSession,
    current_user: CurrentUser,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
    include_inactive: bool = False,
) -> RoomList:
    filters = []
    if current_user.role != UserRole.ADMIN or not include_inactive:
        filters.append(Room.is_active.is_(True))
    query = select(Room).where(*filters)
    count_query = select(func.count()).select_from(Room).where(*filters)
    items = list(db.scalars(query.order_by(Room.name).limit(limit).offset(offset)).all())
    return RoomList(
        items=items,
        total=db.scalar(count_query) or 0,
        limit=limit,
        offset=offset,
    )


@router.get("/{room_id}", response_model=RoomRead)
def read_room(room_id: UUID, db: DbSession, current_user: CurrentUser) -> Room:
    room = _get_room(db, room_id)
    if not room.is_active and current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Room not found")
    return room


@router.post("", response_model=RoomRead, status_code=status.HTTP_201_CREATED)
def create_room(payload: RoomCreate, db: DbSession, admin: AdminUser) -> Room:
    room = Room(id=uuid4(), **payload.model_dump())
    with integrity_errors(db):
        db.add(room)
        db.flush()
        add_audit_log(
            db,
            actor_id=admin.id,
            action="room.created",
            entity_type="room",
            entity_id=room.id,
        )
        db.commit()
    db.refresh(room)
    return room


@router.patch("/{room_id}", response_model=RoomRead)
def update_room(
    room_id: UUID,
    payload: RoomUpdate,
    db: DbSession,
    admin: AdminUser,
) -> Room:
    room = lock_room(db, room_id)
    if payload.is_active is False:
        ensure_no_bookings(db, room_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(room, field, value)
    add_audit_log(
        db,
        actor_id=admin.id,
        action="room.updated",
        entity_type="room",
        entity_id=room.id,
    )
    with integrity_errors(db):
        db.commit()
    db.refresh(room)
    return room


def ensure_no_bookings(db: DbSession, room_id: UUID) -> None:
    occupied = db.scalar(
        select(Booking.id)
        .where(
            Booking.room_id == room_id,
            Booking.status == BookingStatus.ACTIVE,
            Booking.ends_at > datetime.now(UTC),
        )
        .limit(1)
    )
    if occupied is not None:
        raise HTTPException(status_code=409, detail="Сначала отмените незавершённые брони комнаты")


@router.delete("/{room_id}", status_code=status.HTTP_204_NO_CONTENT)
def deactivate_room(room_id: UUID, db: DbSession, admin: AdminUser) -> Response:
    room = lock_room(db, room_id)
    if room.is_active:
        ensure_no_bookings(db, room_id)
        room.is_active = False
        add_audit_log(
            db,
            actor_id=admin.id,
            action="room.deactivated",
            entity_type="room",
            entity_id=room.id,
        )
        db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
