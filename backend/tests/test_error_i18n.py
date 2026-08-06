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
from typing import get_args

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.error_copy import ERROR_COPY, ErrorKey
from app.core.i18n import UI_LOCALES, locale_from_accept_language
from app.core.security import get_password_hash
from app.models.db_models import User
from tests.conftest import TEST_PASSWORD

ALL_KEYS = frozenset(get_args(ErrorKey))


# ─── The copy itself ────────────────────────────────────────────────────────


def test_every_locale_covers_every_key() -> None:
    """The check `email_copy` gets from its total TypedDict — see that module's
    docstring for why this one is a test instead."""
    for locale in UI_LOCALES:
        assert frozenset(ERROR_COPY[locale]) == ALL_KEYS, locale


def test_error_copy_locales_match_the_ui_locale_list() -> None:
    assert frozenset(ERROR_COPY) == frozenset(UI_LOCALES)


def test_czech_is_actually_translated() -> None:
    """A dict copy-pasted from English passes every set-based check above.

    Only exempts nothing today: no error sentence is a loanword or a symbol. If
    one ever legitimately reads the same in both languages, add it here WITH the
    reason rather than weakening the assertion.
    """
    identical = [k for k in ALL_KEYS if ERROR_COPY["cs"][k] == ERROR_COPY["en"][k]]
    assert identical == []


def test_no_key_is_blank() -> None:
    for locale in UI_LOCALES:
        for key in ALL_KEYS:
            assert ERROR_COPY[locale][key].strip(), f"{locale}/{key}"


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
            func = node.func
            if isinstance(func, ast.Name) and func.id == "LocalizedHTTPException":
                for arg in node.args:
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                        raised.add(arg.value)

    # Guards the guard: a broken walk would make the assertion below pass over
    # an empty set, which is the exact failure this test is about.
    assert len(raised) > 10
    assert sorted(ALL_KEYS - raised) == []


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


async def _login_as(
    client: AsyncClient, session: AsyncSession, language: str
) -> None:
    """Create an UNVERIFIED user in `language` and log the client in for real.

    Unverified so that any gated endpoint 403s on `require_verified_email`,
    which is the cheapest localized error reachable behind a real session — and
    deliberately not through the `client` fixture's stub, because the whole
    point is to exercise the `get_current_user` that stamps the locale.
    """
    password = f"{TEST_PASSWORD}-x"
    session.add(
        User(
            email=f"locale-{language.lower()}@example.com",
            hashed_password=get_password_hash(password),
            language=language,
            email_verified_at=None,
        )
    )
    await session.flush()
    res = await client.post(
        "/api/auth/login",
        json={"email": f"locale-{language.lower()}@example.com", "password": password},
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
