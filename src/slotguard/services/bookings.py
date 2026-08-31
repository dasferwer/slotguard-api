from datetime import UTC, datetime
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import Select, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from slotguard.models import Booking, BookingStatus, Room, User, UserRole
from slotguard.schemas.booking import BookingCreate, BookingUpdate
from slotguard.services.audit import add_audit_log


def _get_active_room(db: Session, room_id: UUID) -> Room:
    room = db.get(Room, room_id)
    if room is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Room not found")
    if not room.is_active:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Room is inactive")
    return room


def get_booking(db: Session, booking_id: UUID) -> Booking:
    booking = db.get(Booking, booking_id)
    if booking is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Booking not found")
    return booking


def ensure_booking_access(booking: Booking, current_user: User) -> None:
    if current_user.role != UserRole.ADMIN and booking.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Booking not found")


def _overlap_exists(
    db: Session,
    *,
    room_id: UUID,
    starts_at: datetime,
    ends_at: datetime,
    exclude_booking_id: UUID | None = None,
) -> bool:
    query = select(Booking.id).where(
        Booking.room_id == room_id,
        Booking.status == BookingStatus.ACTIVE,
        Booking.starts_at < ends_at,
        Booking.ends_at > starts_at,
    )
    if exclude_booking_id is not None:
        query = query.where(Booking.id != exclude_booking_id)
    return db.scalar(query.limit(1)) is not None


def _commit_booking(db: Session, booking: Booking) -> Booking:
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        if "no_overlapping_active_bookings" in str(exc.orig):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Room is already booked for the selected period",
            ) from exc
        raise
    db.refresh(booking)
    return booking


def create_booking(db: Session, payload: BookingCreate, current_user: User) -> Booking:
    _get_active_room(db, payload.room_id)
    if _overlap_exists(
        db,
        room_id=payload.room_id,
        starts_at=payload.starts_at,
        ends_at=payload.ends_at,
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Room is already booked for the selected period",
        )

    booking = Booking(
        room_id=payload.room_id,
        user_id=current_user.id,
        starts_at=payload.starts_at,
        ends_at=payload.ends_at,
        purpose=payload.purpose,
        status=BookingStatus.ACTIVE,
    )
    db.add(booking)
    db.flush()
    add_audit_log(
        db,
        actor_id=current_user.id,
        action="booking.created",
        entity_type="booking",
        entity_id=booking.id,
        details={"room_id": str(payload.room_id)},
    )
    return _commit_booking(db, booking)


def update_booking(
    db: Session,
    booking: Booking,
    payload: BookingUpdate,
    current_user: User,
) -> Booking:
    ensure_booking_access(booking, current_user)
    if booking.status != BookingStatus.ACTIVE:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cancelled booking cannot be changed",
        )

    starts_at = payload.starts_at or booking.starts_at
    ends_at = payload.ends_at or booking.ends_at
    if ends_at <= starts_at:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="ends_at must be later than starts_at",
        )
    if payload.starts_at is not None and starts_at <= datetime.now(UTC):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="starts_at must be in the future",
        )
    if _overlap_exists(
        db,
        room_id=booking.room_id,
        starts_at=starts_at,
        ends_at=ends_at,
        exclude_booking_id=booking.id,
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Room is already booked for the selected period",
        )

    booking.starts_at = starts_at
    booking.ends_at = ends_at
    if payload.purpose is not None:
        booking.purpose = payload.purpose
    add_audit_log(
        db,
        actor_id=current_user.id,
        action="booking.updated",
        entity_type="booking",
        entity_id=booking.id,
    )
    return _commit_booking(db, booking)


def cancel_booking(db: Session, booking: Booking, current_user: User) -> Booking:
    ensure_booking_access(booking, current_user)
    if booking.status == BookingStatus.CANCELLED:
        return booking

    booking.status = BookingStatus.CANCELLED
    add_audit_log(
        db,
        actor_id=current_user.id,
        action="booking.cancelled",
        entity_type="booking",
        entity_id=booking.id,
    )
    return _commit_booking(db, booking)


def list_bookings(
    db: Session,
    *,
    current_user: User,
    room_id: UUID | None,
    requested_user_id: UUID | None,
    booking_status: BookingStatus | None,
    limit: int,
    offset: int,
) -> tuple[list[Booking], int]:
    filters = []
    if current_user.role != UserRole.ADMIN:
        filters.append(Booking.user_id == current_user.id)
    elif requested_user_id is not None:
        filters.append(Booking.user_id == requested_user_id)
    if room_id is not None:
        filters.append(Booking.room_id == room_id)
    if booking_status is not None:
        filters.append(Booking.status == booking_status)

    query: Select[tuple[Booking]] = select(Booking).where(*filters)
    count_query = select(func.count()).select_from(Booking).where(*filters)
    items = list(
        db.scalars(query.order_by(Booking.starts_at.asc()).limit(limit).offset(offset)).all()
    )
    total = db.scalar(count_query) or 0
    return items, total
