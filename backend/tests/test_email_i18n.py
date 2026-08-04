"""Server-side translation: locale resolution, plural forms, and the four emails."""

import re
from string import Template

import pytest

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
    def test_verification_body_is_english_by_default(self) -> None:
        # Callers that predate the locale argument must not silently change
        # language — the default is what keeps this a pure addition.
        assert "Welcome to Mealbot" in verification_email_html("https://x/y")

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
        assert "Someone asked to reset" in reset_email_html("https://x/y")

    def test_verification_ttl_matches_the_copy(self) -> None:
        # The copy states the validity window as a literal in both languages
        # while TOKEN_TTL is the thing that enforces it. Nothing links them, so
        # pin them together rather than letting a change to one lie about the
        # other.
        assert TOKEN_TTL.total_seconds() == VERIFY_TTL_HOURS * 3600
        for locale in UI_LOCALES:
            assert str(VERIFY_TTL_HOURS) in COPY[locale]["verify_body"]
