import pytest
from httpx import AsyncClient

from tests.conftest import TEST_EMAIL, TEST_PASSWORD


class TestRegister:
    async def test_register_success(self, unauthed_client: AsyncClient):
        resp = await unauthed_client.post(
            "/api/users/register",
            json={"email": "new@example.com", "password": "NewPassword123"},
        )
        assert resp.status_code == 201

    async def test_register_duplicate_email(
        self, unauthed_client: AsyncClient, test_user
    ):
        resp = await unauthed_client.post(
            "/api/users/register",
            json={"email": TEST_EMAIL, "password": "AnotherPass123"},
        )
        assert resp.status_code == 400
        assert "already registered" in resp.json()["detail"].lower()


class TestLogin:
    async def test_login_success(self, unauthed_client: AsyncClient, test_user):
        resp = await unauthed_client.post(
            "/api/users/login",
            data={"username": TEST_EMAIL, "password": TEST_PASSWORD},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "access_token" in body
        assert body["email"] == TEST_EMAIL

    async def test_login_wrong_password(self, unauthed_client: AsyncClient, test_user):
        resp = await unauthed_client.post(
            "/api/users/login",
            data={"username": TEST_EMAIL, "password": "WrongPassword"},
        )
        assert resp.status_code == 401


class TestProfile:
    async def test_get_profile(self, client: AsyncClient, auth_headers: dict):
        resp = await client.get("/api/users", headers=auth_headers)
        assert resp.status_code == 200
        body = resp.json()
        assert body["email"] == TEST_EMAIL
        assert "id" in body

    async def test_patch_profile(self, client: AsyncClient, auth_headers: dict):
        resp = await client.patch(
            "/api/users",
            headers=auth_headers,
            json={"country": "CZ", "measurement_system": "metric"},
        )
        assert resp.status_code == 200
        assert resp.json()["country"] == "CZ"
        assert resp.json()["measurement_system"] == "metric"

    async def test_patch_invalid_measurement(
        self, client: AsyncClient, auth_headers: dict
    ):
        resp = await client.patch(
            "/api/users",
            headers=auth_headers,
            json={"measurement_system": "invalid_value"},
        )
        assert resp.status_code == 400
