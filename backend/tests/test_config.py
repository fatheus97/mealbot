"""Tests for Settings — API-key placeholder normalization.

An operator who copies .env.example without editing leaves keys as the literal
placeholder ``your_key_here``. Those must read as *unset* so the app fails
honestly ("provider has no key") instead of building a client around a garbage
key that only 401s when the provider is actually hit.
"""

import pytest

from app.core.config import Settings, normalize_optional_key


class TestNormalizeOptionalKey:
    @pytest.mark.parametrize(
        "value",
        [
            None,
            "",
            "   ",
            "your_key_here",
            "YOUR_KEY_HERE",
            "  your_key_here  ",
            "your_openai_key_here",
            "your_gemini_api_key_here",
            "changeme",
            "CHANGE_ME",
        ],
    )
    def test_placeholder_and_blank_become_none(self, value: str | None) -> None:
        assert normalize_optional_key(value) is None

    @pytest.mark.parametrize(
        "value",
        [
            "AIzaSyReal-Looking-Key",
            "sk-proj-abc123",
            "sk-abc123def456",
        ],
    )
    def test_real_keys_pass_through(self, value: str) -> None:
        assert normalize_optional_key(value) == value

    def test_strips_surrounding_whitespace_on_real_key(self) -> None:
        assert normalize_optional_key("  sk-real  ") == "sk-real"

    def test_real_key_that_merely_contains_here_is_kept(self) -> None:
        # Guard the pattern isn't over-eager: only your_..._here is a placeholder.
        assert normalize_optional_key("sk-adhesive-tape") == "sk-adhesive-tape"


class TestSettingsKeyValidatorWired:
    """Prove the field_validator is actually attached to the key fields.

    All three keys are passed explicitly (init kwargs are the highest-priority
    source in pydantic-settings), so these are deterministic regardless of the
    container's process env.
    """

    @staticmethod
    def _settings(
        *,
        openai_api_key: str | None = None,
        gemini_api_key: str | None = None,
        deepseek_api_key: str | None = None,
    ) -> Settings:
        return Settings(
            secret_key="x" * 40,
            database_url="postgresql+psycopg://u:p@db:5432/mealbot",
            openai_api_key=openai_api_key,
            gemini_api_key=gemini_api_key,
            deepseek_api_key=deepseek_api_key,
        )

    def test_placeholder_openai_key_normalized_to_none(self) -> None:
        assert self._settings(openai_api_key="your_key_here").openai_api_key is None

    def test_placeholder_variant_normalized_to_none(self) -> None:
        assert self._settings(openai_api_key="your_openai_key_here").openai_api_key is None

    def test_real_key_preserved(self) -> None:
        assert self._settings(gemini_api_key="AIzaSyReal").gemini_api_key == "AIzaSyReal"


class TestFrontendBaseUrlNormalization:
    """frontend_base_url feeds every emailed/redirect deep link (invite, reset,
    checkout, portal) as `f"{frontend_base_url}/app?..."` — a trailing slash OR
    a stray surrounding space in the configured value would break every one of
    them (a space renders as an invalid/dead link; a trailing slash doubles up
    against the /app segment)."""

    @staticmethod
    def _settings(*, frontend_base_url: str) -> Settings:
        return Settings(
            secret_key="x" * 40,
            database_url="postgresql+psycopg://u:p@db:5432/mealbot",
            frontend_base_url=frontend_base_url,
        )

    def test_trailing_slash_is_stripped(self) -> None:
        s = self._settings(frontend_base_url="https://trymealbot.com/")
        assert s.frontend_base_url == "https://trymealbot.com"

    def test_no_trailing_slash_is_unchanged(self) -> None:
        s = self._settings(frontend_base_url="https://trymealbot.com")
        assert s.frontend_base_url == "https://trymealbot.com"

    def test_multiple_trailing_slashes_are_all_stripped(self) -> None:
        s = self._settings(frontend_base_url="https://trymealbot.com//")
        assert s.frontend_base_url == "https://trymealbot.com"

    def test_trailing_whitespace_is_stripped(self) -> None:
        # Realistic for a value set via a real OS env var / docker-compose
        # `environment:` entry / systemd Environment= (unlike an unquoted
        # .env file, which python-dotenv already strips) — a trailing space
        # would otherwise survive into every emitted link as-is.
        s = self._settings(frontend_base_url="https://trymealbot.com ")
        assert s.frontend_base_url == "https://trymealbot.com"

    def test_whitespace_and_trailing_slash_together_are_stripped(self) -> None:
        s = self._settings(frontend_base_url=" https://trymealbot.com/ ")
        assert s.frontend_base_url == "https://trymealbot.com"
