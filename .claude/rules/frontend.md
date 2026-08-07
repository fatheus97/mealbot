---
description: Rules for frontend React/CSS code
paths: ["frontend/**"]
---

# Frontend Rules

## Theme / colour contrast — CHECK THIS EVERY TIME (recurring bug)
`frontend/src/index.css` is the **stock Vite template**: it is **dark-by-default**
(`background-color:#242424`, light text) and only turns light under
`@media (prefers-color-scheme: light)`. The app has **no designed theme system** —
it stays legible in dark mode purely by leaning on the browser's *adaptive default
text colour*. This has repeatedly caused white-on-white / dark-on-dark bugs in OS
dark mode. So:

- **Never hardcode a light-theme colour that assumes a light background.** Dark
  text (`#111`, `#374151`, …) placed directly on the page background is invisible
  in dark mode; an element with `background:#fff` and **no explicit `color`**
  inherits the light default text → white-on-white in dark mode.
- **Rule of thumb: whenever you set a `background`, set an explicit contrasting
  `color` too.** For a block of content, pick ONE and be consistent: either put it
  on an explicit surface (`background` + explicit dark `color`, e.g. a light card),
  or leave text colour to the adaptive default. The trap is mixing them —
  hardcoded dark text on the adaptive (transparent) page background.
- Inline styles can't use `@media (prefers-color-scheme)` (same reason
  `useIsMobile` exists for responsiveness). To be theme-aware, use a
  self-contained explicit surface, or a `matchMedia`-driven hook.

## Verify BOTH colour schemes before shipping ANY visible UI change (mandatory)
Drive the browser preview and check **dark AND light**. For EACH scheme:
`resize_window { colorScheme: … }`, **then `navigate` to the page again so the app
BOOTS under it** (see below — without the reload you measure the other scheme),
then confirm real contrast — compare computed `color` vs `background` (via
`javascript_tool` / `getComputedStyle`) or a screenshot. A two-theme check is
**not optional** for visible changes; the white-on-white bug has shipped more
than once.

**Why the reload: `resize_window` fires no `change` event.** It changes what
`matchMedia("(prefers-color-scheme: dark)").matches` RETURNS, but does not
dispatch `change` to listeners. Measured directly in #407: a listener armed
before the flip stayed empty (`[]`) while `.matches` went `false → true`. So
React never re-renders, `usePrefersDark` keeps its **mount-time** value, and
every `PAGE_TEXT.x[scheme]` colour on screen belongs to the OTHER scheme. That
reported the mode tabs at 2.54:1 "in light" — they were still painting their dark
`#60a5fa`/`#9ca3af` on a white page. After the reload, re-check a known
theme-following value (the active tab is `#2563eb` light / `#60a5fa` dark) to
prove the boot took.

This one lies in the **false-failure** direction, so it burns time rather than
shipping a bug — but the same stale render would hide a real failure just as
easily, and an agent that "fixes" the phantom makes the live scheme worse.

**You are not the only guardrail — `frontend/src/test/contrast.ts` is.** That suite
does WCAG AA maths on **every inline background/foreground pair in the app source**,
in **both** schemes, and carries negative controls asserting the exact colours that
shipped each past bug still fail. It runs in CI (`npm test`, inside the `frontend
build` job). It is block-based and reads the `bg`/`text`/`fg` shorthands too, so
multi-line `style={{ … }}` objects and palette records are **not** blind spots —
both were hardened after they shipped bugs, and both have dedicated tests. Don't
second-guess a green run on those shapes.

The browser pass covers what static source analysis genuinely cannot reach:
- **a foreground declared with no background beside it** — the suite says so
  itself (`contrast.ts:274`, "the important half"): it can't know which ancestor
  surface the text lands on;
- **contrast killed by an ancestor's `opacity`**, which no per-declaration check sees;
- **colours computed at runtime** — template literals, values from props or state;
- **anything not an inline style** — CSS classes, `index.css` itself.

As `contrast.ts` puts it, the browser pass is "the only one that knows what
actually composites". The layers are complementary; none is sufficient alone.

**Carve-out — no browser tool, no pretending.** Some agents run without a browser
(the `/work-tickets` cloud routine's toolset is `Bash, Read, Write, Edit, Glob,
Grep`). If you cannot drive a preview, do **not** silently skip the check and do
**not** claim you ran it. Instead:
- say so plainly in the PR body — "no browser available in this environment;
  two-theme check not run, relying on the contrast suite";
- and if the diff **introduces or changes a colour, background, or `opacity`**, ask
  the owner to eyeball it rather than auto-merging. A diff that touches no colour at
  all (layout, `zIndex`, `boxSizing`, event handling) has nothing for the two-theme
  check to find — ship it.

(A proper automated visual-regression setup — Playwright snapshots in dark+light —
is the long-term fix for the residual; tracked under ROADMAP "Frontend E2E (U-8)".)

### The sweep is easy to get wrong in the direction of "clean"
Seven PRs (#370, #375, #379, #381, #385, #386, #392) were spent on this. Every
false-clean came from the measurement, not the eye. A sweep MUST:
- **walk the background up to and INCLUDING `document.documentElement`.** index.css
  paints `#242424` on `:root`; stopping at `<body>` finds nothing and silently
  compares against a white default. This produced a full clean report over a page
  with three real failures.
- **start that walk at the ELEMENT ITSELF, not `el.parentElement`.** A `<button>`
  paints its own `backgroundColor`; skipping straight to the parent reads white
  text against whatever is *behind* the button and calls it 1:1. In #407 that
  turned six passing controls ("Generate recipe", "Mark as cooked", the FAB
  glyphs) into fake failures in one sweep. Starting at `el` is strictly safer —
  a transparent element just falls through to the parent on the first iteration.
- **composite alpha AND multiply `opacity` up the ancestor chain.** A group
  `opacity` on a container dims every descendant, and it is invisible to the
  static pair scan — PlanCalendar's month cells dimmed enabled chip BUTTONS to
  2.33:1 while the guard happily reported their undimmed ratios.
- **exclude two things, or drown in false positives:** `el.disabled` /
  `aria-disabled` (WCAG 1.4.3 and 1.4.11 EXEMPT inactive controls — a disabled
  button at 2.43:1 is not a finding), and `background-clip: text` (gradient
  headings compute `color: transparent`, i.e. a fake 1:1).

### Coverage is the harder half — one tab is not the component
The recurring miss was never technique, it was **which pixels were on screen**.
Sweeps sat on the Plan Ahead tab and the healthy page for four PRs, so CookNowForm
was never rendered once and error alerts (which need a failed request) never
existed. #385 then fixed four sites at 2.08–2.40:1 that four prior PRs walked past.
Reaching the hard states:
- **error/empty states** — stub `window.fetch` to 500 the call, then measure the
  alert as actually rendered. Do not measure a synthetic probe element and call it
  a render.
- **admin panels** (`is_admin` is server-set, so there is no UI path) — grant it to
  the throwaway demo account, then use the passwordless Try Demo login. **Local dev
  DB only.**
  ```powershell
  'UPDATE "user" SET is_admin = true WHERE is_demo = true;' | docker compose exec -T db psql -U user -d mealbot
  ```
  Run from the repo root (compose needs `.env`), and set it back to `false` after.
  This surfaced **15 live failures across 5 of 6 panels** that the static check
  could only describe as "one constant is 2.43:1".

  Three things about that grant, so nobody has to re-derive them:
  - **Never point it at prod.** `-U user` is the local role and fails there anyway
    (prod is `-U mealbot -d mealbot`) — a lucky guardrail, not a designed one, so
    do not "fix" the credentials to make it work against the box.
  - **It cannot leak into a later session**, even if you forget the revert: every
    Try Demo mints a *fresh* user with `is_admin` defaulted false
    (`create_ephemeral_demo_user`), and `cleanup_expired_demo_users` deletes demo
    rows older than `demo_session_expire_minutes` (120). `WHERE is_demo = true`
    only ever touches rows alive at that instant. Revert anyway — bounded is not
    the same as clean.
  - **Do NOT "simplify" this to logging in as `admin@mealbotdev.com` or
    `admin@test.com`.** Both are `is_admin` in the local dev DB and both
    look like the tidier option, but reaching them means typing a password into a
    login form — which an agent must not do, even with dev credentials the owner
    supplies. The demo account is used here *because* its login is passwordless.
    If you need a real account, ask the owner to authenticate.
- **cook mode / a plan** needs a real LLM call — say so rather than counting it.

### What the static guards do and do not see (`frontend/src/test/contrast.ts`)
`findInlineColorPairs` (background+colour in one style OBJECT — block-based and
quote-aware, reads `background`/`backgroundColor`/`bg` × `color`/`text`/`fg`),
`findUncoloredControls` (a control that overrides its background but sets no
colour → UA `buttontext`), `findKeywordColors` (bare `red`/`green`/… with no
background to pair against), and constants asserted against `THEME`.
**Still blind to ancestor `opacity`** — only the browser pass catches that.
That scan has been holed five times and each hole reported GREEN over a live
failure, so: **patching the trigger that bit you is not fixing the class.**
`https://` → lookbehind → protocol-relative `//cdn…` still slipped through →
quote-tracking. `bg`/`text` → `fg` still hidden. Fix by construction.

### Negative-control the control
Revert the fix and confirm **which** assertion fails. Twice a test that looked
like a control passed either way — the URL pair in #375 (both assertions returned
`[]` under the broken regex) and the brace tests in #386 (a stray `{`
self-corrects; only a stray `}` truncates). Label the rest as regression cover.

## Layout stability / CLS — don't shift content under the user's cursor (recurring bug)
Conditionally rendering a block **in document flow** (`{cond && <Bar/>}` for a
selection bar, banner, toast, spinner, inline error) pushes everything below it down
the moment it mounts — the classic **Cumulative Layout Shift (CLS)**. This shipped
on the admin bulk-actions bar (#268): selecting a row jumped the whole user table
down, so the control the user was reaching for slid out from under the cursor. The
app is 100% inline styles with lots of `{cond && …}` rendering, so the trap is
everywhere. So:

- **Anything that toggles on/off over existing content** (selection bars, toasts,
  "N selected" banners, inline validation) must **not** land in flow above content
  the user is about to click. Either float it — `position: fixed`/`absolute` is out
  of flow and shifts nothing (what #268 switched to) — or **reserve the space** up
  front (an always-present fixed-height container whose contents swap).
- **Images / async embeds:** give an explicit `width`/`height` (or an aspect-ratio
  box) so they don't reflow when they load.

### The three Core Web Vitals (what Search Console grades)
A moving/janky page is a real UX defect, not just a metric. **CLS** (above) is the
one that keeps biting at the component level; the other two are more architectural —
worth knowing, rarely a per-change item:
- **LCP (Largest Contentful Paint)** — render speed of the biggest above-the-fold
  element. A bundle-size / image-weight / server-response concern; watch it when
  adding a heavy dep or a large hero image.
- **INP (Interaction to Next Paint)** — input responsiveness (replaced FID in 2024).
  Don't do heavy synchronous work in a click/keydown handler — same "never block the
  event loop" spirit as the backend. react-query already runs fetches asynchronously,
  so data loading doesn't stall interactions; the risk is your own sync work.

## iOS zoom on form fields — the one `!important` in the project (#365)
iOS zooms the whole viewport when a focused `input`/`select`/`textarea` renders
**below 16px**, and does **not** zoom back out on blur. The floor is pinned under
`@media (max-width: 640px)`:

```css
input:not([type="checkbox"]):not([type="radio"]), select, textarea {
  font-size: 16px !important;   /* !important ONLY in src/index.css */
  min-height: 40px !important;
}
```

**Two stylesheets carry this rule, because there are two builds and neither
inherits the other's CSS** (`vite.config.ts` has four HTML entry points; only
`app.html` loads `src/index.css`):

| sheet | pages | `!important`? |
|---|---|---|
| `frontend/src/index.css` | `app.html` (the React SPA) | **yes** — the app is 100% inline `style={}` and had to be outranked |
| the inline `<style>` in `frontend/index.html` | the marketing landing page | **no** — nothing there carries an inline style |

`privacy.html` / `terms.html` have no form control at all, so they carry no floor.
**Add one if you ever add a field to them** — they inherit nothing.

- **That `!important` is deliberate and load-bearing — don't remove it.** Inline
  styles outrank author stylesheets, so without it *every* component that pinned
  its own `font-size` silently opted its field out of the guard. Twelve had, over
  two years, and the CSS comment asking them not to had already gone stale. In a
  100%-inline-`style={}` app this can only be enforced mechanically.
- **It is the ONLY `!important` in the project. Keep it that way** — a specificity
  fight anywhere else is a design problem to fix in the component. `mobileFieldGuard.test.ts`
  checks both sheets and fails if a second one appears, if the landing page grows
  one, or if either floor is dropped.
- **Element-level, not container-scoped.** The landing page had pinned 16px via
  `.auth-field input` and `.access-form textarea` — which covered its four fields
  only by markup coincidence (the access form's email input is saved by sitting in
  a label classed for the *modal*). A `<select>` anywhere, or a field added to the
  wrong wrapper, matched nothing and fell to the UA default (~13.3px). Pin the
  floor on the elements, not on whatever container happens to exist today.
- **You may still set an inline `font-size` on a field** — it applies on desktop
  and is simply overridden below 640px. That's the point: no `isMobile ? 16 : x`
  ternary needed, and module-level `CSSProperties` consts (which can't call a hook)
  stay valid.
- **Exception to know:** the rule also clamps fields that legitimately want *more*
  than 16px on mobile. None exist today; if one does, narrow the selector rather
  than fighting it inline.
- Checkboxes and radios are excluded — no text to zoom, and a 40px floor would
  balloon them.
- jsdom evaluates neither `@media` nor the inline-vs-author cascade, so **no render
  test can observe this.** Proof is a `getComputedStyle` measurement at 375px in the
  browser preview (see the mandatory two-theme check above).

## Other conventions
- Responsiveness is JS-driven via `useIsMobile()` (the app is 100% inline
  `style={}`, so CSS `@media` can't reach it). Test mobile with
  `setMobileViewport(true)` and the preview at 375px.
- Typecheck with **`tsc -b`** (not `tsc --noEmit`) — it covers test files and
  matches the Docker build. Every PR includes Vitest tests for new/changed UI.
- Running tooling on the Windows host: `tsc`/`eslint` run via
  `node node_modules/typescript/bin/tsc -b` / `node node_modules/eslint/bin/eslint.js .`
  (pure JS). **Vitest/Vite can't run on the host** (missing win32 native bindings) —
  run them in a `node:26.4.0` container with a cached `node_modules` volume, and
  drive the browser preview via a throwaway Vite container on the compose network
  (`VITE_PROXY_TARGET=http://backend:8000`). Exact commands are in project memory.
