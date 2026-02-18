def test_create_user_is_idempotent(client):
    r1 = client.post("/api/users/", params={"email": "test@example.com"})
    assert r1.status_code == 200
    id1 = r1.json()

    r2 = client.post("/api/users/", params={"email": "test@example.com"})
    assert r2.status_code == 200
    id2 = r2.json()

    assert id1 == id2
