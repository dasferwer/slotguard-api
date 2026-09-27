from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select

from slotguard.db import SessionLocal
from slotguard.models import AuditLog, Booking, BookingRequest, Room


def room(client, admin_headers):
    response = client.post(
        "/api/v1/rooms",
        headers=admin_headers,
        json={
            "name": f"Переговорная {uuid4()}",
            "location": "Тестовый этаж",
            "capacity": 6,
        },
    )
    assert response.status_code == 201
    return response.json()["id"]


def payload(room_id):
    start = datetime.now(UTC) + timedelta(days=20)
    return {
        "room_id": room_id,
        "starts_at": start.isoformat(),
        "ends_at": (start + timedelta(hours=1)).isoformat(),
        "purpose": "Проверка бронирования",
    }


def parallel(*operations):
    barrier = Barrier(len(operations))

    def run(operation):
        barrier.wait(timeout=10)
        return operation()

    with ThreadPoolExecutor(max_workers=len(operations)) as executor:
        return list(executor.map(run, operations))


def create(client, headers, data, key=None):
    return client.post(
        "/api/v1/bookings", json=data, headers={**headers, "Idempotency-Key": key or str(uuid4())}
    )


def test_concurrent_same_key_has_one_booking_and_audit(client, admin_headers, register_user):
    headers = register_user()
    data = payload(room(client, admin_headers))
    key = str(uuid4())
    replies = parallel(*(lambda: create(client, headers, data, key) for _ in range(12)))
    assert [r.status_code for r in replies] == [201] * 12
    assert all(r.json() == replies[0].json() for r in replies)
    booking_id = UUID(replies[0].json()["id"])
    with SessionLocal() as db:
        assert (
            db.scalar(
                select(func.count())
                .select_from(Booking)
                .where(Booking.room_id == UUID(data["room_id"]))
            )
            == 1
        )
        assert (
            db.scalar(
                select(func.count())
                .select_from(AuditLog)
                .where(AuditLog.entity_id == booking_id, AuditLog.action == "booking.created")
            )
            == 1
        )
    changed = {**data, "purpose": "Другой запрос"}
    assert create(client, headers, changed, key).status_code == 409
    assert (
        client.post(
            f"/api/v1/bookings/{booking_id}/cancel", headers={**headers, "If-Match": '"1"'}
        ).status_code
        == 200
    )
    assert create(client, headers, data, key).json() == replies[0].json()


def test_overlap_is_conflict_and_adjacent_interval_allowed(client, admin_headers, register_user):
    headers = register_user()
    data = payload(room(client, admin_headers))
    replies = parallel(*(lambda: create(client, headers, data) for _ in range(8)))
    assert sorted(r.status_code for r in replies) == [201] + [409] * 7
    next_data = {
        **data,
        "starts_at": data["ends_at"],
        "ends_at": (datetime.fromisoformat(data["ends_at"]) + timedelta(hours=1)).isoformat(),
    }
    assert create(client, headers, next_data).status_code == 201


def test_update_and_cancel_cannot_overwrite_each_other(client, admin_headers, register_user):
    headers = register_user()
    data = payload(room(client, admin_headers))
    booking = create(client, headers, data).json()
    path = f"/api/v1/bookings/{booking['id']}"
    version_headers = {**headers, "If-Match": '"1"'}
    replies = parallel(
        lambda: client.patch(path, headers=version_headers, json={"purpose": "Перенос обсуждения"}),
        lambda: client.post(path + "/cancel", headers=version_headers),
    )
    assert sorted(r.status_code for r in replies) == [200, 412]
    assert client.get(path, headers=headers).json()["version"] == 2
    assert client.patch(path, headers=headers, json={"purpose": "Без версии"}).status_code == 428
    assert client.post(path + "/cancel", headers={**headers, "If-Match": "*"}).status_code == 400
    cancelled = client.post(path + "/cancel", headers={**headers, "If-Match": '"2"'})
    assert cancelled.status_code == 200
    assert (
        client.post(
            path + "/cancel",
            headers={
                **headers,
                "If-Match": f'"{cancelled.json()["version"]}"',
            },
        ).json()
        == cancelled.json()
    )


@pytest.mark.parametrize("method", ["delete", "patch"])
def test_deactivation_races_creation(client, admin_headers, register_user, method):
    headers = register_user()
    room_id = room(client, admin_headers)
    data = payload(room_id)

    def deactivate():
        if method == "delete":
            return client.delete(f"/api/v1/rooms/{room_id}", headers=admin_headers)
        return client.patch(
            f"/api/v1/rooms/{room_id}", headers=admin_headers, json={"is_active": False}
        )

    made, disabled = parallel(lambda: create(client, headers, data), deactivate)
    assert (made.status_code, disabled.status_code) in [(201, 409), (409, 204), (409, 200)]
    with SessionLocal() as db:
        stored_room = db.get(Room, UUID(room_id))
        active_count = db.scalar(
            select(func.count())
            .select_from(Booking)
            .where(Booking.room_id == UUID(room_id), Booking.status == "active")
        )
        assert stored_room.is_active or active_count == 0


def test_room_requires_cancellation_before_deactivation(client, admin_headers, register_user):
    headers = register_user()
    room_id = room(client, admin_headers)
    booking = create(client, headers, payload(room_id)).json()
    assert client.delete(f"/api/v1/rooms/{room_id}", headers=admin_headers).status_code == 409
    assert (
        client.post(
            f"/api/v1/bookings/{booking['id']}/cancel", headers={**headers, "If-Match": '"1"'}
        ).status_code
        == 200
    )
    assert client.delete(f"/api/v1/rooms/{room_id}", headers=admin_headers).status_code == 204
    assert create(client, headers, payload(room_id)).status_code == 409


def test_audit_failure_rolls_back_booking_and_key(
    client, admin_headers, register_user, monkeypatch
):
    headers = register_user()
    data = payload(room(client, admin_headers))
    key = str(uuid4())

    def fail(*args, **kwargs):
        raise RuntimeError("Искусственный сбой аудита")

    with monkeypatch.context() as patch:
        patch.setattr("slotguard.services.bookings.add_audit_log", fail)
        with pytest.raises(RuntimeError, match="Искусственный сбой аудита"):
            create(client, headers, data, key)
    with SessionLocal() as db:
        assert (
            db.scalar(
                select(func.count())
                .select_from(Booking)
                .where(Booking.room_id == UUID(data["room_id"]))
            )
            == 0
        )
        assert (
            db.scalar(
                select(func.count()).select_from(BookingRequest).where(BookingRequest.key == key)
            )
            == 0
        )
    assert create(client, headers, data, key).status_code == 201


def test_room_and_registration_unique_races(client, admin_headers):
    data = {"name": f"Комната {uuid4()}", "location": "Первый этаж", "capacity": 2}
    replies = parallel(
        *(lambda: client.post("/api/v1/rooms", headers=admin_headers, json=data) for _ in range(4))
    )
    assert sorted(r.status_code for r in replies) == [201, 409, 409, 409]
    user = {
        "email": f"{uuid4()}@example.com",
        "password": "StrongPass123!",
        "full_name": "Тестовый пользователь",
    }
    replies = parallel(*(lambda: client.post("/api/v1/auth/register", json=user) for _ in range(4)))
    assert sorted(r.status_code for r in replies) == [201, 409, 409, 409]


def test_invalid_fields_and_key_scoping(client, admin_headers, register_user):
    headers, other = register_user(), register_user()
    room_id = room(client, admin_headers)
    data = payload(room_id)
    key = str(uuid4())
    original = create(client, headers, data, key).json()
    other_data = payload(room(client, admin_headers))
    assert create(client, other, other_data, key).status_code == 201
    path = f"/api/v1/bookings/{original['id']}"
    assert (
        client.patch(
            path, headers={**other, "If-Match": '"1"'}, json={"purpose": "Чужая бронь"}
        ).status_code
        == 404
    )
    for value in ({"capacity": None}, {"is_active": None}, {"name": "   "}):
        assert (
            client.patch(f"/api/v1/rooms/{room_id}", headers=admin_headers, json=value).status_code
            == 422
        )
    for value in ({}, {"purpose": None}, {"purpose": "   "}):
        assert (
            client.patch(path, headers={**headers, "If-Match": '"1"'}, json=value).status_code
            == 422
        )
    assert client.post("/api/v1/bookings", headers=headers, json=data).status_code == 422
    assert create(client, headers, {**data, "starts_at": "2020-01-01T00:00:00Z"}).status_code == 422


def test_reschedule_conflict_preserves_version_and_audit(client, admin_headers, register_user):
    headers = register_user()
    data = payload(room(client, admin_headers))
    create(client, headers, data)
    next_start = datetime.fromisoformat(data["ends_at"])
    second = create(
        client,
        headers,
        {
            **data,
            "starts_at": next_start.isoformat(),
            "ends_at": (next_start + timedelta(hours=1)).isoformat(),
        },
    ).json()
    path = f"/api/v1/bookings/{second['id']}"
    reply = client.patch(
        path,
        headers={**headers, "If-Match": '"1"'},
        json={
            "starts_at": data["starts_at"],
            "ends_at": data["ends_at"],
        },
    )
    assert reply.status_code == 409
    assert client.get(path, headers=headers).json() == second
    with SessionLocal() as db:
        assert (
            db.scalar(
                select(func.count())
                .select_from(AuditLog)
                .where(
                    AuditLog.entity_id == UUID(second["id"]), AuditLog.action == "booking.updated"
                )
            )
            == 0
        )


def test_lock_timeout_is_retryable_without_partial_write(client, admin_headers, register_user):
    headers = register_user()
    room_id = room(client, admin_headers)
    data = payload(room_id)
    key = str(uuid4())
    with SessionLocal() as locked:
        locked.scalar(select(Room).where(Room.id == UUID(room_id)).with_for_update())
        reply = create(client, headers, data, key)
        assert reply.status_code == 503
        assert reply.headers["Retry-After"] == "1"
    assert create(client, headers, data, key).status_code == 201


def test_database_constraint_protects_writes_outside_service(client, admin_headers, register_user):
    from sqlalchemy.exc import IntegrityError

    headers = register_user()
    data = payload(room(client, admin_headers))
    first = create(client, headers, data).json()
    with SessionLocal() as db:
        db.add(
            Booking(
                room_id=UUID(data["room_id"]),
                user_id=UUID(first["user_id"]),
                starts_at=datetime.fromisoformat(data["starts_at"]),
                ends_at=datetime.fromisoformat(data["ends_at"]),
                purpose="Прямая запись",
            )
        )
        with pytest.raises(IntegrityError) as failure:
            db.commit()
        assert failure.value.orig.diag.constraint_name == "no_overlapping_active_bookings"
        db.rollback()
