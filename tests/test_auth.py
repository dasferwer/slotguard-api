from uuid import uuid4

from fastapi.testclient import TestClient


def test_register_login_and_read_profile(client: TestClient) -> None:
    email = f"profile-{uuid4()}@example.com"
    payload = {
        "email": email,
        "full_name": "Ilya Developer",
        "password": "StrongPass123!",
    }

    register_response = client.post("/api/v1/auth/register", json=payload)
    assert register_response.status_code == 201
    assert register_response.json()["email"] == email
    assert register_response.json()["role"] == "user"
    assert "password" not in register_response.json()

    duplicate_response = client.post("/api/v1/auth/register", json=payload)
    assert duplicate_response.status_code == 409

    login_response = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": payload["password"]},
    )
    assert login_response.status_code == 200
    token = login_response.json()["access_token"]

    profile_response = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert profile_response.status_code == 200
    assert profile_response.json()["full_name"] == payload["full_name"]


def test_login_rejects_wrong_password(client: TestClient) -> None:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "nobody@example.com", "password": "WrongPass123!"},
    )

    assert response.status_code == 401
