# Landing page implementation plan (Growth phase 2)

> Scoped 2026-07-26 via a 10-agent design workflow (5 scouts → 3 independent
> architects → judge synthesis → adversarial completeness critic) plus owner
> decisions on sequencing, CTA model, and the liability gate. This is the
> reference doc for executing the plan across however many sessions it takes —
> see `ROADMAP.md` → Growth milestone → phase 2 for the one-line pointer.

## Decisions (owner, 2026-07-26)

- **Sequencing:** ship Slices 1–3 as one thrust (not staged as separate stops).
- **CTA model while registration is closed:** zero-backend `mailto:info@trymealbot.com`
  ("Request access"), fulfilled today by generating an invite link (#266). Auto-
  switches to "Get started" the moment `REGISTRATION_ENABLED` flips — no code change.
- **Liability gate:** Slice 3's PR is held from the standing auto-merge grant.
  The owner reads the final marketing copy before that PR merges (merge = deploy
  = indexed). Slices 1–2 carry no public health copy and keep normal autonomy.

## Architecture

**Vite multi-page split**: hand-authored static marketing HTML at `/`, the
existing SPA namespaced to `/app` as a second Vite entry point. One Docker
image, one nginx, one CSP — no new service.

**Why** (verified against the actual stack, not assumed):
- `frontend/src/main.tsx` mounts `<App/>` with no router and no SSR/prerender.
  A crawler or unfurl bot (`facebookexternalhit`, Slackbot, Googlebot) hitting
  an in-SPA "landing view" sees an empty `<div id="root">` — that alone rules
  out any in-App-branch approach for a page whose whole point is being read
  without executing JS.
- Prerender/SSG (react-snap, vite-plugin-prerender) rejected: forces adding
  react-router *and* a headless-chromium build dependency for one static page —
  over-engineering for what this needs.
- A separate marketing service/repo rejected: second image/CSP/toolchain for
  zero benefit.
- Authoring the landing as plain HTML/CSS lets it use real
  `@media (prefers-color-scheme)` — sidestepping the recurring white-on-white
  theme bug entirely instead of fighting the app's inline-style adaptive-default
  gamble (`.claude/rules/frontend.md`).
- The split also avoids touching `App.test.tsx` / the existing SPA test suite,
  since the landing is a wholly separate Vite entry.

## Slices (independently shippable, dependency-ordered)

### Slice 1 — SEO/meta head + self-hosted static assets (~0.5 day, near-zero risk)

App stays at `/`; zero topology change. Legitimate standalone ship.

- `frontend/index.html` `<head>`: real `<title>` (~55 chars, transparency-framed,
  e.g. "Mealbot — meal plans screened against the EU-14 allergens"),
  `<meta name=description>` (~155 chars), `<link rel=canonical
  href=https://trymealbot.com/>`, Open Graph (title/description/image/url/
  type=website/site_name/locale), Twitter `summary_large_image`, `theme-color`.
- Inert `<script type=application/ld+json>`: Organization + WebSite/
  SoftwareApplication (name/description/url/logo only — **price deliberately
  omitted**, defer to Stripe as authoritative, avoids stale structured-data
  liability). JSON-LD is data, not blocked by `script-src 'self'`.
- Create `frontend/public/` (doesn't exist today; Vite copies it verbatim to
  dist root, served from `'self'`): `robots.txt` (Allow `/`; single mechanism
  for keeping `/app` out of the index — see the noindex-only note below),
  `sitemap.xml` (single canonical `/`), a real favicon set (svg + ico +
  apple-touch-icon — **fixes the live `/vite.svg` 404 today**) + `site.webmanifest`,
  a **self-hosted** `og-image.png` (1200×630, byte-light for LCP — CSP forbids
  hotlinked/CDN images), and a Search Console verification file.
- Repoint the favicon `<link>` from `/vite.svg` to the self-hosted icon.

**Tests:** a headless Node/Vitest check over built `dist/index.html` asserting
title/description/canonical/OG/Twitter present, JSON-LD parses to valid
Organization+SoftwareApplication, and — as a CSP-compliance guard — that **no
non-origin host appears in `<head>`** (fails the build if a future edit
hotlinks a CDN/font/image). Assert every public asset referenced actually
exists in `dist`. Manual: run an OG-card validator post-deploy; confirm
favicon returns 200.

### Slice 2 — Namespace the SPA at `/app` + repoint backend deep-links (~0.5–1 day, medium risk, isolated)

No visible change. Isolates the highest-blast-radius change (invite/reset/
billing links — **merge = deploy**) in its own slice *before* the root swap,
so no single slice ever leaves prod broken.

- Add `frontend/app.html` = SPA shell (shared `<head>` minus the marketing OG
  — see the interim-window note below — plus `<meta name=robots
  content=noindex>` so this shell never competes with `/` for indexing).
- `frontend/vite.config.ts`: `build.rollupOptions.input = { main: index.html
  (still the SPA shell at this step), app: app.html }`.
- `frontend/nginx.conf`: add `location /app { try_files $uri $uri/ /app.html; }`;
  **keep** `location / { try_files $uri $uri/ /index.html; }` unchanged so the
  SPA is reachable at BOTH `/` and `/app` during the transition (any
  already-sent `/?param=` email link still works).
- Repoint the backend deep-link builders from `/?param=` → `/app?param=`
  (invite service, password-reset service, Stripe checkout/portal success URLs
  — verify the exact call sites and line numbers at implementation time, they
  may have shifted since scoping). Add a `frontend_base_url.rstrip('/')`
  normalization in backend config so `{base}/app?...` is correct regardless of
  the env value's trailing slash.
- **Pre-merge:** confirm prod `FRONTEND_BASE_URL` is exactly
  `https://trymealbot.com` (origin only, no trailing path).
- **⚠️ Do NOT add the Slice-1 marketing OG/description meta to `index.html` in
  this slice** while it's still the SPA shell — that would create a window
  where `/` unfurls rich marketing meta over a blank JS-only body. Keep
  Slice 1's meta additions scoped to what becomes the landing in Slice 3, or
  ship Slices 2+3 in the same merge if that window is unacceptable.

**Tests:** pytest asserting each link builder emits `{base}/app?param=...`
with the correct token/value and no double slash (mypy strict, no `Any` —
verify the actual round-trip, not just f-string construction, per
`feedback_review_fixes_need_review`). Frontend build test asserting
`app.html` is emitted to `dist` carrying `noindex`. Manual smoke **before**
merge: `/app?reset_token=`, `/app?invite=`, `/app?billing=success` each open
the right modal; old `/?param=` links still work. Pre-push adversarial
multi-agent review (billing/invite/reset blast radius, merge=deploy).

### Slice 3 — Static marketing landing at `/` + registration-aware CTA (~1.5–2 days, the deliverable, most of the risk)

**🔒 HELD FROM STANDING AUTO-MERGE — owner reads the final copy before this PR
merges.** Merge = deploy = indexed; the AI PR reviewer is not a liability
reviewer. Mark the PR draft or leave a required review thread unresolved until
the owner has read the body copy.

- Convert `frontend/index.html` into the landing: full static marketing
  `<body>` (see Copy outline below) + FAQPage JSON-LD generated from the
  on-page FAQ.
- Inline `<style>` (CSP `style-src` allows `'unsafe-inline'`) using **real**
  `@media (prefers-color-scheme: dark/light)` for theming and
  `@media (max-width:640px)` for mobile — no inline-style trap, no
  `useIsMobile`. Every section still commits to an explicit opaque surface +
  explicit contrasting text as a second safety net (the `admin/theme.ts`
  pattern), never hardcoded dark text on the adaptive page background.
  System-ui font stack (CSP forbids external webfonts).
- Hero + screenshots self-hosted under `frontend/public/`, each in an explicit
  width/height or aspect-ratio box (CLS/LCP).
- CTA lives in a **fixed-height reserved container** holding the safe static
  baseline (mailto "Request access" + "Log in" → `/app`).
- `frontend/src/landing/main.ts` (+ `cta.ts`): a small Vite entry (hashed,
  served from `'self'`, **typed + tsc-b + Vitest covered** — not an uncovered
  `public/*.js`) that:
  - fetches `GET /api/config` (same-origin, `connect-src 'self'` permits it)
    and swaps the CTA **in place** per `registration_enabled`/`demo_mode`;
  - forwards `utm_*` query params (and any other query string) onto the
    `/app` link so campaign attribution (`getStoredAttribution()` /
    `captureAttribution()`) isn't silently dropped by the `/` → `/app` split;
  - forwards any `reset_token`/`invite`/`billing` param on `/` to `/app` via
    `location.replace` (stragglers from old links), and redirects a
    logged-in-looking bookmark of `/` (localStorage auth hint present) to
    `/app`.
- `frontend/nginx.conf`: **pin the three-location model explicitly** (do not
  leave the catch-all ambiguous):
  - `location = / { try_files /index.html =404; }` → the landing;
  - `location /app { try_files $uri $uri/ /app.html; }` → SPA + deep links;
  - catch-all `location / { try_files $uri $uri/ /app.html; }` so any stray
    legacy deep path falls through to the app, not the marketing page or a 404.
  - Add a no-JS server-side backup: `if ($arg_invite)`/`($arg_reset_token)`/
    `($arg_billing)` on `= /` → `return 302 /app$is_args$args;` (belt and
    suspenders alongside the JS forward, for in-flight emails with JS
    disabled).
  - **Note near the new locations:** nginx does NOT inherit server-scope
    `add_header` (the CSP) into a location that declares its own
    `add_header`. Neither new location adds one today — don't add one later
    without re-declaring the full security-header set, or the CSP silently
    drops for that route.
  - Confirm Caddy/DNS redirects `www` → apex (and one trailing-slash form) so
    the served host always matches the hardcoded canonical/OG URL.
- Use `noindex` on `app.html` as the **only** mechanism keeping `/app` out of
  the index — do not also `Disallow: /app` in `robots.txt`; a disallowed path
  is never crawled, so Google can never see the `noindex` on it, making the
  two mechanisms self-defeating together.
- `frontend/vite.config.ts`: the `index.html` entry now loads
  `/src/landing/main.ts`, not `/src/main.tsx`.

**Tests:**
- Vitest for the enhancement logic (mocked fetch): config `null` → baseline
  CTA unchanged (no flash); `registration_enabled===true` → "Get started" →
  `/app`; `===false` → "Request access" mailto + "Log in"; `demo_mode===true`
  → "Try the demo" revealed; param-forward fires for
  reset_token/invite/billing and *not* for a plain visit; logged-in-hint
  redirect fires; assert identical container height across every state (CLS).
- **Body-copy liability test** (from the adversarial critic — enforce the
  guardrail, don't just rely on review convention): assert over built
  `dist/index.html` that (1) the verbatim `DietarySelector` disclaimer string
  is present, and (2) a denylist of forbidden phrases — "safe for your
  allergy", "allergen-free", "hypoallergenic", "clinically approved",
  "doctor-recommended", any cures/treats/prevents claim — matches **zero**
  times, failing the build on any hit.
- Head/meta regression test extended from Slice 1.
- **Mandatory manual** (`.claude/rules/frontend.md`): two-theme dark then
  light (`resize_window colorScheme`, compare computed `color` vs
  `background`); mobile at 375px; CLS check on CTA + hero; `curl`/
  `view-source` of `/` with JS disabled shows the full marketing copy (proves
  crawler-readability); `/app?invite=`/`?reset_token=`/`?billing=` all reach
  the right SPA modal; response-header check that `/` and `/app` both still
  carry the full CSP.
- Pre-push adversarial multi-agent review (root swap + theme + routing).

### Slice 4 — DEFERRED, owner-gated: analytics and/or waitlist (~+1 day if chosen, not in core estimate)

Out of core scope for now.

- If a launch email list is wanted instead of the mailto baseline: new
  `POST /api/waitlist` (Pydantic request+response, rate-limited, email
  normalize+dedup, Alembic migration with a **descriptive** revision id + a
  single-head re-check right before merge per
  `reference_alembic_revision_id_collision`, GDPR purpose + deletion path) +
  a landing form (`form-action 'self'`) reusing `getStoredAttribution()`.
- If analytics: **same-origin, self-hosted/proxied only** — a vendor beacon
  (gtag/Plausible CDN) is double-blocked by `script-src 'self'` +
  `connect-src 'self'`; do not relax the CSP to accommodate one.
- **Recommendation (and the owner's call for now): skip this.** The mailto
  baseline sidesteps a new unauthenticated write surface and personal-data
  obligations, and the shipped invite system (#266) already fulfills "request
  access."

## Copy outline (led by the differentiator, transparency not endorsement)

1. **Hero** — headline leads with the differentiator ("Meal plans that
   respect every diet and allergen you combine"), transparency-voiced subhead
   ("Every recipe is screened against the 14 EU-regulated allergens and their
   common derivatives, with dietary rules grounded in cited public-health
   sources"), registration-aware CTA + "Log in", self-hosted dimensioned hero
   visual.
2. **The differentiator** — diets stack (e.g. vegan + low-FODMAP + a tree-nut
   allergy at once); name the EU-14 allergens verbatim; mention
   impossible/high-risk combos are detected and escalated as *guidance*
   ("suggests consulting a dietitian"), never a medical determination. Close
   with the shipped `DietarySelector` disclaimer **verbatim**.
3. **Evidence-grounded pillar** — name the citable bases (EU FIC 1169/2011,
   EFSA, USDA/FSIS, Monash low-FODMAP, WHO weaning). "Grounded in", never
   "endorsed by."
4. **How it works** — plan → shop → cook, three steps, self-hosted dimensioned
   screenshots.
5. **Pricing** — €4.99/mo or €2.99/mo billed annually (€35.88/yr), 10-day free
   trial. Mention the launch feedback credit as a light promo line, not a
   headline price. State Stripe checkout as authoritative for the exact
   figure.
6. **FAQ** (feeds FAQPage JSON-LD) — including "Is this medical or dietary
   advice?" (No — screens and cites sources; not a guarantee; consult a
   professional and check labels) and "Is it available now?" (private alpha —
   request access / existing members log in).
7. **Access** — honest "private alpha" framing; never implies open signup.
8. **Transparency footer** — the liability statement + contact.

## Liability guardrails (enforced, not just advisory)

- Transparency verbs only: "screened against", "flags", "cites", "grounded
  in", "checks for". **Forbidden:** "safe for your allergy", "allergen-free",
  "hypoallergenic", "clinically approved", "doctor-recommended", any
  cures/treats/prevents claim.
- Reuse the shipped `DietarySelector` disclaimer verbatim.
- Describe allergen derivative coverage as "common derivatives" — never
  "complete" or "exhaustive."
- Price omitted from JSON-LD; Stripe is authoritative for the live figure.
- CTA never implies open registration while `registration_enabled=false` — no
  live "Sign up" that would 403.
- **Owner liability read required before Slice 3's PR merges** (see Decisions
  above) — this overrides the standing auto-merge grant for this one PR only.

## Out of scope

- react-router or any SSR/prerender/SSG framework.
- A separate marketing service/repo/static host.
- Third-party analytics or any external webfont/CDN (CSP-incompatible).
- The waitlist endpoint (Slice 4) — deferred, owner-gated, mailto is the
  default.
- Flipping `REGISTRATION_ENABLED` — remains the owner's parked
  product-readiness call; this page does not open registration and does not
  nudge toward flipping.
- Automated visual-regression (Playwright dark+light snapshots) — tracked
  under ROADMAP U-8; the mandatory manual two-theme/mobile/CLS/no-JS check is
  the guardrail until then.
- Intro tours / coach-mark popups.

## Total effort

~3–4 focused solo-dev days for Slices 1–3 (owner chose to ship all three as
one thrust), plus the CI/review loop. Frontend Vitest/Vite runs in the
`node:26` Docker recipe (host can't run it); `tsc -b` + eslint run on the host
as pure JS. Merge = prod deploy — verify both themes and every deep link
end-to-end before each merge, and remember Slice 3 is held for the owner's
liability read regardless of CI/AI-review status.
