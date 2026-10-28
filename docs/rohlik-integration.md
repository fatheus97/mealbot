# rohlik.cz integration: design

Status: designed 2026-10-28 with the owner. Not built. Waiting on Rohlik's written consent (see Terms).

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
- **Preselection is deterministic:** drop promoted results, then take the user's favourite, then
  the first result, never an out-of-stock one. Every candidate can be swapped in.
- **Pack count is computed in the frontend:** `packs = ceil(need / parsed pack size)`. The
  piece-weight table covers `ks` items, there is a 1-pack fallback when the size can't be parsed or
  the units don't match, and every line gets −/+.
- **Review screen:** price per line, an estimated total, Xtra-only prices marked, and unmatched lines
  shown as „nenalezeno“.
- **Backend:** proxies the Rohlik calls and nothing else.
- **Rohlik login: nothing is stored.** The user logs in through OAuth on each send. The access token
  passes through MealBot's backend only for that send and is never written anywhere. The OAuth
  `state` and PKCE verifier live between redirect and callback in a short-lived, signed, HttpOnly
  cookie, not a table. If the spike shows that logging in every time is annoying, the alternative is
  an encrypted refresh token plus a Disconnect option in Settings. That needs a new `cryptography`
  dependency, a key in `.env`, deletion on account delete, and exclusion from the data export.
- **Gate:** the same as generation (verified email + entitled). There are no LLM calls in v1, so the
  usage cost cap is not touched.
- **Kill switch:** `ROHLIK_ENABLED`, off by default. While it is off, no host `.env` change is needed.
- **Privacy pages** (en + cs; hand-edited source, never regenerate): name Rohlik as the recipient of
  the shopping-list items the user sends, and say the Rohlik login token is used only during the send
  and is not stored.

## Deferred

- LLM product picking. Only if swap telemetry (the existing edit telemetry) shows people swap
  preselections often.
- A per-recipe "buy just this" button.
- English-language plans. These need a translation step.
- Rohlik Group's other shops (Knuspr, Gurkerl, Kifli, Sezamo).

## Spike (owner's personal use only, see Terms)

1. Register a dev client through dynamic client registration with a localhost redirect. Record
   whether a `https://trymealbot.com/...` redirect URI is also accepted.
2. Authorization code + PKCE, with the owner logging in himself in his browser.
3. Search a typical Czech MealBot list, apply the preselection rule, add to his cart, verify, then
   restore his cart exactly to its prior state.
4. Check whether the refresh token works, and whether a second login skips the login and consent
   screens. That second check decides between "nothing stored" and the encrypted refresh token.

On 2026-10-28 the auto-mode classifier blocked an agent-run attempt, because it writes to a real
cart. The owner runs the script himself, or approves it explicitly.
