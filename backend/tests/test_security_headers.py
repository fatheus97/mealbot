"""Verify the security-headers middleware adds the expected hardening headers
to every response — including error responses (404), so a misconfigured proxy
can't trick the browser into treating an API JSON payload as HTML."""

import pytest
from httpx import AsyncClient

EXPECTED_HEADERS: dict[str, str] = {
    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'; base-uri 'none'",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "geolocation=(), microphone=(), camera=(), payment=()",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-site",
}


@pytest.mark.parametrize("header,expected", list(EXPECTED_HEADERS.items()))
async def test_security_headers_present_on_2xx(
    unauthed_client: AsyncClient, header: str, expected: str,
) -> None:
    resp = await unauthed_client.get("/health")
    assert resp.status_code == 200
    assert resp.headers.get(header) == expected, (
        f"Missing or wrong {header!r} on /health"
    )


@pytest.mark.parametrize("header,expected", list(EXPECTED_HEADERS.items()))
async def test_security_headers_present_on_404(
    unauthed_client: AsyncClient, header: str, expected: str,
) -> None:
    resp = await unauthed_client.get("/this-route-does-not-exist")
    assert resp.status_code == 404
    assert resp.headers.get(header) == expected, (
        f"Missing or wrong {header!r} on 404"
    )


async def test_csp_blocks_default_resources(unauthed_client: AsyncClient) -> None:
    """The API CSP should be strict — `default-src 'none'` means a browser
    rendering this response can't load any subresources. Guards against the
    case where a JSON response is mis-served as HTML."""
    resp = await unauthed_client.get("/health")
    csp = resp.headers["Content-Security-Policy"]
    assert "default-src 'none'" in csp
    assert "frame-ancestors 'none'" in csp
