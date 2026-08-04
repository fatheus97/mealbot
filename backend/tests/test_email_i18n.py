"""Server-side translation: locale resolution, plural forms, and the four emails."""

import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from string import Template
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import i18n
from app.core.email_copy import (
    COPY,
    VERIFY_TTL_HOURS,
    EmailCopy,
    expiry_phrase,
    render,
)
from app.core.i18n import (
    DEFAULT_LOCALE,
    UI_LOCALES,
    locale_for_language,
    plural_category,
)
from app.core.language_whitelist import SUPPORTED_LANGUAGES
from app.models.db_models import User
from app.services import email_verification, feedback_notify, password_reset
from app.services.email_verification import TOKEN_TTL, change_notice_html, verification_email_html
from app.services.password_reset import reset_email_html


class TestLocaleForLanguage:
    def test_maps_the_languages_we_translate(self) -> None:
        assert locale_for_language("English") == "en"
        assert locale_for_language("Czech") == "cs"

    def test_matching_is_case_insensitive_and_trims(self) -> None:
        # `User.language` is normalized to canonical casing on write, but this
        # is also read from rows written before that normalization existed.
        assert locale_for_language("  czech ") == "cs"
        assert locale_for_language("CZECH") == "cs"

    @pytest.mark.parametrize("language", ["Japanese", "Polish", "Hindi"])
    def test_untranslated_whitelist_languages_fall_back_to_english(
        self, language: str
    ) -> None:
        # The whitelist is 33 languages because the MODEL can write them all.
        # Only the ones with hand-written copy get their own email; the rest
        # get English rather than a language nobody wrote.
        assert language in SUPPORTED_LANGUAGES
        assert locale_for_language(language) == DEFAULT_LOCALE

    @pytest.mark.parametrize("value", [None, "", "   ", "Klingon", "cs", "en"])
    def test_anything_unrecognised_falls_back_rather_than_raising(
        self, value: str | None
    ) -> None:
        # Note "cs"/"en" fall back too: the column holds EXONYMS, not locale
        # codes, so a bare code is as unrecognised as a made-up language.
        assert locale_for_language(value) == DEFAULT_LOCALE

    def test_every_mapped_language_is_actually_whitelisted(self) -> None:
        # A mapping to a language the API refuses to store would be dead code
        # that looks like support.
        canonical = {s.lower() for s in SUPPORTED_LANGUAGES}
        assert set(i18n._LANGUAGE_TO_LOCALE) <= canonical


class TestPluralCategory:
    @pytest.mark.parametrize(
        "count,expected", [(0, "other"), (1, "one"), (2, "other"), (5, "other")]
    )
    def test_english_has_two_forms(self, count: int, expected: str) -> None:
        assert plural_category("en", count) == expected

    @pytest.mark.parametrize(
        "count,expected",
        [
            (0, "other"),
            (1, "one"),
            (2, "few"),
            (3, "few"),
            (4, "few"),
            (5, "other"),
            (11, "other"),
            (100, "other"),
        ],
    )
    def test_czech_has_a_separate_form_for_two_to_four(
        self, count: int, expected: str
    ) -> None:
        # The reason a `count == 1` ternary cannot work for this language.
        assert plural_category("cs", count) == expected


class TestCopyCompleteness:
    def test_every_shipped_locale_has_copy(self) -> None:
        assert set(COPY) == set(UI_LOCALES)

    def test_every_locale_defines_every_key(self) -> None:
        # Redundant with mypy (EmailCopy is a total TypedDict) — kept because
        # the failure here names the missing keys directly.
        expected = set(EmailCopy.__annotations__)
        for locale, copy in COPY.items():
            assert set(copy) == expected, locale

    def test_every_locale_covers_its_plural_categories(self) -> None:
        # The guard mypy CANNOT provide: how many plural forms a language needs
        # is CLDR data, not type information. Without this, a future Slovak or
        # Polish dictionary carrying only one/other would pass every other
        # check and quietly print the wrong noun for 2-4.
        for locale in UI_LOCALES:
            needed = {plural_category(locale, n) for n in range(0, 200)}
            have = set(COPY[locale]["reset_expiry"])
            assert needed <= have, f"{locale} missing {needed - have}"

    def test_no_string_is_left_as_the_untranslated_english(self) -> None:
        # A copy-paste that never got translated. The bodies share HTML
        # scaffolding, so compare only the keys that are pure prose.
        english = COPY["en"]
        identical = [
            key
            for key in ("verify_subject", "reset_subject", "change_notice_subject",
                        "credit_subject")
            if COPY["cs"][key] == english[key]  # type: ignore[literal-required]
        ]
        assert identical == []

    def test_every_locale_uses_the_same_placeholders(self) -> None:
        # The bug: a translator drops $link and the email ships with no way to
        # act on it — for the two mails that exist purely to carry a link.
        holes = lambda s: sorted(set(re.findall(r"\$(\w+)", s)))  # noqa: E731
        for key, en_value in COPY["en"].items():
            if not isinstance(en_value, str):
                continue
            cs_value = COPY["cs"][key]  # type: ignore[literal-required]
            assert holes(en_value) == holes(cs_value), key


class TestRendering:
    def test_substitute_raises_on_a_missing_value(self) -> None:
        # Rather than mailing a literal "$link". The send path swallows and
        # logs, so raising degrades to a visible non-delivery.
        with pytest.raises(KeyError):
            render("<p>$link</p>")

    @pytest.mark.parametrize("locale", UI_LOCALES)
    def test_every_template_renders_with_its_documented_values(
        self, locale: str
    ) -> None:
        # Catches a stray `$` in the HTML as well as a placeholder one locale
        # introduced and the caller never supplies.
        copy = COPY[locale]  # type: ignore[index]
        render(copy["verify_body"], link="L")
        render(copy["change_notice_body"], new_email="E")
        render(copy["reset_body"], link="L", expiry="X")
        render(copy["credit_body"], credit_eur="1.00", max_eur="3.00")

    @pytest.mark.parametrize("locale", UI_LOCALES)
    def test_subjects_carry_no_placeholders(self, locale: str) -> None:
        # Nothing fills them, so a `$` in a subject line would ship verbatim.
        copy = COPY[locale]  # type: ignore[index]
        for key in ("verify_subject", "reset_subject", "change_notice_subject",
                    "credit_subject"):
            assert not Template(copy[key]).get_identifiers()  # type: ignore[literal-required]


class TestExpiryPhrase:
    def test_english_switches_on_one(self) -> None:
        assert expiry_phrase("en", 1) == "1 minute"
        assert expiry_phrase("en", 30) == "30 minutes"

    def test_czech_uses_the_genitive_form_that_follows_beh_em(self) -> None:
        # "během 1 minuty" / "během 3 minut" / "během 30 minut" — the noun is
        # inflected for THIS sentence, which is why the forms are namespaced
        # under reset_expiry rather than being a reusable "N minutes".
        assert expiry_phrase("cs", 1) == "1 minuty"
        assert expiry_phrase("cs", 3) == "3 minut"
        assert expiry_phrase("cs", 30) == "30 minut"


class TestEmailBodies:
    def test_verification_body_renders_english(self) -> None:
        assert "Welcome to Mealbot" in verification_email_html("https://x/y", "en")

    def test_verification_body_translates(self) -> None:
        body = verification_email_html("https://x/y", "cs")
        assert "Vítejte v Mealbotu" in body
        assert "https://x/y" in body

    def test_the_link_is_still_escaped_in_every_locale(self) -> None:
        # Escaping lives with the caller, not with the template. A translation
        # must not be able to move it.
        for locale in UI_LOCALES:
            body = verification_email_html('https://x/?a=1"><script>', locale)
            assert "<script>" not in body
            assert "&quot;&gt;&lt;script&gt;" in body

    def test_change_notice_escapes_the_new_address_in_every_locale(self) -> None:
        for locale in UI_LOCALES:
            body = change_notice_html('a@b.c"><img src=x>', locale)
            assert "<img" not in body
            assert "&lt;img" in body

    def test_reset_body_translates_and_carries_the_expiry(self) -> None:
        assert "Klikněte během" in reset_email_html("https://x/y", "cs")
        assert "Someone asked to reset" in reset_email_html("https://x/y", "en")

    def test_verification_ttl_matches_the_copy(self) -> None:
        # The copy states the validity window as a literal in both languages
        # while TOKEN_TTL is the thing that enforces it. Nothing links them, so
        # pin them together rather than letting a change to one lie about the
        # other.
        assert TOKEN_TTL.total_seconds() == VERIFY_TTL_HOURS * 3600
        for locale in UI_LOCALES:
            assert str(VERIFY_TTL_HOURS) in COPY[locale]["verify_body"]


async def _capture_into(sent: list[tuple[str, str, str]]):
    async def _send(to: str, subject: str, html: str) -> bool:
        sent.append((to, subject, html))
        return True

    return _send


class TestTheLocaleActuallyReachesTheSendCall:
    """The gap every test above leaves open.

    They all hand a locale in directly, which proves the copy, the plurals and
    the escaping — and proves nothing about whether the real call sites read
    ``User.language`` at all. The locale argument is REQUIRED (no default) so a
    dropped one is a type error rather than a silent English fallback, but the
    compiler only sees the html builders. That a Czech SUBJECT is chosen, and
    chosen from the recipient's own row, is behaviour only an end-to-end
    assertion can pin.
    """

    @staticmethod
    def _czech_user(email: str) -> User:
        return User(
            email=email,
            normalized_email=email,
            hashed_password="x",
            language="Czech",
        )

    async def test_verification_email_uses_the_users_language(
        self, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        user = self._czech_user("cz-verify@example.com")
        db_session.add(user)
        await db_session.flush()

        sent: list[tuple[str, str, str]] = []

        @asynccontextmanager
        async def _factory() -> AsyncIterator[AsyncSession]:
            yield db_session

        monkeypatch.setattr(
            email_verification, "send_transactional", await _capture_into(sent)
        )
        monkeypatch.setattr(email_verification, "session_factory", _factory)

        await email_verification.dispatch_verification_email(user.id)  # type: ignore[arg-type]

        assert len(sent) == 1
        assert sent[0][1] == COPY["cs"]["verify_subject"]
        assert "Vítejte v Mealbotu" in sent[0][2]

    async def test_reset_email_uses_the_users_language(
        self, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        user = self._czech_user("cz-reset@example.com")
        db_session.add(user)
        await db_session.flush()

        sent: list[tuple[str, str, str]] = []

        @asynccontextmanager
        async def _factory() -> AsyncIterator[AsyncSession]:
            yield db_session

        monkeypatch.setattr(
            password_reset, "send_transactional", await _capture_into(sent)
        )
        monkeypatch.setattr(password_reset, "session_factory", _factory)

        await password_reset.dispatch_reset_email("cz-reset@example.com")

        assert len(sent) == 1
        assert sent[0][1] == COPY["cs"]["reset_subject"]
        assert "Klikněte během" in sent[0][2]

    async def test_credit_email_uses_the_reporters_language(self) -> None:
        reporter = self._czech_user("cz-credit@example.com")
        reporter.id = 1
        send = AsyncMock(return_value=True)
        with patch(
            "app.services.feedback_notify.email_service.send_transactional", send
        ):
            await feedback_notify.notify_credit_granted(reporter, 100)

        assert send.await_args is not None
        _, subject, html = send.await_args.args
        assert subject == COPY["cs"]["credit_subject"]
        assert "Díky, že jste si našli čas" in html

    async def test_change_notice_uses_the_language_it_is_handed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # This one takes the locale as an argument rather than looking it up:
        # by the time it runs the row holds the NEW address, so there is no
        # user row left to read the old language from.
        sent: list[tuple[str, str, str]] = []
        monkeypatch.setattr(
            email_verification, "send_transactional", await _capture_into(sent)
        )

        await email_verification.dispatch_change_notice("old@x.com", "new@x.com", "cs")

        assert len(sent) == 1
        assert sent[0][1] == COPY["cs"]["change_notice_subject"]
        assert "byla právě změněna" in sent[0][2]

    @pytest.mark.parametrize("language", ["Japanese", "English"])
    async def test_an_untranslated_language_still_gets_english(
        self,
        db_session: AsyncSession,
        monkeypatch: pytest.MonkeyPatch,
        language: str,
    ) -> None:
        # The fallback has to hold at the CALL SITE, not just inside
        # locale_for_language — 31 of the 33 whitelisted languages land here.
        user = User(
            email=f"other-{language}@example.com",
            normalized_email=f"other-{language}@example.com",
            hashed_password="x",
            language=language,
        )
        db_session.add(user)
        await db_session.flush()

        sent: list[tuple[str, str, str]] = []

        @asynccontextmanager
        async def _factory() -> AsyncIterator[AsyncSession]:
            yield db_session

        monkeypatch.setattr(
            email_verification, "send_transactional", await _capture_into(sent)
        )
        monkeypatch.setattr(email_verification, "session_factory", _factory)

        await email_verification.dispatch_verification_email(user.id)  # type: ignore[arg-type]

        assert len(sent) == 1
        assert sent[0][1] == COPY["en"]["verify_subject"]
