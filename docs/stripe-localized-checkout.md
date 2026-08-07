# Localizing the Stripe checkout

Two separate things decide what language a customer sees on Stripe's hosted
pages, and only one of them is code.

| What | Controlled by | Status |
|---|---|---|
| Stripe's own chrome ("Try Mealbot", "Then €4.99 per month starting…") | the `locale` we send | **done in code** — follows the app's UI language |
| The product **name** and **description** on the line item | your Stripe **Product** | needs the setup below |
| Czech plural glitches like `10 dny/dní zdarma` | Stripe's own translations | **not ours** — report to Stripe support |

## 1. The chrome (already done)

`create_checkout_session` and `create_portal_session` pass an explicit
`locale=`, read from `Accept-Language` — which `authFetch` sets to the SPA's
chosen UI locale.

This replaced Stripe's default `locale="auto"`, which resolves from the
browser/IP. That is why the page came up Czech for a Czech-based user **no
matter which language they had picked in the app**: `auto` never saw the app's
setting. Nothing to configure; it works as soon as the code is deployed.

## 2. The product name and description (needs a second Product)

**Stripe stores exactly one name and one description per Product.** There is no
localized-name field, and no way to override it per Checkout session —
`price_data` would mint an ad-hoc Price, which breaks the annual allow-list in
`annual_price_ids()` and therefore the feedback-credit eligibility check.

So Czech copy needs its own Product, and a Product's Prices belong to it —
meaning a Czech Product needs its own monthly and annual Prices.

### Decide first: is this worth it?

You do **not** have to do this. The cheaper option is to stop the product copy
from carrying language at all:

- Name → `Mealbot` (a brand name reads correctly in any language)
- Description → empty

The customer arrived from a paywall that already explained the product in their
own language, and Stripe's chrome around the line item is now localized. An
English sentence repeating the pitch adds little and mismatches half your
audience. **This is the recommended option** — one Product, no drift, no extra
Prices to keep in sync.

Do the rest of this page only if you want genuinely Czech product copy.

### Setup

1. Stripe Dashboard → **switch to Live mode** (top-right toggle). Test mode has
   its own separate objects; editing those changes nothing customers see. This
   is the step people skip.
2. **Product catalog → Products → + Add product**.
3. Name it (e.g. `Mealbot`) and give it the Czech description
   (e.g. `Neomezené AI jídelníčky a recepty`).
4. Add a **recurring monthly** Price: `4,99 EUR`, billing period *Monthly*,
   and set **tax behaviour to inclusive** — matching the existing Prices, since
   the operator is a Czech OSVČ/neplátce and the sticker price is what is
   charged.
5. Add a second **recurring yearly** Price on the same Product: `35,88 EUR`,
   billing period *Yearly*, tax behaviour inclusive.
6. Copy both Price ids (`price_…`).
7. On the box, add them to `/opt/mealbot/.env`:

   ```
   STRIPE_PRICE_ID_CS=price_...
   STRIPE_PRICE_ID_ANNUAL_CS=price_...
   ```

8. Recreate the backend so it re-reads the env file — **`up -d`, never
   `restart`** (`restart` reuses the container's old environment):

   ```bash
   cd /opt/mealbot && docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d backend
   ```

9. Verify:

   ```bash
   docker compose -f docker-compose.yml -f docker-compose.prod.yml exec backend \
     python -c "from app.core.config import settings; print(settings.stripe_price_id_cs, settings.stripe_price_id_annual_cs)"
   ```

Until step 7, **both variables are unset and every locale uses the baseline
Prices** — the exact behaviour from before this feature existed. The code ships
inert; nothing breaks if you never do this.

### The one thing that must not be forgotten

`STRIPE_PRICE_ID_ANNUAL_CS` is counted by `annual_price_ids()`, which is what
`is_annual()` uses to exclude annual subscribers from the **monthly-only**
launch feedback credit.

A Czech annual subscriber sits on a *different* Price id than an English one. If
that id were not in the allow-list they would read as monthly and be granted
real euros they should not get — the same failure shape as the Price-rotation
blind spot the `stripe_price_ids_annual_legacy` list exists for. It is wired in
code and covered by `test_czech_annual_price_counts_as_annual`, so it cannot be
forgotten by whoever sets the env var — but if you ever add a *third* locale,
that wiring is the thing to extend.

### Prices are never edited, only replaced

Stripe Prices are immutable. Changing an amount means creating a new Price and
retiring the old one — and any annual id you retire must be appended to
`STRIPE_PRICE_IDS_ANNUAL_LEGACY`, or grandfathered subscribers on the old id
start reading as monthly.
