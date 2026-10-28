# rohlik.cz integration: design

Status: designed and spiked 2026-10-28 with the owner (results at the end). Not built. Waiting on
Rohlik's written consent and on Rohlik allowlisting MealBot's redirect URI (see Terms and the spike
results).

Goal: a „Poslat do Rohlíku“ button on a plan's shopping list that puts the items into the user's own
rohlik.cz cart. The user then finishes the order in Rohlik's e-shop as usual.

## What Rohlik offers

- **No public API.** Every third-party integration found (Home Assistant, Homey, community MCP
  servers) reverse-engineers the website's private API and logs in with the user's Rohlik password.
  That route is ruled out: it means holding other people's passwords and breaking whenever the site
  changes.
- **An official MCP server**, `https://mcp.rohlik.cz/mcp`. Its protected-resource metadata points at
  the authorization server `https://identity.rohlik.cz`, which supports authorization code + PKCE
  (S256), refresh tokens, and dynamic client registration at `/connect/register`. Checked against
  the discovery metadata on 2026-10-28.
- Tools this feature needs: `batch_search_products` (up to 4 queries per call, 5 results each,
  Czech keywords), `add_items_to_cart` (`productId` + `quantity`), `get_checkout_link`. An order is
  only ever completed in Rohlik's own e-shop, so MealBot never touches payment.
- No affiliate program, only a customer referral scheme.

## Terms (MCP addendum, effective 16.01.2026)

The server is „výhradně pro zlepšení vašeho zákaznického zážitku“, and „jakékoli jiné použití je
možné pouze s předchozím písemným souhlasem Rohlik.cz“. It is also described as an experimental
service that Rohlik can change or end without notice.

MealBot calling the server on behalf of its users is that other use. The owner sent a consent request
to zakaznici@rohlik.cz on 2026-10-28; no reply yet. Until Rohlik consents in writing:

- No MealBot client is registered for production, and MealBot makes no calls to `mcp.rohlik.cz` for
  its users.
- The spike (below) runs only as the owner's personal use: his own Rohlik account, his own cart, from
  his own machine.
- `ROHLIK_ENABLED` stays off.

If Rohlik refuses, the fallback is a "copy a prompt for your AI assistant" button: the user pastes
the list into their own Claude or ChatGPT with the Rohlik connector. That is plain personal use.

## Search facts that shape the design

From a live search on 2026-10-28:

- Promoted products rank first and carry a `promoted` badge plus an `impressionId`. The top hit for
  „olivový olej“ was promoted green olives (70 g), not olive oil.
- Pack size is free text in `textualAmount`: „cca 0,53 kg“, „250 g“, „10 ks“, „500 ml“, „0,75 l“.
- Every result has a price, `inStock`, `favourite`, and `xtraMembershipRequired` where relevant.
- MealBot's shopping-list items carry only `name` (in the plan's language) and `quantity_grams`, plus
  an English `canonical_name` for countable items. No product IDs, no pack sizes.

## v1 decisions

- **Scope:** rohlik.cz only, and only on plans generated in Czech, whose item names are already Czech
  search keywords. Hidden everywhere else.
- **Entry point:** one „Poslat do Rohlíku“ button on the shopping list. It sends the unticked lines
  (ticked means already have or already bought) to a review screen.
- **Flow order:** login comes first, because searching needs the token too.
  1. The click POSTs the unticked lines, with the existing CSRF header like every mutating call.
     The backend validates them, stores them in the flow store (below) under a new flow id, and
     returns Rohlik's authorize URL as JSON. The frontend sets `window.location` to it. (A 302 in
     reply to a `fetch` POST would be followed by the browser and blocked by CORS, so the SPA would
     never navigate.)
  2. The callback is a GET from `identity.rohlik.cz` and cannot carry the CSRF header; the
     `state`/cookie check below is its protection. It finds its flow through the flow id, which
     sits in the same signed cookie as `state` and the PKCE verifier. It exchanges the code, keeps
     the token in the flow entry, and redirects straight to the review screen with only the flow
     id in the URL. It does no searching, so the user is never left looking at a blank tab.
  3. The review screen shows a loading state and fetches the candidates for that flow id. That fetch
     runs the searches: at most a few `batch_search_products` calls in flight at once (4 queries
     each), under one overall deadline. Results are cached in the flow entry, so a repeat fetch
     costs no MCP calls. A line whose search failed or timed out shows as „nenalezeno“ with a
     retry, and a retry re-searches only the failed lines. A partial failure never discards the
     lines that did match, and the flow entry stays. The limits are settings, the way
     `stripe_timeout_seconds` is:
     - `rohlik_timeout_seconds`: per MCP call
     - `rohlik_search_deadline_seconds`: the whole fetch
     - `rohlik_search_retry_cap`: retries per flow

     The endpoint also has a rate limit keyed on the authenticated user, not on the flow id,
     because a client could otherwise open new flows to get around it.
  4. The confirm POST sends the chosen product IDs and quantities, again with the CSRF header. The
     backend rejects the whole request unless:
     - every line key exists in the flow;
     - each product ID is one of the candidates stored for that line;
     - each quantity is a positive integer within a bound derived from that line, on top of the
       global cap. The bound is a small multiple of the pack count, and the backend computes that
       pack count itself from the line's need and the chosen candidate's pack size. It never
       takes the frontend's number.

     MealBot's OAuth client therefore only ever adds products that its own search returned, in
     amounts tied to the plan. Then the backend calls `add_items_to_cart` and deletes the flow
     entry.

  The flow id is unguessable (`secrets.token_urlsafe`), and every read and write of a flow entry
  checks that it belongs to the authenticated user. The callback likewise rejects a cookie whose
  flow belongs to a different user than the current session. That case gets its own test.

  The list is kept server-side rather than in `sessionStorage`, so nothing that the backend later
  acts on has to come back from the browser except the final selection, which is validated as
  untrusted input.
- **Preselection is deterministic:** drop promoted results, then take the user's favourite, then
  the first result, never an out-of-stock one. Every candidate can be swapped in.
- **Pack count is computed in the frontend:** `packs = ceil(need / parsed pack size)`. The
  piece-weight table covers `ks` items, there is a 1-pack fallback when the size can't be parsed or
  the units don't match, and every line gets −/+. Weighed („cca“) items round to the nearest pack
  count when the shortfall is under 15 %, otherwise up (decided after the spike, see below). That
  rule applies only after the size has parsed as a weight; the 1-pack fallback always wins when
  parsing fails.
- **Review screen:** price per line, an estimated total, Xtra-only prices marked, and unmatched lines
  shown as „nenalezeno“.
- **Backend:** proxies the Rohlik calls and nothing else. Everything the review screen sends back is
  untrusted input: a Pydantic model with integer product IDs, a positive integer quantity per line
  with a sane upper bound, and a capped line count. Every MCP call has a timeout and catches specific
  exceptions, in line with the rest of the codebase.
  - What comes back from `mcp.rohlik.cz` is untrusted input too. Search and cart payloads are
    parsed into Pydantic models. A missing or changed field (`textualAmount`, `price`, `inStock`)
    degrades the line to „nenalezeno“ or to the 1-pack fallback, never to a 500.
  - Product names and badges are third-party text and are rendered as text only, never as HTML.
  - The access token and the `Authorization` header never reach logs, error reports or exception
    messages.
- **Rohlik login: nothing is persisted.** The user logs in through OAuth on each send.
  - The OAuth `state`, the PKCE verifier and the flow id live between redirect and callback in a
    signed, HttpOnly cookie with `SameSite=Lax` (the callback is a cross-site navigation from `identity.rohlik.cz`,
    so `Strict` would not be sent) and a short `Max-Age` of about 10 minutes. Its `Secure` flag
    follows the existing `cookie_secure` setting, like the auth cookies. The cookie is bound to the
    MealBot session that started the flow.
  - The callback rejects any `state` that does not match the cookie, then deletes the cookie.
  - **Flow store:** a process-memory dict keyed by user and flow id. Each entry holds the validated
    list, the access token, the MCP `Mcp-Session-Id` and the search candidates. Rules:
    - TTL of about 15 minutes, which is long enough to search, review and add.
    - Expiry is checked on every read and swept on every write.
    - At most one live flow per user: starting a new one replaces the old. The state/PKCE cookie
      has one fixed name, so a second tab also replaces the first tab's cookie. The first tab's
      callback then fails its `state` check. That is accepted, and the user sees a translated
      „spusťte odeslání znovu“ message (start the send again), not a 500.
    - The entry is deleted as soon as `add_items_to_cart` returns.

    So a user who starts flows and never finishes cannot grow it. The token never goes to the
    browser, so XSS or frontend logging cannot leak it, and nothing is written to disk or the
    database. A deploy or restart drops every entry, and the user simply logs in again.
  - This works because prod runs a single uvicorn worker (`backend/Dockerfile` CMD, no
    `--workers`). If the backend ever scales out, the flow store has to move to a shared
    short-lived store, or flows fail with a re-login.
  - Local dev can only exercise the OAuth flow with a `localhost` redirect, as the spike did: dynamic
    registration rejects any other redirect URI. The production redirect needs Rohlik's allowlisting
    (see the spike results).
  - The spike measured the cost in a browser with a live Rohlik session at `identity.rohlik.cz`:
    a repeat authorization came back in 0.4 s with no login or consent screen. A browser without
    that session gets Rohlik's login screen on each send. That cost is accepted for v1.
  - The rejected alternative was an encrypted refresh token plus a Disconnect option. It needs a
    new `cryptography` dependency, a key in `.env`, deletion on account delete, and exclusion from
    the data export.
- **Gate:** the same as generation (verified email + entitled). There are no LLM calls in v1, so the
  usage cost cap is not touched.
- **Kill switch:** `ROHLIK_ENABLED`, off by default. While it is off, no host `.env` change is needed.
- **Privacy pages** (en + cs; hand-edited source, never regenerate): name Rohlik as the recipient of
  the shopping-list items the user sends, and say the Rohlik login token is used only for the send,
  held in memory for at most about 15 minutes, and never stored.

## Deferred

- LLM product picking. Only if swap telemetry (the existing edit telemetry) shows people swap
  preselections often.
- A per-recipe "buy just this" button.
- English-language plans. These need a translation step.
- Rohlik Group's other shops (Knuspr, Gurkerl, Kifli, Sezamo).
- **Shelf-life-aware rounding** (owner's idea, 2026-10-28): overbuying matters less for something
  that keeps for weeks. The „cca“ rule already covers the commonest case, because weighed items are
  mostly the perishable ones. The gap is packaged perishables, such as cooking cream rounding up to
  2 × 180 ml for 200 g. Rohlik's website shows a figure like „běžně čerstvé 30 dnů“, but the MCP
  does not expose it: neither search results nor `get_product_details` carry it, only a free-text
  „Skladování“ paragraph (checked 2026-10-28). Two ways to enable it later:
  - Rohlik exposes the freshness figure. Ask in the consent thread.
  - Reuse the receipt scanner's LLM `shelf_life_days` estimate, at one LLM call per send.

## Spike (owner's personal use only, see Terms)

1. Register a dev client through dynamic client registration with a localhost redirect. Record
   whether a `https://trymealbot.com/...` redirect URI is also accepted.
2. Authorization code + PKCE, with the owner logging in himself in his browser.
3. Search a typical Czech MealBot list, apply the preselection rule, add to his cart, verify, then
   restore his cart exactly to its prior state.
4. Check whether the refresh token works, and whether a second login skips the login and consent
   screens. That second check decides between "nothing stored" and the encrypted refresh token.

On 2026-10-28 the auto-mode classifier blocked an agent-run attempt, because it writes to a real
cart, so the owner ran the script himself the same day.

### Results (2026-10-28)

- **A `trymealbot.com` redirect cannot self-register.** Dynamic client registration answered
  `400 invalid_request`: „Redirect URI is not allowed for dynamic client registration“. A
  `localhost`-only registration was accepted (public client, `token_endpoint_auth_method: none`). So
  a production client needs Rohlik to register or allowlist MealBot's redirect URI. Production is
  blocked on Rohlik technically as well as by the terms; question 2 of the consent request covers it.
- **OAuth:** authorization code + PKCE works. The token response has `access_token` (valid 28 799 s,
  about 8 h), `refresh_token`, `id_token`, `scope`, `token_type`. A refresh succeeded, and the refresh
  token was not rotated.
- **MCP:** `rohlik_mcp` 4.1.4, protocol `2025-06-18`, with an `Mcp-Session-Id`. It exposes 58
  tools, including every tool this feature needs.
- **Search, match, cart:** 8 of 8 lines of a typical Czech list matched, for an estimated 621,14 Kč.
  The add landed exactly (each product's quantity was the old quantity plus the packs added), and
  the cart was then restored exactly to its prior 3 products and 4 units. Cart items carry
  `productId`, `quantity`, `textualAmount`, `price` and more, so the review screen needs no extra
  lookups.
- **Preselection:** the skip-promoted rule chose olive oil (1 l) over the two promoted results. For
  „rajčata“ it chose cherry tomatoes because they are the owner's favourite. That is the rule working
  as designed, and the review screen is where a swap happens.
- **Second authorization: silent, 0.4 s,** in the owner's browser, which had a live Rohlik
  session. That confirms "nothing persisted" costs nothing for users who are logged in to Rohlik.
  Users who aren't see Rohlik's login screen on each send.
- **Leftover:** the spike's dev client stays registered at Rohlik, because no registration access
  token was kept. It is harmless: a localhost-only redirect and no secret.

### Decided after the spike

- **Rounding for weighed („cca“) products (owner, 2026-10-28):** for „cca“ items only, round to the
  nearest pack count when the shortfall is under 15 %; otherwise round up. Packaged sizes (250 g,
  10 ks) always round up. The rule applies only after the size has parsed as a weight; the 1-pack
  fallback wins when parsing fails. Always rounding up had bought 2 × ~0,53 kg of chicken for a
  600 g need, about 77 % extra; the rule makes it 1 pack, an 11.7 % shortfall.
