from collections.abc import Iterator
from contextlib import contextmanager

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session


@contextmanager
def integrity_errors(db: Session) -> Iterator[None]:
    try:
        yield
    except IntegrityError as exc:
        db.rollback()
        constraint = getattr(getattr(exc.orig, "diag", None), "constraint_name", None)
        messages = {
            "no_overlapping_active_bookings": "Комната уже забронирована на это время",
            "rooms_name_key": "Комната с таким названием уже существует",
            "users_email_key": "Этот email уже зарегистрирован",
        }
        if constraint in messages:
            raise HTTPException(status_code=409, detail=messages[constraint]) from exc
        raise
