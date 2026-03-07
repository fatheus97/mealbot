import jwt
import pytest

from app.core.security import (
    ALGORITHM,
    get_password_hash,
    verify_password,
    create_access_token,
)
from app.core.config import settings


class TestPasswordHashing:
    def test_hash_and_verify_roundtrip(self):
        pw = "SecurePass123"
        hashed = get_password_hash(pw)
        assert verify_password(pw, hashed) is True

    def test_wrong_password_fails(self):
        hashed = get_password_hash("CorrectPassword")
        assert verify_password("WrongPassword", hashed) is False

    def test_hash_is_not_plaintext(self):
        pw = "MyPassword"
        hashed = get_password_hash(pw)
        assert hashed != pw


class TestAccessToken:
    def test_token_contains_correct_sub(self):
        token = create_access_token(subject=42)
        payload = jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
        assert payload["sub"] == "42"

    def test_token_has_expiry(self):
        token = create_access_token(subject=1)
        payload = jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
        assert "exp" in payload

    def test_token_with_wrong_secret_raises(self):
        token = create_access_token(subject=1)
        with pytest.raises(jwt.InvalidSignatureError):
            jwt.decode(token, "wrong-secret", algorithms=[ALGORITHM])
