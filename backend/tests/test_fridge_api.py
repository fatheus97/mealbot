# tests/test_fridge_api.py
from fastapi.testclient import TestClient


def test_fridge_roundtrip(client: TestClient):
    """
    Full lifecycle:
    - create user
    - put fridge contents
    - get fridge contents back and compare
    """

    # 1) Create user
    create_resp = client.post("/api/users/", params={"email": "fridge@example.com"})
    assert create_resp.status_code == 200
    user_id = create_resp.json()
    assert isinstance(user_id, int)

    # 2) Put fridge contents for that user
    fridge_payload = [
        {"name": "chicken breast", "quantity_grams": 600.0, "need_to_use": True},
        {"name": "rice", "quantity_grams": 500.0, "need_to_use": False},
    ]

    put_resp = client.put(f"/api/users/{user_id}/fridge", json=fridge_payload)
    assert put_resp.status_code == 200

    get_resp = client.get(f"/api/users/{user_id}/fridge")
    assert get_resp.status_code == 200
    data = get_resp.json()

    by_name = {x["name"]: x for x in data}
    assert by_name["chicken breast"]["need_to_use"] is True
    assert by_name["rice"]["need_to_use"] is False


def test_fridge_nonexistent_user(client: TestClient):
    """
    GET /fridge pro neexistujícího usera by měl vrátit 404.
    """

    resp = client.get("/api/users/999999/fridge")
    assert resp.status_code == 404
    body = resp.json()
    assert body["detail"] == "User not found"
