import jwt
import pytest

from app.core.config import Settings, settings
from app.core.security import (
    ALGORITHM,
    create_access_token,
    get_password_hash,
    verify_password,
)


class TestPasswordHashing:
    def test_hash_and_verify_roundtrip(self) -> None:
        pw = "SecurePass123"
        hashed = get_password_hash(pw)
        assert verify_password(pw, hashed) is True

    def test_wrong_password_fails(self) -> None:
        hashed = get_password_hash("CorrectPassword")
        assert verify_password("WrongPassword", hashed) is False

    def test_hash_is_not_plaintext(self) -> None:
        pw = "MyPassword"
        hashed = get_password_hash(pw)
        assert hashed != pw

    def test_hash_uses_configured_rounds(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # get_password_hash must honour settings.bcrypt_rounds so the suite can
        # hash at bcrypt's floor while prod stays at 12. The cost factor is
        # encoded in the modular-crypt prefix as `$2b$<zero-padded-cost>$`.
        # Patch to a value distinct from both the prod default (12) and the
        # ambient test override (4) so this genuinely proves the wiring.
        monkeypatch.setattr(settings, "bcrypt_rounds", 6)
        hashed = get_password_hash("whatever")
        assert hashed.startswith("$2b$06$")
        # A hash minted at a non-default cost must still verify — checkpw reads
        # the cost from the hash itself.
        assert verify_password("whatever", hashed) is True

    def test_default_rounds_is_production_strength(self) -> None:
        # Prod must not be silently weakened by the test-only override: a freshly
        # constructed Settings (no env override) keeps the 12 default.
        s = Settings(
            secret_key="a" * 64,
            database_url="postgresql+psycopg://u:p@localhost/db",
        )
        assert s.bcrypt_rounds == 12


class TestAccessToken:
    def test_token_contains_correct_sub(self) -> None:
        token = create_access_token(subject=42, sid=1)
        payload = jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
        assert payload["sub"] == "42"

    def test_token_has_expiry(self) -> None:
        token = create_access_token(subject=1, sid=1)
        payload = jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
        assert "exp" in payload

    def test_token_carries_sid_and_tv_claims(self) -> None:
        token = create_access_token(subject=7, sid=42, token_version=3)
        payload = jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
        assert payload["sid"] == 42
        assert payload["tv"] == 3

    def test_token_with_wrong_secret_raises(self) -> None:
        token = create_access_token(subject=1, sid=1)
        with pytest.raises(jwt.InvalidSignatureError):
            jwt.decode(token, "wrong-secret-that-is-long-enough-for-hmac-sha256", algorithms=[ALGORITHM])


class TestSecretKeyValidation:
    def test_weak_key_rejected(self) -> None:
        with pytest.raises(ValueError, match="SECRET_KEY is insecure"):
            Settings(
                secret_key="CHANGE_ME",
                database_url="postgresql+psycopg://u:p@localhost/db",
            )

    def test_short_key_rejected(self) -> None:
        with pytest.raises(ValueError, match="SECRET_KEY is insecure"):
            Settings(
                secret_key="tooshort",
                database_url="postgresql+psycopg://u:p@localhost/db",
            )

    def test_good_key_accepted(self) -> None:
        s = Settings(
            secret_key="a" * 64,
            database_url="postgresql+psycopg://u:p@localhost/db",
        )
        assert s.secret_key == "a" * 64
