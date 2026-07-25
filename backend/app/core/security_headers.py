from collections.abc import Awaitable, Callable

from fastapi import Request, Response

# The backend serves JSON only — never HTML, never scripts, never fonts.
# `default-src 'none'` blocks every resource type by default; the browser will
# refuse to load anything from these responses even if a payload were ever
# coerced into being interpreted as HTML.
_API_CSP = "default-src 'none'; frame-ancestors 'none'; base-uri 'none'"

_HEADERS: dict[str, str] = {
    "Content-Security-Policy": _API_CSP,
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    # camera=(self): same-origin camera for the frontend's receipt-scan getUserMedia
    # flow (an empty camera=() blocked the browser prompt — mealbot-tickets#4). Kept
    # in parity with the frontend nginx header; inert on these JSON-only responses,
    # but parity avoids a future "re-sync" silently reintroducing camera=().
    "Permissions-Policy": "geolocation=(), microphone=(), camera=(self), payment=()",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-site",
}


async def security_headers_middleware(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    response = await call_next(request)
    for name, value in _HEADERS.items():
        response.headers.setdefault(name, value)
    return response
