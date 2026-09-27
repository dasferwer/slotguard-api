from collections.abc import Callable, Generator
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from slotguard.config import get_settings
from slotguard.db import engine
from slotguard.main import app
from slotguard.seed import seed_database


@pytest.fixture(scope="session", autouse=True)
def reset_database() -> Generator[None, None, None]:
    if engine.url.database != "slotguard_test":
        raise RuntimeError("Тесты разрешены только в отдельной БД slotguard_test")
    with engine.begin() as connection:
        connection.execute(
            text("TRUNCATE TABLE booking_requests, audit_logs, bookings, rooms, users CASCADE")
        )
    seed_database()
    yield


@pytest.fixture(scope="session")
def client() -> Generator[TestClient, None, None]:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(scope="session")
def admin_headers(client: TestClient) -> dict[str, str]:
    settings = get_settings()
    response = client.post(
        "/api/v1/auth/login",
        json={
            "email": str(settings.admin_email),
            "password": settings.admin_password.get_secret_value(),
        },
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.fixture
def register_user(client: TestClient) -> Callable[[str | None], dict[str, str]]:
    def factory(email: str | None = None) -> dict[str, str]:
        user_email = email or f"user-{uuid4()}@example.com"
        password = "StrongPass123!"
        register_response = client.post(
            "/api/v1/auth/register",
            json={
                "email": user_email,
                "full_name": "Test User",
                "password": password,
            },
        )
        assert register_response.status_code == 201
        login_response = client.post(
            "/api/v1/auth/login",
            json={"email": user_email, "password": password},
        )
        assert login_response.status_code == 200
        return {"Authorization": f"Bearer {login_response.json()['access_token']}"}

    return factory
