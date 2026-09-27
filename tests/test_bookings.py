from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from fastapi.testclient import TestClient


def test_booking_conflict_cancellation_and_visibility(
    client: TestClient,
    register_user: Callable[[str | None], dict[str, str]],
) -> None:
    first_user = register_user()
    second_user = register_user()
    room_response = client.get("/api/v1/rooms", headers=first_user)
    room_id = room_response.json()["items"][0]["id"]
    starts_at = datetime.now(UTC) + timedelta(days=2)
    ends_at = starts_at + timedelta(hours=1)
    booking_payload = {
        "room_id": room_id,
        "starts_at": starts_at.isoformat(),
        "ends_at": ends_at.isoformat(),
        "purpose": "Architecture review",
    }

    create_response = client.post(
        "/api/v1/bookings",
        headers={**first_user, "Idempotency-Key": str(uuid4())},
        json=booking_payload,
    )
    assert create_response.status_code == 201
    booking_id = create_response.json()["id"]

    conflict_payload = {
        **booking_payload,
        "starts_at": (starts_at + timedelta(minutes=30)).isoformat(),
        "ends_at": (ends_at + timedelta(minutes=30)).isoformat(),
        "purpose": "Overlapping interview",
    }
    conflict_response = client.post(
        "/api/v1/bookings",
        headers={**second_user, "Idempotency-Key": str(uuid4())},
        json=conflict_payload,
    )
    assert conflict_response.status_code == 409

    hidden_response = client.get(
        f"/api/v1/bookings/{booking_id}",
        headers=second_user,
    )
    assert hidden_response.status_code == 404

    adjacent_payload = {
        **booking_payload,
        "starts_at": ends_at.isoformat(),
        "ends_at": (ends_at + timedelta(hours=1)).isoformat(),
        "purpose": "Adjacent booking",
    }
    adjacent_response = client.post(
        "/api/v1/bookings",
        headers={**second_user, "Idempotency-Key": str(uuid4())},
        json=adjacent_payload,
    )
    assert adjacent_response.status_code == 201

    cancel_response = client.post(
        f"/api/v1/bookings/{booking_id}/cancel",
        headers={**first_user, "If-Match": '"1"'},
    )
    assert cancel_response.status_code == 200
    assert cancel_response.json()["status"] == "cancelled"

    replacement_response = client.post(
        "/api/v1/bookings",
        headers={**second_user, "Idempotency-Key": str(uuid4())},
        json=booking_payload,
    )
    assert replacement_response.status_code == 201


def test_user_can_reschedule_own_booking(
    client: TestClient,
    register_user: Callable[[str | None], dict[str, str]],
) -> None:
    headers = register_user()
    room_id = client.get("/api/v1/rooms", headers=headers).json()["items"][1]["id"]
    starts_at = datetime.now(UTC) + timedelta(days=4)
    ends_at = starts_at + timedelta(minutes=45)
    create_response = client.post(
        "/api/v1/bookings",
        headers={**headers, "Idempotency-Key": str(uuid4()), "If-Match": '"1"'},
        json={
            "room_id": room_id,
            "starts_at": starts_at.isoformat(),
            "ends_at": ends_at.isoformat(),
            "purpose": "Initial planning",
        },
    )
    booking_id = create_response.json()["id"]
    new_start = starts_at + timedelta(hours=2)
    new_end = new_start + timedelta(hours=1)

    update_response = client.patch(
        f"/api/v1/bookings/{booking_id}",
        headers={**headers, "Idempotency-Key": str(uuid4()), "If-Match": '"1"'},
        json={
            "starts_at": new_start.isoformat(),
            "ends_at": new_end.isoformat(),
            "purpose": "Updated planning session",
        },
    )

    assert update_response.status_code == 200
    assert update_response.json()["purpose"] == "Updated planning session"
    assert update_response.json()["starts_at"] == new_start.isoformat().replace("+00:00", "Z")
