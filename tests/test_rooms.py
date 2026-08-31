from collections.abc import Callable
from uuid import uuid4

from fastapi.testclient import TestClient


def test_users_can_list_rooms_but_only_admin_can_create(
    client: TestClient,
    admin_headers: dict[str, str],
    register_user: Callable[[str | None], dict[str, str]],
) -> None:
    user_headers = register_user()

    list_response = client.get("/api/v1/rooms", headers=user_headers)
    assert list_response.status_code == 200
    assert list_response.json()["total"] >= 3

    payload = {
        "name": f"Room-{uuid4()}",
        "location": "Floor 7",
        "capacity": 6,
        "description": "A new meeting room",
    }
    forbidden_response = client.post(
        "/api/v1/rooms",
        headers=user_headers,
        json=payload,
    )
    assert forbidden_response.status_code == 403

    create_response = client.post(
        "/api/v1/rooms",
        headers=admin_headers,
        json=payload,
    )
    assert create_response.status_code == 201
    assert create_response.json()["name"] == payload["name"]

    deactivate_response = client.delete(
        f"/api/v1/rooms/{create_response.json()['id']}",
        headers=admin_headers,
    )
    assert deactivate_response.status_code == 204

    hidden_response = client.get(
        f"/api/v1/rooms/{create_response.json()['id']}",
        headers=user_headers,
    )
    assert hidden_response.status_code == 404
