from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, status

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
def create(payload: BookingCreate, db: DbSession, current_user: CurrentUser) -> Booking:
    return create_booking(db, payload, current_user)


@router.get("/{booking_id}", response_model=BookingRead)
def read(booking_id: UUID, db: DbSession, current_user: CurrentUser) -> Booking:
    booking = get_booking(db, booking_id)
    ensure_booking_access(booking, current_user)
    return booking


@router.patch("/{booking_id}", response_model=BookingRead)
def update(
    booking_id: UUID,
    payload: BookingUpdate,
    db: DbSession,
    current_user: CurrentUser,
) -> Booking:
    booking = get_booking(db, booking_id)
    return update_booking(db, booking, payload, current_user)


@router.post("/{booking_id}/cancel", response_model=BookingRead)
def cancel(booking_id: UUID, db: DbSession, current_user: CurrentUser) -> Booking:
    booking = get_booking(db, booking_id)
    return cancel_booking(db, booking, current_user)
