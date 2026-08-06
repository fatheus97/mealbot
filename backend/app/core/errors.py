"""Error responses whose ``detail`` is written in the reader's language.

─── Why the translation happens in a HANDLER, not at the raise site ────────────
The obvious version passes a locale down to every function that raises. That
means a ``locale`` parameter on every router signature, then on every service
they call, then on the services those call — for something only the outermost
layer ever uses. Threading a value through a dozen signatures so one of them can
format a string is exactly the plumbing that makes a codebase resistant to the
NEXT change.

So the raise site names WHAT went wrong (``ErrorKey``) and nothing else, and one
handler — which holds the ``Request``, and therefore both candidate locales —
turns that into a sentence. Services keep their signatures. Adding a locale is a
dictionary entry, not a refactor.

─── The English detail is set eagerly, and that is deliberate ──────────────────
``LocalizedHTTPException`` fills in ``self.detail`` with the ENGLISH sentence at
construction, exactly as the plain ``HTTPException`` it replaces did. It is
never read on the normal path — the handler builds the response — but it means
that if one of these is ever raised somewhere the handler does not cover (a
background task, a unit test constructing one directly, an ASGI app assembled
without ``register_error_handlers``), the behaviour degrades to precisely
today's rather than to a 500 or an empty body.

─── Locale precedence ──────────────────────────────────────────────────────────
1. ``request.state.locale`` — stamped by ``get_current_user`` from
   ``User.language``. A logged-in user's chosen language always wins, because it
   is a deliberate choice and the header is whatever their browser shipped with.
2. ``Accept-Language`` — the only signal on the logged-out paths (failed login,
   registration, password reset), which is most of what this module exists for.
3. English.

─── Plurals are WHOLE SENTENCES, not a noun with an ending ─────────────────────
``PluralErrorKey`` names a base; the copy holds ``{base}_{category}``, and each
variant is a complete sentence. Czech is why: the count governs case across the
clause, so "N cookbook recipe(s)" cannot be assembled by picking an ending —
1 recept / 2 recepty / 5 receptů, and the verb phrase after it shifts too. This
is the same one-key-per-sentence rule the frontend dictionaries follow.

─── Still not here ─────────────────────────────────────────────────────────────
No ``headers`` and no machine-readable ``extra`` dict. The usage-cap 429 in
``deps.py`` is the only raise that wants either — it sets ``Retry-After`` and
returns the object-``detail`` shape ``extractErrorDetail`` understands — and it
keeps its plain ``HTTPException`` until someone migrates it and can test what
they added.
"""

from __future__ import annotations

from typing import Final, get_args

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from app.core.error_copy import ERROR_COPY, ErrorKey, PluralErrorKey
from app.core.i18n import (
    DEFAULT_LOCALE,
    Locale,
    locale_from_accept_language,
    plural_category,
    render,
)

#: Derived, never hand-listed — a second copy of these names would be one more
#: thing to keep in step with `PluralErrorKey`.
PLURAL_KEYS: Final[frozenset[str]] = frozenset(get_args(PluralErrorKey))


class LocalizedHTTPException(HTTPException):
    """An ``HTTPException`` that names its message instead of spelling it out.

    ``count`` is required for a plural key and rejected for a static one, and
    that pairing is checked here rather than by the type system. Overloads were
    the obvious way to get it at compile time and do not actually work: the
    static signature ends in ``**params: str``, which can itself absorb a
    ``count=`` argument, so the two overloads overlap and mypy rejects any
    implementation covering both.

    Runtime is a fair place for it. The English ``detail`` is rendered during
    ``__init__``, so a mismatched pair fails the moment the raise executes —
    the first time its branch runs under test, not once a user reaches it.
    """

    def __init__(
        self,
        status_code: int,
        key: ErrorKey | PluralErrorKey,
        *,
        count: int | None = None,
        **params: str,
    ) -> None:
        if (count is None) != (key not in PLURAL_KEYS):
            raise ValueError(
                f"{key!r}: `count` is required for a plural key and not "
                f"accepted for any other (got count={count!r})"
            )
        self.key = key
        self.count = count
        self.params = params
        super().__init__(
            status_code=status_code,
            detail=self.render_for(DEFAULT_LOCALE),
        )

    def render_for(self, locale: Locale) -> str:
        lookup: str = self.key
        values = dict(self.params)
        if self.count is not None:
            lookup = f"{lookup}_{plural_category(locale, self.count)}"
            values["count"] = str(self.count)
        return render(ERROR_COPY[locale][lookup], **values)


def resolve_locale(request: Request) -> Locale:
    """Which language to answer this request in. See module docstring."""
    # `request.state` raises AttributeError for an unset name rather than
    # returning None, hence getattr with a default. The attribute is absent on
    # every unauthenticated request, and on any error raised BEFORE
    # get_current_user finishes — which is most of what lands here.
    stamped: Locale | None = getattr(request.state, "locale", None)
    if stamped is not None:
        return stamped
    return locale_from_accept_language(request.headers.get("accept-language"))


async def localized_exception_handler(
    request: Request, exc: Exception
) -> JSONResponse:
    """Render a ``LocalizedHTTPException`` in the reader's language.

    Typed as ``Exception`` because that is the signature Starlette's handler
    registry declares; the ``isinstance`` narrowing is what makes that honest
    for mypy. The re-raise is unreachable in practice — the handler is only ever
    registered against ``LocalizedHTTPException``.
    """
    if not isinstance(exc, LocalizedHTTPException):  # pragma: no cover
        raise exc
    return JSONResponse(
        {"detail": exc.render_for(resolve_locale(request))},
        status_code=exc.status_code,
    )


def register_error_handlers(app: FastAPI) -> None:
    """Wire the handler up. Called once, from ``app.main``.

    Starlette resolves handlers by walking ``type(exc).__mro__``, so registering
    the subclass takes precedence over the built-in ``HTTPException`` handler
    that every un-migrated raise in the codebase still goes through.
    """
    app.add_exception_handler(LocalizedHTTPException, localized_exception_handler)
