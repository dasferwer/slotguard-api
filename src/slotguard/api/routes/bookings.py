from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status

from slotguard.api.dependencies import CurrentUser, DbSession
from slotguard.models import Booking, BookingStatus
from slotguard.schemas.booking import BookingCreate, BookingList, BookingRead, BookingUpdate
from slotguard.services.bookings import (
    cancel_booking,
    create_booking,
    ensure_booking_access,
    get_booking,
    list_bookings,
    update_booking,
)

router = APIRouter(prefix="/bookings", tags=["bookings"])


def expected_version(if_match: Annotated[str | None, Header()] = None) -> int:
    if if_match is None:
        raise HTTPException(status_code=428, detail="Передайте версию в заголовке If-Match")
    if len(if_match) > 20 or not if_match.startswith('"') or not if_match.endswith('"'):
        raise HTTPException(status_code=400, detail='Ожидается If-Match: "1"')
    value = if_match[1:-1]
    if not value.isascii() or not value.isdigit() or int(value) < 1:
        raise HTTPException(status_code=400, detail="Некорректная версия брони")
    return int(value)


Version = Annotated[int, Depends(expected_version)]


@router.get("", response_model=BookingList)
def read_bookings(
    db: DbSession,
    current_user: CurrentUser,
    room_id: UUID | None = None,
    user_id: UUID | None = None,
    booking_status: Annotated[BookingStatus | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> BookingList:
    items, total = list_bookings(
        db,
        current_user=current_user,
        room_id=room_id,
        requested_user_id=user_id,
        booking_status=booking_status,
        limit=limit,
        offset=offset,
    )
    return BookingList(items=items, total=total, limit=limit, offset=offset)


@router.post("", response_model=BookingRead, status_code=status.HTTP_201_CREATED)
def create(
    payload: BookingCreate,
    db: DbSession,
    current_user: CurrentUser,
    idempotency_key: Annotated[
        str, Header(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$")
    ],
) -> BookingRead:
    return create_booking(db, payload, current_user, idempotency_key)


@router.get("/{booking_id}", response_model=BookingRead)
def read(booking_id: UUID, db: DbSession, current_user: CurrentUser) -> Booking:
    booking = get_booking(db, booking_id)
    ensure_booking_access(booking, current_user)
    return booking


@router.patch("/{booking_id}", response_model=BookingRead)
def update(
    booking_id: UUID,
    payload: BookingUpdate,
    version: Version,
    db: DbSession,
    current_user: CurrentUser,
) -> Booking:
    booking = get_booking(db, booking_id)
    return update_booking(db, booking, payload, current_user, version)


@router.post("/{booking_id}/cancel", response_model=BookingRead)
def cancel(booking_id: UUID, db: DbSession, current_user: CurrentUser, version: Version) -> Booking:
    booking = get_booking(db, booking_id)
    return cancel_booking(db, booking, current_user, version)
