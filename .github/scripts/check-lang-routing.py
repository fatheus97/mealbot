"""Check the production nginx's language routing against a running container.

Usage: python3 .github/scripts/check-lang-routing.py [base_url]
(default http://localhost:8080, the "frontend security headers" CI job's port).

nginx sends a visitor arriving from OUTSIDE the site, whose browser prefers
Czech or Slovak, from /, /privacy and /terms to the Czech editions
($lang_to_czech in frontend/nginx.conf). The browser cases come from
frontend/src/test/fixtures/accept-language.json, the same table Vitest holds
detectLocale() to, so the server and the app cannot disagree about who gets
Czech. Exits non-zero on any mismatch.
"""

import http.client
import json
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit

BASE = urlsplit(sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8080")
FIXTURE = Path(__file__).resolve().parents[2] / "frontend/src/test/fixtures/accept-language.json"
PAGES = {"/": "/cs", "/privacy": "/cs/privacy", "/terms": "/cs/terms"}
CZECH = {"Accept-Language": "cs-CZ,cs;q=0.9,en;q=0.8"}
SELF = f"{BASE.scheme}://{BASE.netloc}"

failures: list[str] = []


def get(path: str, headers: dict[str, str]) -> tuple[int, str | None, str | None]:
    conn = http.client.HTTPConnection(BASE.hostname, BASE.port or 80, timeout=5)
    try:
        conn.request("GET", path, headers=headers)
        resp = conn.getresponse()
        resp.read()
        return resp.status, resp.getheader("Location"), resp.getheader("Content-Security-Policy")
    finally:
        conn.close()


def expect(name: str, path: str, headers: dict[str, str], status: int, location: str | None = None) -> None:
    got_status, got_location, csp = get(path, headers)
    ok = got_status == status and got_location == location and csp is not None
    print(f"{'ok  ' if ok else 'FAIL'} {name}: GET {path} -> {got_status} {got_location or ''}")
    if not ok:
        failures.append(f"{name}: expected {status} {location or ''}, got {got_status} {got_location or ''}"
                        + ("" if csp else " (no CSP header)"))


cases = json.loads(FIXTURE.read_text(encoding="utf-8"))["cases"]
for case in cases:
    headers = {"Accept-Language": case["header"]} if case["header"] else {}
    label = case["header"] or "(no Accept-Language)"
    for page, czech_page in PAGES.items():
        if case["czech"]:
            expect(label, page, headers, 302, czech_page)
        else:
            expect(label, page, headers, 200)

expect("query string and campaign tags survive", "/?utm_source=fb&utm_campaign=x", CZECH, 302,
       "/cs?utm_source=fb&utm_campaign=x")
expect("from an external site", "/", {**CZECH, "Referer": "https://www.facebook.com/"}, 302, "/cs")
expect("from a look-alike host", "/", {**CZECH, "Referer": f"https://{BASE.hostname}.evil.example/"}, 302, "/cs")
expect("from our Czech landing", "/", {**CZECH, "Referer": f"{SELF}/cs"}, 200)
expect("from our English landing", "/privacy", {**CZECH, "Referer": f"{SELF}/"}, 200)
expect("from our https origin", "/terms", {**CZECH, "Referer": f"https://{BASE.hostname}/cs/terms"}, 200)
expect("Czech pages never redirect", "/cs", {"Accept-Language": "en-US"}, 200)
expect("Czech legal pages never redirect", "/cs/terms", {"Accept-Language": "en-US"}, 200)
expect("an emailed-token forward still wins", "/?invite=abc", CZECH, 302, "/app?invite=abc")

# Every quantifier in the map is possessive. A header built to make a
# backtracking regex explode must still answer at once.
hostile = {"Accept-Language": " x ," * 1900 + "en"}
started = time.monotonic()
expect("a crafted header", "/", hostile, 200)
elapsed = time.monotonic() - started
print(f"     ({elapsed * 1000:.0f} ms)")
if elapsed > 1.0:
    failures.append(f"a crafted Accept-Language took {elapsed:.2f}s: the map regex backtracks")

if failures:
    print(f"\n{len(failures)} language-routing check(s) failed:")
    for failure in failures:
        print(f"::error::{failure}")
    sys.exit(1)
print(f"\nall language-routing checks passed ({len(cases)} browser cases x {len(PAGES)} pages + edge cases)")
