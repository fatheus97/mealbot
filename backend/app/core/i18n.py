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

from string import Template
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


#: Upper bounds on the Accept-Language header we are willing to parse. The header
#: is attacker-controlled on every request, including unauthenticated ones, and
#: the parse below is linear — but "linear in a 10 MB header" is still work we do
#: not have to do. Both numbers are far above any real browser (Chrome sends
#: ~4 tags, ~60 bytes).
_ACCEPT_LANGUAGE_MAX_CHARS: Final = 512
_ACCEPT_LANGUAGE_MAX_TAGS: Final = 20


def locale_from_accept_language(header: str | None) -> Locale:
    """Locale from ``Accept-Language``.

    Mainly for the LOGGED-OUT paths — a failed login, registration, a password
    reset. For ERROR MESSAGES, once a request has a user, ``User.language`` wins
    and this is not consulted: the language they picked in the app is a
    deliberate choice, while the header is whatever their browser was installed
    with. A Czech-speaking user on a borrowed English laptop should still get
    Czech errors.

    ⚠️ ONE DELIBERATE EXCEPTION, on an authenticated path: ``billing``'s
    ``_checkout_locale`` calls this to pick the language of Stripe's hosted
    Checkout and Portal pages. That is not a contradiction — ``User.language`` is
    the RECIPE language (33 options, what the model writes meal plans in), while
    Stripe's pages are UI chrome, and ``authFetch`` puts the SPA's chosen UI
    locale in this header precisely so the backend can read it. Do not "correct"
    that call site to ``request.state.locale``: it would make the checkout follow
    the recipe language, and before it read this header at all it followed the
    browser's IP — the bug #423 exists to close.

    Quality values are honoured rather than taking the first tag, because
    ``en;q=0.5, cs`` genuinely means Czech, and a "first wins" reading gets that
    exactly backwards. Ties keep source order (``sorted`` is stable), which is
    what q-value equality is supposed to mean.

    Unparseable input never raises — a malformed header is a reason to fall back
    to English, not to 500 a login attempt.
    """
    if not header:
        return DEFAULT_LOCALE

    ranked: list[tuple[float, int, str]] = []
    for index, part in enumerate(header[:_ACCEPT_LANGUAGE_MAX_CHARS].split(",")):
        if index >= _ACCEPT_LANGUAGE_MAX_TAGS:
            break
        tag, _, params = part.strip().partition(";")
        tag = tag.strip().lower()
        if not tag:
            continue
        quality = 1.0
        for param in params.split(";"):
            name, _, value = param.partition("=")
            if name.strip().lower() == "q":
                try:
                    quality = float(value.strip())
                except ValueError:
                    # A junk q makes the tag unusable, not the whole header.
                    quality = 0.0
        # `;q=0` is the RFC 9110 way to say "explicitly not this one".
        if quality > 0:
            ranked.append((-quality, index, tag))

    for _, _, tag in sorted(ranked):
        # A bare `*` means "anything", so stop looking and take the default
        # rather than letting a lower-ranked tag win a slot it did not earn.
        if tag == "*":
            break
        primary = tag.split("-", 1)[0]
        if primary in UI_LOCALES:
            # UI_LOCALES is a tuple of Locale literals, so this narrows on its
            # own — no cast needed.
            return primary
    return DEFAULT_LOCALE


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


def render(template: str, /, **values: str) -> str:
    """Substitute ``$name`` placeholders, raising if one has no value.

    ``substitute``, never ``safe_substitute``: an unfilled placeholder would
    mail a user a literal "$link". The send path already swallows and logs
    exceptions, so raising degrades to "no email plus a logged error" — which is
    both recoverable and visible, unlike a broken email that looks delivered.
    """
    return Template(template).substitute(**values)
