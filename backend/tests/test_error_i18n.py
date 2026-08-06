"""Localized error `detail` strings: the copy, the header parse, and the wiring.

The end-to-end tests below are the ones that matter, and they are written to
fail for the RIGHT reason. Asserting `response.json()["detail"] == <czech>` also
passes if the endpoint 500s into a different Czech string, so each one pins the
status code too, and the precedence test asserts the English is ABSENT rather
than only that the Czech is present — an assertion that both languages could
satisfy proves nothing about which one won.
"""

from __future__ import annotations

import ast
import pathlib
import re
from datetime import UTC, datetime
from typing import get_args

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.error_copy import ERROR_COPY, ErrorKey, PluralErrorKey
from app.core.errors import LocalizedHTTPException
from app.core.i18n import UI_LOCALES, Locale, locale_from_accept_language, plural_category
from app.core.security import get_password_hash
from app.models.db_models import User
from tests.conftest import TEST_PASSWORD

ALL_KEYS = frozenset(get_args(ErrorKey))
PLURAL_BASES = frozenset(get_args(PluralErrorKey))


def expected_keys(locale: Locale) -> frozenset[str]:
    """Every key a locale must define.

    Locale-DEPENDENT on purpose. How many plural forms a language needs is CLDR
    data, not type information, so this asks `plural_category` which categories
    it can actually return rather than assuming English's two. Czech needs a
    third (`few`, for 2-4), and a check hardcoded to one/other would happily
    pass a Czech dictionary that renders "5 recepty".

    `email_copy` learned the same lesson from the frontend, where a Slovak
    dictionary carrying only one/other compiled clean.
    """
    categories = {plural_category(locale, n) for n in range(200)}
    return ALL_KEYS | {
        f"{base}_{category}" for base in PLURAL_BASES for category in categories
    }


# ─── The copy itself ────────────────────────────────────────────────────────


def test_every_locale_covers_every_key() -> None:
    """The check `email_copy` gets from its total TypedDict — see that module's
    docstring for why this one is a test instead."""
    for locale in UI_LOCALES:
        assert frozenset(ERROR_COPY[locale]) == expected_keys(locale), locale


def test_error_copy_locales_match_the_ui_locale_list() -> None:
    assert frozenset(ERROR_COPY) == frozenset(UI_LOCALES)


def test_czech_is_actually_translated() -> None:
    """A dict copy-pasted from English passes every set-based check above.

    Only exempts nothing today: no error sentence is a loanword or a symbol. If
    one ever legitimately reads the same in both languages, add it here WITH the
    reason rather than weakening the assertion.
    """
    # Intersection, not ALL_KEYS: English has no `_few`, so comparing over the
    # union would KeyError rather than report a copy-paste.
    shared = frozenset(ERROR_COPY["cs"]) & frozenset(ERROR_COPY["en"])
    identical = [k for k in shared if ERROR_COPY["cs"][k] == ERROR_COPY["en"][k]]
    assert identical == []


def test_no_key_is_blank() -> None:
    for locale in UI_LOCALES:
        for key in ERROR_COPY[locale]:
            assert ERROR_COPY[locale][key].strip(), f"{locale}/{key}"


def test_placeholders_match_across_locales() -> None:
    """Both languages must fill the same blanks.

    A Czech string that names `$needed` where English names `$need` renders
    fine in English and raises KeyError in Czech — on the error path, so the
    user hits a 500 while already failing at something else. `substitute`
    (not `safe_substitute`) makes that loud rather than silent, which is why
    catching it here matters.
    """
    for key in frozenset(ERROR_COPY["cs"]) & frozenset(ERROR_COPY["en"]):
        assert placeholders(ERROR_COPY["cs"][key]) == placeholders(
            ERROR_COPY["en"][key]
        ), key


def placeholders(template: str) -> frozenset[str]:
    return frozenset(re.findall(r"\$\{?([a-z_]+)\}?", template))


def test_plural_sentences_actually_differ() -> None:
    """Each Czech plural form must be its own sentence.

    Czech inflects the noun AND the pronoun after it (1 recept / ho, 2-4
    recepty / je, 5+ receptů / je), so two identical forms mean someone filled
    the dict by copy-paste and one of the counts will read wrong.
    """
    for base in PLURAL_BASES:
        forms = {
            category: ERROR_COPY["cs"][f"{base}_{category}"]
            for category in {plural_category("cs", n) for n in range(200)}
        }
        assert len(set(forms.values())) == len(forms), f"{base}: {forms}"


def test_no_orphan_error_keys() -> None:
    """Every key must be raised somewhere.

    The mirror of "every raise has a key": a key nothing raises is copy a
    translator maintains forever for a sentence no user can reach. The frontend
    learned this one the expensive way — `calendar.plan` sat in both
    dictionaries for a call site that was never wired up, so the dictionary
    looked complete while the component still rendered English.
    """
    app_dir = pathlib.Path(__file__).resolve().parent.parent / "app"
    raised: set[str] = set()
    for path in app_dir.rglob("*.py"):
        if path.name == "error_copy.py":
            continue  # defining a key is not using it
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.Call):
                continue
            # Both `LocalizedHTTPException(...)` and `errors.LocalizedHTTPException(...)`.
            # Every call site imports the symbol directly today, so the second
            # form matches nothing — but a key reached only through a qualified
            # import would otherwise pass this test for the WRONG reason: not
            # found, therefore not reported, and `assert len(raised) > 10` is
            # far too coarse to notice one missing.
            func = node.func
            name = (
                func.id
                if isinstance(func, ast.Name)
                else func.attr if isinstance(func, ast.Attribute) else None
            )
            if name == "LocalizedHTTPException":
                for arg in node.args:
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                        raised.add(arg.value)

    # Guards the guard: a broken walk would make the assertion below pass over
    # an empty set, which is the exact failure this test is about.
    assert len(raised) > 10
    # PLURAL_BASES as well as ALL_KEYS. A plural key is raised by its BASE
    # (`count=` picks the suffix at render time), so the base is what appears
    # in the source — and leaving it out meant an unused plural key was
    # invisible to the one test whose whole job is finding unused keys.
    assert sorted((ALL_KEYS | PLURAL_BASES) - raised) == []


# ─── Rendering: parameters and plurals ──────────────────────────────────────


def test_parameters_are_substituted() -> None:
    exc = LocalizedHTTPException(
        409, "plan_reopen_shortage", ingredient="Chicken", needed="250", have="80"
    )
    assert exc.render_for("en") == (
        "Not enough Chicken in fridge to reopen this plan: need 250g, have 80g."
    )
    # `${needed}g` is braced because `$neededg` would parse as one name. Pinned
    # because dropping the braces still renders — just with the wrong value
    # missing and a KeyError, or worse, silently in a locale that spaces it.
    assert "250g" in exc.render_for("en")


def test_parameters_survive_into_czech() -> None:
    exc = LocalizedHTTPException(
        409, "plan_reopen_shortage", ingredient="Kuřecí maso", needed="250", have="80"
    )
    rendered = exc.render_for("cs")
    assert "Kuřecí maso" in rendered
    assert "250" in rendered and "80" in rendered
    assert "$" not in rendered


@pytest.mark.parametrize(
    ("count", "fragment"),
    [
        (1, "1 recept "),
        (2, "2 recepty "),
        (4, "4 recepty "),
        (5, "5 receptů "),
        (11, "11 receptů "),
        (0, "0 receptů "),
    ],
)
def test_czech_picks_the_right_plural_form(count: int, fragment: str) -> None:
    exc = LocalizedHTTPException(409, "plan_favorites_block_delete", count=count)
    assert fragment in exc.render_for("cs")


@pytest.mark.parametrize(("count", "fragment"), [(1, "1 cookbook recipe."), (2, "2 cookbook recipes.")])
def test_english_picks_the_right_plural_form(count: int, fragment: str) -> None:
    exc = LocalizedHTTPException(409, "plan_favorites_block_delete", count=count)
    assert fragment in exc.render_for("en")


def test_plural_key_without_count_is_rejected() -> None:
    # Without the guard this KeyErrors deep inside `render`, naming a suffixed
    # key that appears nowhere in the source — a confusing report for what is
    # really a wrong call.
    with pytest.raises(ValueError, match="required for a plural key"):
        LocalizedHTTPException(409, "plan_favorites_block_delete")  # type: ignore[call-overload]


def test_count_on_a_static_key_is_rejected() -> None:
    # The quieter mistake of the two: `render` would ignore the count and
    # return a perfectly good sentence, so nothing would ever surface it.
    with pytest.raises(ValueError, match="not\n?\\s*accepted for any other"):
        LocalizedHTTPException(404, "plan_not_found", count=3)  # type: ignore[call-overload]


def test_eager_english_detail_matches_the_rendered_english() -> None:
    """`detail` is filled at construction so an unhandled raise degrades to
    today's behaviour rather than to an empty body. It must not drift from what
    the handler would produce for English."""
    for exc in (
        LocalizedHTTPException(404, "plan_not_found"),
        LocalizedHTTPException(409, "plan_favorites_block_delete", count=3),
        LocalizedHTTPException(
            409, "plan_reopen_shortage", ingredient="Rice", needed="10", have="2"
        ),
    ):
        assert exc.detail == exc.render_for("en")


# ─── Accept-Language parsing ────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        (None, "en"),
        ("", "en"),
        ("cs", "cs"),
        ("CS", "cs"),  # case-insensitive per RFC 9110
        ("cs-CZ", "cs"),  # region subtag ignored
        ("cs-CZ,cs;q=0.9,en;q=0.8", "cs"),
        ("de,fr;q=0.9", "en"),  # nothing we translate
        ("*", "en"),
        # The whole point of parsing q at all: first-tag-wins gets this backwards.
        ("en;q=0.5, cs", "cs"),
        ("en;q=0.5,cs;q=0.9", "cs"),
        ("cs;q=0.5,en;q=0.9", "en"),
        # Equal q keeps source order — that is what equality is supposed to mean.
        ("en;q=0.8,cs;q=0.8", "en"),
        ("cs;q=0.8,en;q=0.8", "cs"),
        # `;q=0` is RFC 9110 for "explicitly not this one".
        ("cs;q=0,en", "en"),
        ("cs;q=0", "en"),
        # A `*` earlier in the ranking must not let a lower-ranked tag win.
        ("*;q=0.9,cs;q=0.1", "en"),
        # Junk must fall back, not raise: this runs on every failed login.
        ("cs;q=banana", "en"),
        (";;;", "en"),
        (",,,", "en"),
        ("cs;;q=0.9", "cs"),
        ("=", "en"),
    ],
)
def test_locale_from_accept_language(header: str | None, expected: str) -> None:
    assert locale_from_accept_language(header) == expected


def test_accept_language_is_bounded() -> None:
    """The header is attacker-controlled on every unauthenticated request."""
    assert locale_from_accept_language("de," * 10_000 + "cs") == "en"
    assert locale_from_accept_language("x" * 100_000) == "en"


# ─── End to end ─────────────────────────────────────────────────────────────

BAD_LOGIN = {"email": "nobody@example.com", "password": "wrong-password-x"}

# NOTE: every test below uses `unauthed_client`, never `client`. The `client`
# fixture overrides `get_current_user` with a stub that returns `test_user`
# directly — so the real dependency never runs and `request.state.locale` is
# never stamped. A precedence test written against it would silently be testing
# the Accept-Language path twice.


@pytest.mark.asyncio
async def test_logged_out_error_uses_accept_language(
    unauthed_client: AsyncClient,
) -> None:
    """The case that forced this design: a failed login has no user row to read
    a language from, so the header is the only signal there is."""
    res = await unauthed_client.post(
        "/api/auth/login",
        json=BAD_LOGIN,
        headers={"Accept-Language": "cs-CZ,cs;q=0.9"},
    )
    assert res.status_code == 401
    assert res.json()["detail"] == ERROR_COPY["cs"]["auth_bad_credentials"]


@pytest.mark.asyncio
async def test_logged_out_error_defaults_to_english(
    unauthed_client: AsyncClient,
) -> None:
    res = await unauthed_client.post("/api/auth/login", json=BAD_LOGIN)
    assert res.status_code == 401
    assert res.json()["detail"] == ERROR_COPY["en"]["auth_bad_credentials"]


@pytest.mark.asyncio
async def test_unknown_accept_language_falls_back_to_english(
    unauthed_client: AsyncClient,
) -> None:
    res = await unauthed_client.post(
        "/api/auth/login", json=BAD_LOGIN, headers={"Accept-Language": "ja,de;q=0.8"}
    )
    assert res.status_code == 401
    assert res.json()["detail"] == ERROR_COPY["en"]["auth_bad_credentials"]


@pytest.mark.asyncio
async def test_unauthenticated_request_is_localized(
    unauthed_client: AsyncClient,
) -> None:
    """Raised from `get_access_token_from_cookie` — a dependency that runs
    BEFORE `get_current_user`, so `request.state.locale` has never been set."""
    res = await unauthed_client.get("/api/users", headers={"Accept-Language": "cs"})
    assert res.status_code == 401
    assert res.json()["detail"] == ERROR_COPY["cs"]["auth_not_authenticated"]


@pytest.mark.asyncio
async def test_plan_error_is_localized_end_to_end(
    unauthed_client: AsyncClient, db_session: AsyncSession
) -> None:
    """A plan-slice key travelling the real handler, not just `render_for`.

    Uses a VERIFIED user so the request gets past the email gate and reaches
    the router — a 403 from `gate_confirm_email` would also be Czech and would
    pass a naive "is it Czech" assertion while proving nothing about plan.py.
    Hence the exact-string comparison and the status pin.
    """
    await _login_as(unauthed_client, db_session, "Czech", verified=True)
    res = await unauthed_client.get("/api/plan/999999")
    assert res.status_code == 404, res.text
    assert res.json()["detail"] == ERROR_COPY["cs"]["plan_not_found"]


async def _login_as(
    client: AsyncClient,
    session: AsyncSession,
    language: str,
    *,
    verified: bool = False,
) -> None:
    """Create a user in `language` and log the client in for real.

    UNVERIFIED by default, so any gated endpoint 403s on
    `require_verified_email` — the cheapest localized error reachable behind a
    real session. Deliberately not through the `client` fixture's stub, because
    the whole point is to exercise the `get_current_user` that stamps the
    locale.

    Pass `verified=True` to get PAST that gate and reach a router.
    """
    password = f"{TEST_PASSWORD}-x"
    email = f"locale-{language.lower()}-{'v' if verified else 'u'}@example.com"
    session.add(
        User(
            email=email,
            hashed_password=get_password_hash(password),
            language=language,
            email_verified_at=datetime.now(UTC) if verified else None,
        )
    )
    await session.flush()
    res = await client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    assert res.status_code == 200, res.text


@pytest.mark.asyncio
async def test_user_language_beats_accept_language(
    unauthed_client: AsyncClient, db_session: AsyncSession
) -> None:
    """A Czech-speaking user on a borrowed English laptop still gets Czech.

    The header says English and the account says Czech; only one of them can
    win, so this asserts the English sentence is ABSENT as well as that the
    Czech one is present — an assertion that merely finds the Czech string
    would also pass if both were somehow rendered.
    """
    await _login_as(unauthed_client, db_session, "Czech")
    res = await unauthed_client.post(
        "/api/billing/checkout", json={}, headers={"Accept-Language": "en-US,en;q=0.9"}
    )
    assert res.status_code == 403
    assert res.json()["detail"] == ERROR_COPY["cs"]["gate_confirm_email"]
    assert ERROR_COPY["en"]["gate_confirm_email"] not in res.text


@pytest.mark.asyncio
async def test_user_language_beats_accept_language_the_other_way(
    unauthed_client: AsyncClient, db_session: AsyncSession
) -> None:
    """The mirror. Without it, a bug that just always returned Czech for a
    logged-in user would pass the test above."""
    await _login_as(unauthed_client, db_session, "English")
    res = await unauthed_client.post(
        "/api/billing/checkout", json={}, headers={"Accept-Language": "cs-CZ,cs;q=0.9"}
    )
    assert res.status_code == 403
    assert res.json()["detail"] == ERROR_COPY["en"]["gate_confirm_email"]
    assert ERROR_COPY["cs"]["gate_confirm_email"] not in res.text


@pytest.mark.asyncio
async def test_untranslated_user_language_falls_back_to_english(
    unauthed_client: AsyncClient, db_session: AsyncSession
) -> None:
    """31 of the 33 whitelisted languages have no copy. They must land on
    English rather than on a KeyError — see `locale_for_language`."""
    await _login_as(unauthed_client, db_session, "Japanese")
    res = await unauthed_client.post("/api/billing/checkout", json={})
    assert res.status_code == 403
    assert res.json()["detail"] == ERROR_COPY["en"]["gate_confirm_email"]
