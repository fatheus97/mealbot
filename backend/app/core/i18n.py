"""Server-side translation, for the text the backend itself puts in front of a user.

The frontend has its own dictionary (``frontend/src/i18n/``) for UI chrome. This
one covers what React never sees: transactional email, and — next slice — the
``detail`` strings on error responses.

─── Which locale ───────────────────────────────────────────────────────────────
For email the answer is unambiguous: the recipient is always a ``User``, and
``User.language`` already records the language they chose. That field holds an
English EXONYM ("Czech") from a 33-entry whitelist
(``app/core/language_whitelist.py``) because it is fed to the meal-plan prompt,
and the model can write Japanese without anyone translating a single button. So
the whitelist is deliberately much larger than the set of languages this file
has copy for, and ``locale_for_language`` narrows one to the other — anything we
have not translated resolves to English rather than failing.

─── Placeholders use ``$name``, not ``{name}`` ─────────────────────────────────
The frontend uses ``{name}``; this file uses ``string.Template``. Not
gratuitous: these templates are whole HTML documents, and the day one of them
grows a ``<style>`` block every ``{`` in the CSS becomes a format field.
``str.format`` would raise on a good day and silently mangle the body on a bad
one. ``$`` cannot collide with HTML or CSS, and ``Template.substitute`` (not
``safe_substitute``) raises on a missing value — a half-rendered email showing
"$link" to a user is worse than a logged failure the send path already swallows.
"""

from __future__ import annotations

from typing import Final, Literal

Locale = Literal["en", "cs"]

#: Locales this file actually has copy for. Keep in sync with UI_LOCALES in
#: frontend/src/store/useLocaleStore.ts — a user whose UI is Czech and whose
#: email arrives in English is the exact seam this file exists to close. CI
#: checks the two lists match (.github/workflows/ci.yml, "locale parity").
UI_LOCALES: Final[tuple[Locale, ...]] = ("en", "cs")

DEFAULT_LOCALE: Final[Locale] = "en"

#: Exonym (lowercased) → locale, for the subset of SUPPORTED_LANGUAGES we
#: translate. Every other whitelisted language falls through to English.
_LANGUAGE_TO_LOCALE: Final[dict[str, Locale]] = {
    "english": "en",
    "czech": "cs",
}


def locale_for_language(language: str | None) -> Locale:
    """Locale to write to a user in, from their ``User.language``.

    Falls back to English for null, blank, unknown, and — importantly — for the
    31 whitelisted languages we do not translate. A Japanese-speaking user gets
    Japanese recipes and an English email today, which is the honest outcome;
    the alternative would be inventing copy nobody wrote.
    """
    if not language:
        return DEFAULT_LOCALE
    return _LANGUAGE_TO_LOCALE.get(language.strip().lower(), DEFAULT_LOCALE)


PluralCategory = Literal["one", "few", "many", "other"]


def plural_category(locale: Locale, count: int) -> PluralCategory:
    """CLDR plural category for ``count``.

    Hand-written rather than pulled from Babel, and worth stating why: Babel is
    the right answer the moment a third language appears, but it ships the whole
    CLDR dataset to decide something these two languages settle in six lines.
    The rules below are transcribed from CLDR and pinned by tests; if this file
    ever needs a language whose rules are not obvious, that is the signal to
    take the dependency rather than to guess.

    Integers only, which is all the backend counts. Czech's fourth category
    ("many") applies to decimals — ``1,5 minuty`` — so it is unreachable here
    and named only so the type matches the frontend's.
    """
    if locale == "cs":
        if count == 1:
            return "one"
        if 2 <= count <= 4:
            return "few"
        return "other"
    return "one" if count == 1 else "other"
