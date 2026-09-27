import hashlib
import json
from datetime import UTC, datetime
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import Select, func, select, text
from sqlalchemy.orm import Session

from slotguard.models import Booking, BookingRequest, BookingStatus, Room, User, UserRole
from slotguard.schemas.booking import BookingCreate, BookingRead, BookingUpdate
from slotguard.services.audit import add_audit_log
from slotguard.services.transactions import integrity_errors


def lock_room(db: Session, room_id: UUID) -> Room:
    room = db.scalar(
        select(Room)
        .where(Room.id == room_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if room is None:
        raise HTTPException(status_code=404, detail="Комната не найдена")
    return room


def ensure_active(room: Room) -> None:
    if not room.is_active:
        raise HTTPException(status_code=409, detail="Комната деактивирована")


def get_booking(db: Session, booking_id: UUID) -> Booking:
    booking = db.get(Booking, booking_id)
    if booking is None:
        raise HTTPException(status_code=404, detail="Бронь не найдена")
    return booking


def ensure_booking_access(booking: Booking, current_user: User) -> None:
    if current_user.role != UserRole.ADMIN and booking.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Бронь не найдена")


def _lock_booking(db: Session, booking: Booking, user: User, version: int) -> Room:
    ensure_booking_access(booking, user)
    # Единый порядок блокировок исключает взаимную блокировку отмены и переноса.
    room = lock_room(db, booking.room_id)
    db.refresh(booking, with_for_update=True)
    if booking.version != version:
        raise HTTPException(
            status_code=412, detail="Бронь уже изменена; получите актуальную версию"
        )
    return room


def create_booking(
    db: Session,
    payload: BookingCreate,
    current_user: User,
    key: str,
) -> BookingRead:
    normalized = payload.model_dump(mode="json")
    normalized["starts_at"] = payload.starts_at.astimezone(UTC).isoformat()
    normalized["ends_at"] = payload.ends_at.astimezone(UTC).isoformat()
    fingerprint = hashlib.sha256(json.dumps(normalized, sort_keys=True).encode()).hexdigest()
    # Блокировка ключа берётся до комнаты; повтор не ждёт чужую комнату и не создаёт вторую бронь.
    db.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 101))"),
        {"key": f"{current_user.id}:{key}"},
    )
    previous = db.get(BookingRequest, (current_user.id, key))
    if previous is not None:
        if previous.fingerprint != fingerprint:
            raise HTTPException(status_code=409, detail="Ключ уже использован с другим запросом")
        return BookingRead.model_validate(previous.response)
    room = lock_room(db, payload.room_id)
    ensure_active(room)
    if payload.starts_at <= datetime.now(UTC):
        raise HTTPException(status_code=422, detail="Начало брони должно быть в будущем")
    booking = Booking(
        id=uuid4(), user_id=current_user.id, status=BookingStatus.ACTIVE, **payload.model_dump()
    )
    with integrity_errors(db):
        db.add(booking)
        db.flush()
        response = BookingRead.model_validate(booking)
        db.add(
            BookingRequest(
                user_id=current_user.id,
                key=key,
                fingerprint=fingerprint,
                response=response.model_dump(mode="json"),
            )
        )
        add_audit_log(
            db,
            actor_id=current_user.id,
            action="booking.created",
            entity_type="booking",
            entity_id=booking.id,
            details={"room_id": str(room.id), "version": booking.version},
        )
        db.commit()
    return response


def update_booking(
    db: Session,
    booking: Booking,
    payload: BookingUpdate,
    current_user: User,
    version: int,
) -> Booking:
    room = _lock_booking(db, booking, current_user, version)
    ensure_active(room)
    if booking.status != BookingStatus.ACTIVE:
        raise HTTPException(status_code=409, detail="Отменённую бронь нельзя изменить")
    if not payload.model_fields_set or any(
        getattr(payload, field) is None for field in payload.model_fields_set
    ):
        raise HTTPException(status_code=422, detail="Передайте непустые значения изменяемых полей")
    starts_at = payload.starts_at or booking.starts_at
    ends_at = payload.ends_at or booking.ends_at
    if ends_at <= starts_at:
        raise HTTPException(status_code=422, detail="Конец брони должен быть позже начала")
    if payload.starts_at is not None and starts_at <= datetime.now(UTC):
        raise HTTPException(status_code=422, detail="Начало брони должно быть в будущем")
    with integrity_errors(db):
        booking.starts_at, booking.ends_at = starts_at, ends_at
        if payload.purpose is not None:
            booking.purpose = payload.purpose
        booking.version += 1
        add_audit_log(
            db,
            actor_id=current_user.id,
            action="booking.updated",
            entity_type="booking",
            entity_id=booking.id,
            details={"version": booking.version},
        )
        db.commit()
    return booking


def cancel_booking(db: Session, booking: Booking, current_user: User, version: int) -> Booking:
    _lock_booking(db, booking, current_user, version)
    if booking.status == BookingStatus.CANCELLED:
        return booking
    booking.status = BookingStatus.CANCELLED
    booking.version += 1
    add_audit_log(
        db,
        actor_id=current_user.id,
        action="booking.cancelled",
        entity_type="booking",
        entity_id=booking.id,
        details={"version": booking.version},
    )
    db.commit()
    return booking


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
